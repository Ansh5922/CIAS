"""
pipeline.py
-----------
CIAS (Crime Intelligence & Analytics System)
Preprocessing Layer — Main Ingestion Pipeline Orchestrator

Responsibility:
    End-to-end orchestration of document ingestion, routing files to
    proper handlers, extracting information, model schema parsing via LLM,
    field validations, mapping geometries (geocoding), identifying duplicates,
    and database persistence.

Design:
    - Follows SOLID principles:
        S — Single Responsibility: coordinates independent services.
        O — Open/Closed: extensible extractors mapping and process hooks.
        L — Liskov-safe: standard ProcessingResult returned under all pipelines layouts.
        I — Interface-segregated: simple orchestrator entry point.
        D — Dependency Inverted: all extractors and processors are constructor-injected.
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Dict, Optional, Union
from sqlalchemy.orm import Session

# Import Pipeline Models
from app.preprocessing.models import CrimeRecord, ProcessingResult, SourceType
from app.preprocessing.deduplication import DuplicateResult

# Import Component Services
from app.preprocessing.extractors import PDFExtractor, ImageExtractor, CSVExtractor, URLExtractor
from app.preprocessing.llm.gemini_extractor import GeminiExtractor
from app.preprocessing.validation import CrimeRecordValidator
from app.preprocessing.geocoding import Geocoder
from app.preprocessing.deduplication import DuplicateDetector
from app.preprocessing.insertion import DatabaseInserter

logger = logging.getLogger(__name__)


class PreprocessingPipeline:
    """
    Orchestration coordinator running raw and structured police intelligence files
    through extraction, validation, enrichment, deduplication, and PostgreSQL database insertion.
    """

    def __init__(
        self,
        db: Session,
        pdf_extractor: Optional[PDFExtractor] = None,
        image_extractor: Optional[ImageExtractor] = None,
        csv_extractor: Optional[CSVExtractor] = None,
        url_extractor: Optional[URLExtractor] = None,
        gemini_extractor: Optional[GeminiExtractor] = None,
        validator: Optional[CrimeRecordValidator] = None,
        geocoder: Optional[Geocoder] = None,
        duplicate_detector: Optional[DuplicateDetector] = None,
        inserter: Optional[DatabaseInserter] = None,
    ) -> None:
        """
        Supports Constructor-based Dependency Injection for all components.
        Missing instances resolve automatically using default class constructor mappings.
        """
        self.db = db
        
        # Extractor engine instances
        self.pdf_extractor = pdf_extractor or PDFExtractor()
        self.image_extractor = image_extractor or ImageExtractor()
        self.csv_extractor = csv_extractor or CSVExtractor()
        self.url_extractor = url_extractor or URLExtractor()

        # Core enrichment/validation helper instances
        self.gemini_extractor = gemini_extractor or GeminiExtractor()
        self.validator = validator or CrimeRecordValidator()
        self.geocoder = geocoder or Geocoder()
        self.duplicate_detector = duplicate_detector or DuplicateDetector(db=self.db)
        self.inserter = inserter or DatabaseInserter(db=self.db)

        logger.info("PreprocessingPipeline: orchestration layer successfully assembled.")

    def process(self, source: str, source_type: str, job_id: Optional[int] = None) -> ProcessingResult:
        """
        Orchestrate files or URL paths through ingestion, geocoding, deduplication, and database insertion.
        
        Parameters
        ----------
        source:
            Filesystem location parameter or public URL target.
        source_type:
            Source extension pattern ("PDF", "IMAGE", "CSV", "EXCEL", "URL").
        job_id:
            Identity of the active PreprocessingJob pipeline entry.

        Returns
        -------
        ProcessingResult
            Pipeline run outcome summary containing the inserted CrimeRecord and pipeline logs.
        """
        start_time = time.time()
        logger.info(
            "Pipeline: Ingestion sequence triggered | Source: '%s' | Type: '%s'",
            source,
            source_type,
        )

        result = ProcessingResult()
        
        try:
            # 1. Select appropriate extractor and extract text/structured rows
            extracted_data = self._extract(source, source_type)

            # 2. Check if extraction yielded a list of rows (CSV/Excel) or a single raw text string (PDF/Image/URL)
            if isinstance(extracted_data, list):
                logger.info("Pipeline: Extracted structured record list from CSV/Excel table (%d rows).", len(extracted_data))
                
                # For multiple rows, we process each row to produce individual records
                records_processed = 0
                for row_data in extracted_data:
                    # Construct and process record in isolation
                    inc_rec = self._map_dict_to_record(row_data, source, source_type)
                    row_res = self._process_record(inc_rec, job_id)
                    
                    if row_res.success:
                        records_processed += 1
                        
                result.success = records_processed > 0
                result.message = f"Successfully loaded and inserted {records_processed}/{len(extracted_data)} table rows."
                
            else:
                logger.info("Pipeline: Extracted raw text block (%d chars). Triggering Gemini parsing.", len(extracted_data))
                
                # 3. Call Gemini Parser for unstructured logs
                gemini_res = self.gemini_extractor.extract(extracted_data)
                
                if not gemini_res.success:
                    logger.error("Pipeline: Gemini LLM extraction failed. Aborting pipeline.")
                    return gemini_res

                if not gemini_res.record:
                    raise ValueError("Gemini Extractor succeeded but did not return a valid CrimeRecord module.")
                
                # Inject pipeline metadata details
                record = gemini_res.record
                record.source_name = source
                record.extracted_text = extracted_data
                if source_type == "URL":
                    record.source_url = source
                
                # 4. Route parsed record through validation, geocoding, deduplication, and insertion
                result = self._process_record(record, job_id)

        except Exception as exc:
            logger.exception("Pipeline: Core orchestrator encountered runtime crash.")
            result.success = False
            result.message = f"Pipeline Orchestrator error: {exc}"
            result.errors.append(str(exc))

        result.processing_time_seconds = round(time.time() - start_time, 2)
        logger.info(
            "Pipeline: Ingestion sequence finalized in %.2f seconds | Success: %s",
            result.processing_time_seconds,
            result.success,
        )
        return result

    # ------------------------------------------------------------------
    # Private — Ingestion & Enrichment Helpers
    # ------------------------------------------------------------------

    def _extract(self, source: str, source_type: str) -> Union[str, List[Dict[str, Any]]]:
        """
        Direct input targets to matching file-format extractor hooks.
        """
        st_clean = source_type.upper().strip()
        logger.debug("Pipeline: Delegating extraction for format: %s", st_clean)

        if st_clean == "PDF":
            return self.pdf_extractor.extract(source)
        elif st_clean == "IMAGE":
            return self.image_extractor.extract(source)
        elif st_clean in ("CSV", "EXCEL"):
            return self.csv_extractor.extract(source)
        elif st_clean == "URL":
            return self.url_extractor.extract(source)
        else:
            raise ValueError(f"Unsupported pipeline source format type: '{source_type}'")

    def _process_record(self, record: CrimeRecord, job_id: Optional[int]) -> ProcessingResult:
        """
        Flow-control orchestrator for a single CrimeRecord instance.
        """
        # A. Validate CrimeRecord
        val_res = self._validate(record)
        if not val_res.success:
            logger.warning("Pipeline: Model failed validation checks.")
            return val_res

        # B. Geocode location properties
        self._geocode(record)

        # C. Check duplicates
        dup_res = self._check_duplicate(record)
        if dup_res.is_duplicate:
            logger.warning(
                "Pipeline: Duplicate match discovered for record (Confidence: %.3f) with case_id: %s. Inserts bypassed.",
                dup_res.confidence_score,
                dup_res.matched_record_id,
            )
            # Safe exit mapping
            return ProcessingResult(
                success=True,
                message=f"Duplicate bypassed. Match reason: '{dup_res.reason}'",
                record=record,
                warnings=[f"Identified duplicate of case_id {dup_res.matched_record_id}"]
            )

        # D. Insert record into database tables
        case_id = self._insert(record, job_id)
        
        return ProcessingResult(
            success=True,
            message=f"Successfully processed and inserted record. case_id: {case_id}",
            record=record
        )

    def _validate(self, record: CrimeRecord) -> ProcessingResult:
        """
        Route to our CrimeRecordValidator component instance.
        """
        logger.debug("Pipeline: Triggering validations pass.")
        return self.validator.validate(record)

    def _geocode(self, record: CrimeRecord) -> None:
        """
        Route to our Geocoder component instance.
        """
        if record.location:
            logger.debug("Pipeline: Triggering geolocation lookup.")
            try:
                self.geocoder.geocode(record.location)
            except Exception as exc:
                logger.error("Pipeline: Non-fatal Geocoder failure: %s", exc)

    def _check_duplicate(self, record: CrimeRecord) -> DuplicateResult:
        """
        Route to our DuplicateDetector component instance.
        """
        logger.debug("Pipeline: Triggering duplicate check.")
        try:
            return self.duplicate_detector.check_duplicate(record)
        except Exception as exc:
            logger.error("Pipeline: Non-fatal Deduplicator failure: %s", exc)
            return DuplicateResult(is_duplicate=False)

    def _insert(self, record: CrimeRecord, job_id: Optional[int]) -> int:
        """
        Route to our DatabaseInserter component instance.
        """
        logger.debug("Pipeline: Triggering SQLAlchemy DB insertions pass.")
        return self.inserter.insert(record, job_id)

    # ------------------------------------------------------------------
    # Private — Table translation helper
    # ------------------------------------------------------------------

    def _map_dict_to_record(self, row_data: Dict[str, Any], source: str, source_type: str) -> CrimeRecord:
        """
        Helps build a CrimeRecord from a single row dictionary (CSV/Excel).
        """
        # Map source enum
        src_map = SourceType.CSV if source_type.upper() == "CSV" else SourceType.EXCEL
        
        # Build core CrimeRecord structure from dictionary keys
        record = CrimeRecord(
            source_type=src_map,
            source_name=source,
            fir_number=row_data.get("fir_number"),
            case_number=row_data.get("case_number"),
            crime_type=row_data.get("crime_type"),
            crime_category=row_data.get("crime_category"),
            description=row_data.get("description"),
            modus_operandi=row_data.get("modus_operandi"),
            motive=row_data.get("motive")
        )
        
        # Parse dates strings if present (or rely on Pydantic to do it during creation)
        # Let's map date properties safely
        # Optional: Map location/people attributes if CSV columns maps match
        
        return record
