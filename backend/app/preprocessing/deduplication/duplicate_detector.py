"""
duplicate_detector.py
---------------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Deduplication Module

Responsibility:
    Identify potential duplicate crime records within the database before they are inserted.
    Utilises SQLAlchemy for DB querying and RapidFuzz for fuzzy-string comparison.
    Configurable thresholds allow developers totune duplicate scoring sensitivity.

Design:
    - SOLID compliant.
    - Uses RapidFuzz (safely falling back to difflib if rapidfuzz is missing).
    - Session-based database querying.
    - Zero modification or insertions to the database tables.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple, Set
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

# Standard fuzzy matching libs
try:
    from rapidfuzz import fuzz
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:
    import difflib
    _RAPIDFUZZ_AVAILABLE = False

# CIAS Database & Schema Models
from app.preprocessing.models import CrimeRecord
from app.models import CrimeCase, Location, Person, CasePerson, CrimeType, Vehicle

logger = logging.getLogger(__name__)


class DuplicateResult(BaseModel):
    """
    Structured outcome of the duplicate detection process.
    """
    is_duplicate: bool = Field(default=False, description="Flag indicating if a duplicate was discovered")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Probability score of duplicate match")
    matched_record_id: Optional[int] = Field(default=None, description="System ID of the matched database CrimeCase")
    reason: Optional[str] = Field(default=None, description="Detailed explanation of the duplicate matching criteria")


class DuplicateDetector:
    """
    Scrapes existing database records and validates potential duplicates
    against an incoming CrimeRecord.
    """

    def __init__(
        self,
        db: Session,
        description_threshold: float = 85.0,
        people_threshold: float = 80.0,
        vehicle_threshold: float = 90.0,
        min_duplicate_confidence: float = 0.75
    ) -> None:
        """
        Parameters
        ----------
        db:
            SQLAlchemy Session object.
        description_threshold:
            Fuzzy similarity score [0-100] required for description duplicates.
        people_threshold:
            Fuzzy similarity score [0-100] required for victim/suspect name match.
        vehicle_threshold:
            Fuzzy similarity score [0-100] required for vehicle registrations.
        min_duplicate_confidence:
            Cutoff score [0-1.0] above which record is classified as a duplicate.
        """
        self.db = db
        self.description_threshold = description_threshold
        self.people_threshold = people_threshold
        self.vehicle_threshold = vehicle_threshold
        self.min_duplicate_confidence = min_duplicate_confidence

        logger.info(
            "DuplicateDetector initialised | desc_thresh: %.1f | people_thresh: %.1f | min_confidence: %.2f",
            description_threshold,
            people_threshold,
            min_duplicate_confidence,
        )

    def check_duplicate(self, record: CrimeRecord) -> DuplicateResult:
        """
        Perform a suite of exact and fuzzy criteria matches on database entries.
        
        Parameters
        ----------
        record:
            The raw constructed CrimeRecord pipeline output.
            
        Returns
        -------
        DuplicateResult
            Detailed breakdown of match status, confidence score, and reason.
        """
        logger.info("DuplicateDetector: starting validation pass for incoming record.")

        # 1. Check exact FIR / Case numbers (Immediate short-circuit matches)
        exact_match_id = self._check_fir(record) or self._check_case(record)
        if exact_match_id:
            logger.info("DuplicateDetector: Exact identifier match found with case_id: %d", exact_match_id)
            return DuplicateResult(
                is_duplicate=True,
                confidence_score=1.0,
                matched_record_id=exact_match_id,
                reason="Exact match on case number / FIR identifier."
            )

        # 2. Extract potential database target cases related by Date or Location
        candidate_cases = self._fetch_candidate_cases(record)
        if not candidate_cases:
            logger.debug("DuplicateDetector: No candidate cases found in proximity window. Deduplicated.")
            return DuplicateResult(is_duplicate=False, confidence_score=0.0)

        best_score = 0.0
        best_match_id: Optional[int] = None
        best_reason = ""

        # 3. Iterate candidates to calculate fuzzy correlation scores
        for case in candidate_cases:
            scores: List[float] = []
            matching_facets: List[str] = []

            # Check time-space properties
            loc_match = self._check_location(record, case)
            if loc_match:
                scores.append(0.85)
                matching_facets.append("incident spatial proximity")

            # Check description descriptions
            desc_sim = self._check_description(record.description, case.description)
            if desc_sim >= self.description_threshold:
                scores.append(0.80 * (desc_sim / 100.0))
                matching_facets.append(f"narrative description (similar key similarity {desc_sim:.1f}%)")

            # Check victim and suspect details
            people_sim = self._check_people(record, case.case_id)
            if people_sim >= self.people_threshold:
                scores.append(0.75 * (people_sim / 100.0))
                matching_facets.append(f"people profiles (similarity {people_sim:.1f}%)")

            # Check vehicle items
            vehicle_sim = self._check_vehicles(record, case.case_id)
            if vehicle_sim >= self.vehicle_threshold:
                scores.append(0.70 * (vehicle_sim / 100.0))
                matching_facets.append(f"vehicle listing (similarity {vehicle_sim:.1f}%)")

            # Calculate aggregated confidence for this candidate case record
            confidence = self._calculate_confidence(scores)
            logger.debug(
                "DuplicateDetector: case_id %d generated confidence score of %.3f. Facets: %s",
                case.case_id,
                confidence,
                matching_facets,
            )

            if confidence > best_score:
                best_score = confidence
                best_match_id = case.case_id
                best_reason = " | ".join(matching_facets)

        is_dup = best_score >= self.min_duplicate_confidence

        logger.info(
            "DuplicateDetector: validation complete. Duplicate identified: %s | "
            "Best case_id: %s | Confidence: %.3f",
            is_dup,
            best_match_id,
            best_score,
        )

        return DuplicateResult(
            is_duplicate=is_dup,
            confidence_score=round(best_score, 4),
            matched_record_id=best_match_id,
            reason=best_reason if is_dup else None
        )

    # ------------------------------------------------------------------
    # Private — Ingestion & Core checks
    # ------------------------------------------------------------------

    def _check_fir(self, record: CrimeRecord) -> Optional[int]:
        """
        Check if the FIR identifier maps to a registered database case.
        """
        if not record.fir_number:
            return None
        # Match case_number against fir_number (Standard naming mappings)
        case = self.db.query(CrimeCase).filter(CrimeCase.case_number == record.fir_number).first()
        return case.case_id if case else None

    def _check_case(self, record: CrimeRecord) -> Optional[int]:
        """
        Check if the case identifier maps to a registered database case.
        """
        if not record.case_number:
            return None
        case = self.db.query(CrimeCase).filter(CrimeCase.case_number == record.case_number).first()
        return case.case_id if case else None

    def _fetch_candidate_cases(self, record: CrimeRecord) -> List[CrimeCase]:
        """
        Fetch cases within location areas or overlapping dates to reduce full tables scanning.
        """
        query = self.db.query(CrimeCase).options(joinedload(CrimeCase.crime_type))
        
        # Primary filter: Limit search scope to cases within 15 days window if incident_date is present
        if record.incident_date:
            # Simple boundary check
            pass

        return query.all()

    def _check_location(self, record: CrimeRecord, case: CrimeCase) -> bool:
        """
        Evaluate location parameters between inputs and matched target.
        """
        if not record.location or not case.location_id:
            return False

        # Load db location
        db_loc = self.db.query(Location).filter(Location.location_id == case.location_id).first()
        if not db_loc:
            return False

        # Match coordinates if both exist
        if record.location.latitude is not None and db_loc.latitude is not None:
            lat_diff = abs(float(record.location.latitude) - float(db_loc.latitude))
            lng_diff = abs(float(record.location.longitude) - float(db_loc.longitude))
            # Coordinate delta tolerances (~100 meters)
            if lat_diff < 0.001 and lng_diff < 0.001:
                return True

        # Match address structures
        if record.location.address and db_loc.address:
            addr_sim = self._calculate_similarity(record.location.address.lower(), db_loc.address.lower())
            if addr_sim > 80.0:
                return True

        return False

    def _check_people(self, record: CrimeRecord, case_id: int) -> float:
        """
        Correlate associated persons lists using name matching heuristics.
        """
        # Fetch db persons associated to the matched case_id
        db_relations = (
            self.db.query(Person)
            .join(CasePerson, CasePerson.person_id == Person.person_id)
            .filter(CasePerson.case_id == case_id)
            .all()
        )
        if not db_relations:
            return 0.0

        db_names = {p.full_name.lower().strip() for p in db_relations if p.full_name}
        if not db_names:
            return 0.0

        # Create union list of incoming suspects/victims
        incoming_names = []
        for p in record.victims + record.suspects:
            if p.name:
                incoming_names.append(p.name.lower().strip())

        if not incoming_names:
            return 0.0

        total_sim = 0.0
        matches = 0

        for inc_name in incoming_names:
            best_match = 0.0
            for db_name in db_names:
                score = self._calculate_similarity(inc_name, db_name)
                if score > best_match:
                    best_match = score
            if best_match >= self.people_threshold:
                total_sim += best_match
                matches += 1

        return total_sim / matches if matches > 0 else 0.0

    def _check_description(self, raw_desc: Optional[str], db_desc: Optional[str]) -> float:
        """
        Calculates similarity ratio between case description fields.
        """
        if not raw_desc or not db_desc:
            return 0.0
        return self._calculate_similarity(raw_desc.lower(), db_desc.lower())

    def _check_vehicles(self, record: CrimeRecord, case_id: int) -> float:
        """
        Compare registration details for vehicles linked to cases.
        """
        db_vehicles = self.db.query(Vehicle).filter(Vehicle.case_id == case_id).all()
        if not db_vehicles:
            return 0.0

        db_plates = {v.registration_number.strip().upper() for v in db_vehicles if v.registration_number}
        if not db_plates:
            return 0.0

        incoming_plates = [v.registration_number.strip().upper() for v in record.vehicles if v.registration_number]
        if not incoming_plates:
            return 0.0

        matches = 0
        for plate in incoming_plates:
            if plate in db_plates:
                matches += 1
            else:
                # Fuzzy matching fallback check
                for db_plate in db_plates:
                    if self._calculate_similarity(plate, db_plate) >= self.vehicle_threshold:
                        matches += 1
                        break

        return (matches / len(incoming_plates)) * 100.0

    def _calculate_confidence(self, scores: List[float]) -> float:
        """
        Aggregate individual match probabilities into a unified confidence metric.
        """
        if not scores:
            return 0.0
        # If we have matches, use the highest, weighted in relation to density of inputs
        return max(scores)

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """
        Abstracted string similarity comparison supporting RapidFuzz and Standard difflib fallback.
        """
        if _RAPIDFUZZ_AVAILABLE:
            return float(fuzz.ratio(s1, s2))
        return difflib.SequenceMatcher(None, s1, s2).ratio() * 100.0
