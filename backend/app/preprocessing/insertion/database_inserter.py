"""
database_inserter.py
--------------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Database Insertion Module

Responsibility:
    Insert objects mapped by a validated CrimeRecord schema into the production PostgreSQL database.
    Integrates via SQLAlchemy ORM transactions, safely managing rollbacks on integrity violations.
    Updates related job logs (preprocessing_jobs) upon completion.

Design:
    - Follows SOLID principles:
        S — Single Responsibility: database record persistence.
        O — Open/Closed: extensible schemas support.
        L — Liskov-safe: accepts CrimeRecord pydantic schema.
        I — Interface-segregated: simple entry point.
        D — DB Session injection.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

# CIAS Database Models
from app.preprocessing.models import CrimeRecord
from app.models import (
    CrimeCase,
    Location,
    Person,
    CasePerson,
    CrimeType,
    Vehicle,
    Weapon,
    Evidence,
    CrimeMedia,
    PreprocessingJob
)

logger = logging.getLogger(__name__)


class DatabaseInserter:
    """
    Manages persistence of CrimeRecord structures into database tables.
    Runs all inserts in an isolated transaction to prevent partial case insertions.
    """

    def __init__(self, db: Session) -> None:
        """
        Parameters
        ----------
        db:
            SQLAlchemy Session object.
        """
        self.db = db
        logger.info("DatabaseInserter: initialised with DB Session.")

    def insert(self, record: CrimeRecord, job_id: Optional[int] = None) -> int:
        """
        Insert the CrimeRecord into PostgreSQL tables.
        
        Saves locations, cases, victims, suspects, witnesses, officers, 
        weapons, vehicles, evidence, media inside a unified transaction.
        
        Parameters
        ----------
        record:
            Validated CrimeRecord instance.
        job_id:
            Optional ID of the active PreprocessingJob processing this record.

        Returns
        -------
        int
            The case_id of the newly created parent CrimeCase.

        Raises
        ------
        IntegrityError
            If DB constraints or unique keys are violated.
        Exception
            For other SQL errors (causing a transaction rollback).
        """
        logger.info("DatabaseInserter: commencing persistence transaction.")
        
        # Start transaction block
        try:
            # 1. Insert Location
            location_id = self._insert_location(record)

            # 2. Match or create CrimeType
            crime_type_id = self._get_or_create_crime_type(record.crime_type)

            # 3. Insert Crime Case (parent record)
            title = f"{record.crime_type or 'Incident'} report"
            if record.fir_number:
                title += f" (FIR {record.fir_number})"

            # Map incident Date/Time safely to datetime
            incident_dt: Optional[datetime] = None
            if record.incident_date:
                t_val = record.incident_time if record.incident_time else datetime.min.time()
                incident_dt = datetime.combine(record.incident_date, t_val)

            case_obj = CrimeCase(
                case_number=record.case_number or record.fir_number,
                crime_type_id=crime_type_id,
                location_id=location_id,
                title=title,
                description=record.description,
                incident_time=incident_dt,
                reported_time=record.report_date,
                confidence_score=record.confidence_score,
                status=record.status.value if record.status else "Open",
                source=record.source_type.value if record.source_type else "TEXT",
            )
            self.db.add(case_obj)
            self.db.flush()  # Populate case_id

            case_id: int = case_obj.case_id
            logger.info("DatabaseInserter: parent CrimeCase generated with case_id: %d", case_id)

            # 4. Insert associated relations
            self._insert_people(record.victims, case_id, "Victim")
            self._insert_people(record.suspects, case_id, "Suspect")
            self._insert_people(record.witnesses, case_id, "Witness")
            self._insert_people(record.officers, case_id, "Officer")
            self._insert_vehicles(record, case_id)
            self._insert_weapons(record, case_id)
            self._insert_evidence(record, case_id)
            self._insert_media(record, case_id)

            # 5. Pipeline job updates
            if job_id:
                self._update_job(job_id, status="Completed", success=True)

            self.db.commit()
            logger.info("DatabaseInserter: Transaction committed successfully for case_id: %d", case_id)
            return case_id

        except IntegrityError as exc:
            self.db.rollback()
            logger.error("DatabaseInserter: Integrity constraint violation during insert. Transaction rolled back: %s", exc)
            if job_id:
                self._update_job(job_id, status="Failed", success=False, error_msg=f"Integrity Error: {exc}")
            raise
        except Exception as exc:
            self.db.rollback()
            logger.exception("DatabaseInserter: Exception occurred during insertion. Transaction rolled back.")
            if job_id:
                self._update_job(job_id, status="Failed", success=False, error_msg=str(exc))
            raise

    # ------------------------------------------------------------------
    # Private — Ingestion Helpers
    # ------------------------------------------------------------------

    def _insert_location(self, record: CrimeRecord) -> Optional[int]:
        """
        Saves location coordinates and details.
        """
        if not record.location:
            return None

        loc = record.location
        loc_obj = Location(
            address=loc.address,
            landmark=loc.landmark,
            city=loc.locality or loc.area,
            state=loc.state,
            postal_code=loc.postal_code,
            latitude=loc.latitude,
            longitude=loc.longitude
        )
        self.db.add(loc_obj)
        self.db.flush()
        return loc_obj.location_id

    def _insert_people(self, people_list: List[Any], case_id: int, role: str) -> None:
        """
        Saves person detail attributes and maps them to CasePerson relations.
        """
        for person in people_list:
            # Check ID uniqueness to prevent duplicative Person creations in base table
            person_obj = None
            if person.identification_number:
                person_obj = self.db.query(Person).filter(
                    Person.identification_mark == person.identification_number
                ).first()

            if not person_obj:
                person_obj = Person(
                    full_name=person.name,
                    gender=person.gender.value if person.gender else None,
                    age=person.age,
                    phone=person.phone,
                    address=person.address,
                    identification_mark=person.identification_number
                )
                self.db.add(person_obj)
                self.db.flush()

            # Map Case relation
            rel_obj = CasePerson(
                case_id=case_id,
                person_id=person_obj.person_id,
                role=role,
                remarks=person.remarks
            )
            self.db.add(rel_obj)

    def _insert_vehicles(self, record: CrimeRecord, case_id: int) -> None:
        """
        Saves vehicles involved with a case.
        """
        for vehicle in record.vehicles:
            v_obj = Vehicle(
                case_id=case_id,
                registration_number=vehicle.registration_number,
                vehicle_type=vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                brand=vehicle.brand,
                model=vehicle.model,
                color=vehicle.color,
                owner=vehicle.owner,
                remarks=vehicle.remarks
            )
            self.db.add(v_obj)

    def _insert_weapons(self, record: CrimeRecord, case_id: int) -> None:
        """
        Saves weapons involved with a case.
        """
        for weapon in record.weapons:
            w_obj = Weapon(
                case_id=case_id,
                weapon_type=weapon.weapon_type.value if weapon.weapon_type else None,
                weapon_name=weapon.weapon_name,
                recovered=weapon.recovered,
                description=weapon.description
            )
            self.db.add(w_obj)

    def _insert_evidence(self, record: CrimeRecord, case_id: int) -> None:
        """
        Saves evidence attachments.
        """
        for item in record.evidence:
            ev_obj = Evidence(
                case_id=case_id,
                evidence_type=item.evidence_type,
                file_name=f"Evidence_{case_id}_{item.evidence_type}",
                file_path=item.description,  # Or standard S3 paths
                description=item.description
            )
            self.db.add(ev_obj)

    def _insert_media(self, record: CrimeRecord, case_id: int) -> None:
        """
        Saves media URLs or documents references.
        """
        for item in record.media:
            med_obj = CrimeMedia(
                case_id=case_id,
                media_type=item.media_type.value if item.media_type else None,
                file_name=item.file_name,
                file_path=item.file_path,
                mime_type=item.mime_type
            )
            self.db.add(med_obj)

    def _update_job(self, job_id: int, status: str, success: bool, error_msg: Optional[str] = None) -> None:
        """
        Helper to log pipeline milestones within PreprocessingJob records.
        """
        job = self.db.query(PreprocessingJob).filter(PreprocessingJob.job_id == job_id).first()
        if job:
            job.processing_status = status
            job.database_insertion_completed = success
            if error_msg:
                job.error_message = error_msg
            if success:
                job.completed_at = datetime.utcnow()
            self.db.flush()

    def _get_or_create_crime_type(self, crime_type_name: str) -> Optional[int]:
        """
        Resolves name strings to database CrimeType mappings, creating them dynamically on demand.
        """
        if not crime_type_name:
            return None
        
        cleaned_name = crime_type_name.strip()
        ct = self.db.query(CrimeType).filter(
            func.lower(CrimeType.crime_name) == cleaned_name.lower()
        ).first()

        if not ct:
            ct = CrimeType(
                crime_name=cleaned_name,
                severity_level=2,
                description=f"Auto-generated crime type wrapper for '{cleaned_name}'"
            )
            self.db.add(ct)
            self.db.flush()

        return ct.crime_type_id
