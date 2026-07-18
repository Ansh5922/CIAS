"""
validator.py
------------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Validation Module

Responsibility:
    Validate and normalize a given CrimeRecord object.
    It checks data rules (required fields, range limits, time ordering,
    duplicate relations, missing descriptions) and separates structural
    validation errors (which make a record invalid) from compliance warnings.

    This validator does NOT:
        - Query databases
        - Perform geocoding
        - Run duplicate detection against database records
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any, List, Set, Tuple

# CIAS Preprocessing Imports
from app.preprocessing.models import CrimeRecord, ProcessingResult
from app.preprocessing.models import (
    PersonRole,
    SourceType,
    Gender,
    CrimeStatus,
    MediaType,
    VehicleType,
    WeaponType,
)

logger = logging.getLogger(__name__)


class CrimeRecordValidator:
    """
    Validates CrimeRecord models for logical completeness and schema compliance.
    
    Performs standard normalizations (e.g. trimming string spaces) and collects
    errors (critical validation failures) and warnings (non-critical failures).
    
    Typical usage:
    --------------
    >>> validator = CrimeRecordValidator()
    >>> result = validator.validate(crime_record)
    >>> if not result.success:
    ...     print("Validation failed:", result.errors)
    """

    def validate(self, record: CrimeRecord) -> ProcessingResult:
        """
        Executes all validation routines on the given CrimeRecord.
        
        Modifies the record in-place by normalizing string values, and updating
        its `is_valid` and `validation_errors` properties prior to wrapping
        the output in a ProcessingResult object.
        
        Parameters
        ----------
        record:
            The CrimeRecord model instance.
            
        Returns
        -------
        ProcessingResult:
            Valued status wrapper containing validation errors, warning logs, 
            and the normalized/updated CrimeRecord.
        """
        start_time = time.time()
        logger.info("Validation sequence initiated for record.")

        errors: List[str] = []
        warnings: List[str] = []

        try:
            # 1. Strip and normalize all string fields recursively
            self._normalize_strings(record)

            # 2. Run validations
            self._validate_required_fields(record, errors)
            self._validate_temporal_data(record, errors)
            self._validate_location(record, errors)
            self._validate_confidence_score(record, errors)
            self._validate_entities(record, errors, warnings)
            self._validate_enums(record, errors)

        except Exception as exc:
            logger.exception("Unexpected error inside validator runtime.")
            errors.append(f"Validator system exception: {exc}")

        # Update record validation flags
        record.is_valid = len(errors) == 0
        record.validation_errors = errors

        # Wrap in standard processing outcome
        result = ProcessingResult(
            success=record.is_valid,
            message="Record validation completed successfully." if record.is_valid else "Record failed validation checks.",
            processing_time_seconds=round(time.time() - start_time, 4),
            record=record,
            errors=errors,
            warnings=warnings
        )

        logger.info(
            "Validation finished: valid=%s | Errors: %d | Warnings: %d | Time: %.4fs",
            record.is_valid,
            len(errors),
            len(warnings),
            result.processing_time_seconds,
        )
        return result

    # ------------------------------------------------------------------
    # Private — Normalization methods
    # ------------------------------------------------------------------

    def _normalize_strings(self, obj: Any) -> None:
        """
        Recursively traverses a Pydantic model or data structure and trims
        leading/trailing spaces from all string values.
        """
        if not obj:
            return

        # Handle simple lists
        if isinstance(obj, list):
            for item in obj:
                self._normalize_strings(item)
            return

        # Traverse fields if it is a Pydantic model
        if hasattr(obj, "model_fields"):
            for field_name in obj.model_fields.keys():
                val = getattr(obj, field_name)
                if isinstance(val, str):
                    setattr(obj, field_name, val.strip())
                elif isinstance(val, list):
                    for item in val:
                        self._normalize_strings(item)
                elif hasattr(val, "model_fields"):
                    self._normalize_strings(val)

    # ------------------------------------------------------------------
    # Private — Validation methods
    # ------------------------------------------------------------------

    def _validate_required_fields(self, record: CrimeRecord, errors: List[str]) -> None:
        """
        Verify that core identifiably unique fields exist.
        """
        if not record.fir_number and not record.case_number:
            errors.append("Invalid Record: Both 'fir_number' and 'case_number' are missing.")

        if not record.crime_type:
            errors.append("Invalid Record: Missing 'crime_type'.")

        if not record.incident_date:
            errors.append("Invalid Record: Missing 'incident_date'.")

    def _validate_temporal_data(self, record: CrimeRecord, errors: List[str]) -> None:
        """
        Check that date/time are logical and correctly relative to each other.
        """
        today = date.today()
        now = datetime.utcnow()

        # Check incident date limits
        if record.incident_date:
            if record.incident_date > today:
                errors.append(f"Temporal Exception: 'incident_date' ({record.incident_date}) is in the future.")

            if record.incident_date.year < 1900:
                errors.append(f"Temporal Exception: 'incident_date' ({record.incident_date}) is chronologically too old (pre-1900).")

        # Check report date limits
        if record.report_date:
            if record.report_date > now:
                errors.append(f"Temporal Exception: 'report_date' ({record.report_date}) is in the future.")

            # Validate relative constraint: report_date must not occur before incident_date
            if record.incident_date:
                # Convert date to datetime at start of day for comparison
                incident_dt = datetime.combine(record.incident_date, datetime.min.time())
                if record.report_date < incident_dt:
                    errors.append(
                        f"Temporal Exception: 'report_date' ({record.report_date}) cannot occur before "
                        f"'incident_date' ({record.incident_date})."
                    )

    def _validate_location(self, record: CrimeRecord, errors: List[str]) -> None:
        """
        Check coordinates fields are within boundary range:
        - Lat: [-90.0, 90.0]
        - Lng: [-180.0, 180.0]
        """
        if not record.location:
            return

        lat = record.location.latitude
        lng = record.location.longitude

        if lat is not None:
            if lat < -90.0 or lat > 90.0:
                errors.append(f"Coordinates Exception: Latitude ({lat}) falls outside coordinate bounds [-90, 90].")

        if lng is not None:
            if lng < -180.0 or lng > 180.0:
                errors.append(f"Coordinates Exception: Longitude ({lng}) falls outside coordinate bounds [-180, 180].")

    def _validate_confidence_score(self, record: CrimeRecord, errors: List[str]) -> None:
        """
        Verify the AI extraction quality score is bounded contextually [0, 1].
        """
        score = record.confidence_score
        if score is not None:
            if score < 0.0 or score > 1.0:
                errors.append(f"Validation Exception: Extraction confidence_score ({score}) falls outside scale [0.0, 1.0].")

    def _validate_entities(self, record: CrimeRecord, errors: List[str], warnings: List[str]) -> None:
        """
        Validates entity lists and descriptions:
        - Verifiably missing descriptions are flagged.
        - Identifies duplicate persons within lists.
        - Identifies duplicate vehicles within lists.
        """
        # A. Empty Descriptions
        if not record.description or not record.description.strip():
            warnings.append("Compliance warning: 'description' narrative is empty.")

        # B. Duplicate persons checking
        # Check distinct list categories individually
        self._check_duplicate_persons("victims", record.victims, errors, warnings)
        self._check_duplicate_persons("suspects", record.suspects, errors, warnings)
        self._check_duplicate_persons("witnesses", record.witnesses, errors, warnings)
        self._check_duplicate_persons("officers", record.officers, errors, warnings)

        # C. Duplicate vehicles checking
        seen_vehicles: Set[str] = set()
        for idx, vehicle in enumerate(record.vehicles):
            if vehicle.registration_number:
                reg_clean = vehicle.registration_number.strip().upper()
                if reg_clean in seen_vehicles:
                    warnings.append(
                        f"Compliance warning: Duplicate vehicle registration '{vehicle.registration_number}' "
                        f"found at index {idx} in vehicles list."
                    )
                else:
                    seen_vehicles.add(reg_clean)

    def _check_duplicate_persons(self, list_name: str, persons_list: List[Any], errors: List[str], warnings: List[str]) -> None:
        """
        Helper method to isolate duplicates inside individual person roles array by name or ID.
        """
        seen_names: Set[str] = set()
        seen_ids: Set[str] = set()

        for idx, person in enumerate(persons_list):
            # Check national ID duplicates
            if person.identification_number:
                id_clean = person.identification_number.strip().upper()
                if id_clean in seen_ids:
                    warnings.append(
                        f"Compliance warning: Duplicate identification number '{id_clean}' found "
                        f"for person at index {idx} in {list_name} list."
                    )
                else:
                    seen_ids.add(id_clean)

            # Check name duplicates
            if person.name:
                name_clean = person.name.strip().lower()
                if name_clean in seen_names:
                    warnings.append(
                        f"Compliance warning: Duplicate name '{person.name}' found "
                        f"for person at index {idx} in {list_name} list."
                    )
                else:
                    seen_names.add(name_clean)

    def _validate_enums(self, record: CrimeRecord, errors: List[str]) -> None:
        """
        Verify that values match predefined constants.
        """
        # Status check
        if record.status and record.status not in CrimeStatus.__members__.values():
            errors.append(f"Enum constraint exception: Current status '{record.status}' is not a valid CrimeStatus.")

        # Source type check
        if record.source_type and record.source_type not in SourceType.__members__.values():
            errors.append(f"Enum constraint exception: Current source_type '{record.source_type}' is not a valid SourceType.")

        # Validate people details
        for index, person in enumerate(record.victims):
            self._validate_person_enums(f"victims[{index}]", person, errors)
        for index, person in enumerate(record.suspects):
            self._validate_person_enums(f"suspects[{index}]", person, errors)
        for index, person in enumerate(record.witnesses):
            self._validate_person_enums(f"witnesses[{index}]", person, errors)
        for index, person in enumerate(record.officers):
            self._validate_person_enums(f"officers[{index}]", person, errors)

        # Validate vehicles
        for index, vehicle in enumerate(record.vehicles):
            if vehicle.vehicle_type and vehicle.vehicle_type not in VehicleType.__members__.values():
                errors.append(
                    f"Enum constraint exception: Vehicle type '{vehicle.vehicle_type}' at indices {index} "
                    f"is not a valid VehicleType."
                )

        # Validate weapons
        for index, weapon in enumerate(record.weapons):
            if weapon.weapon_type and weapon.weapon_type not in WeaponType.__members__.values():
                errors.append(
                    f"Enum constraint exception: Weapon type '{weapon.weapon_type}' at indices {index} "
                    f"is not a valid WeaponType."
                )

        # Validate media
        for index, item in enumerate(record.media):
            if item.media_type and item.media_type not in MediaType.__members__.values():
                errors.append(
                    f"Enum constraint exception: Media type '{item.media_type}' at indices {index} "
                    f"is not a valid MediaType."
                )

    def _validate_person_enums(self, ref_name: str, person: Any, errors: List[str]) -> None:
        """
        Helper method to validate person properties structure.
        """
        if person.gender and person.gender not in Gender.__members__.values():
            errors.append(f"Enum constraint exception: Gender '{person.gender}' for '{ref_name}' is not a valid Gender.")
        
        if person.role and person.role not in PersonRole.__members__.values():
            errors.append(f"Enum constraint exception: Role '{person.role}' for '{ref_name}' is not a valid PersonRole.")
