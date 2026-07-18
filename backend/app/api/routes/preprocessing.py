"""
preprocessing.py
----------------
CIAS (Crime Intelligence & Analytics System)
API Layer — Preprocessing Routes

Responsibility:
    Exposes endpoints to trigger the document ingestion pipeline.
    Allows processing of both locally uploaded files (referenced by file_id)
    and public article URLs.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

# CIAS Backend Core & Security
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.auth.user import User
from app.models.preprocessing.uploaded_file import UploadedFile
from app.models.preprocessing.preprocessing_job import PreprocessingJob

# CIAS Preprocessing Services
from app.preprocessing.pipeline import PreprocessingPipeline
from app.preprocessing.models import ProcessingResult

router = APIRouter()


class URLProcessRequest(BaseModel):
    """Payload schema for url processing."""
    url: str = Field(..., description="The public HTTP/HTTPS URL of the article to ingest")


class FileProcessRequest(BaseModel):
    """Payload schema for file id processing."""
    file_id: int = Field(..., description="The database file_id of the uploaded file to process")


@router.post("/process-url", response_model=dict, status_code=status.HTTP_200_OK)
def process_url(
    payload: URLProcessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ingest and preprocess an article from a URL.
    
    - Extract text from the website URL.
    - Run LLM extraction block to produce a CrimeRecord.
    - Validate fields, lookup and geocode locations, check duplicates, and persist.
    """
    # 1. Create a Preprocessing Job entry to track this execution
    job = PreprocessingJob(
        started_at=datetime.utcnow(),
        processing_status="Running",
        ocr_completed=False,
        entity_extraction_completed=False,
        database_insertion_completed=False
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        # 2. Instantiate and run pipeline
        pipeline = PreprocessingPipeline(db=db)
        result = pipeline.process(source=payload.url, source_type="URL", job_id=job.job_id)
        
        # 3. Commit/update job state based on execution
        if result.success:
            job.processing_status = "Completed"
            job.entity_extraction_completed = True
            job.database_insertion_completed = True
            job.completed_at = datetime.utcnow()
        else:
            job.processing_status = "Failed"
            job.error_message = result.message or "Pipeline execution failed."
        db.commit()

        return {
            "success": result.success,
            "message": result.message,
            "job_id": job.job_id,
            "errors": result.errors,
            "warnings": result.warnings
        }

    except Exception as exc:
        db.rollback()
        # Ensure job status is failed
        job.processing_status = "Failed"
        job.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"URL Ingestion pipeline failed: {exc}"
        )


@router.post("/process-file", response_model=dict, status_code=status.HTTP_200_OK)
def process_file(
    payload: FileProcessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Process an uploaded file by ID.
    
    - PDF, Image (JPG/PNG/BMP/etc.), CSV, and Excel are supported.
    - Runs OCR/extraction, LLM structure parsing, geocoding, deduplication, and persistence.
    """
    # 1. Fetch file from database
    uploaded_file = db.query(UploadedFile).filter(UploadedFile.file_id == payload.file_id).first()
    if not uploaded_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Uploaded file with ID {payload.file_id} not found."
        )

    # 2. Create the Preprocessing Job tied to the file_id
    job = PreprocessingJob(
        file_id=uploaded_file.file_id,
        started_at=datetime.utcnow(),
        processing_status="Running",
        ocr_completed=False,
        entity_extraction_completed=False,
        database_insertion_completed=False
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        # 3. Map type details
        file_type = uploaded_file.file_type.upper()  # PDF, IMAGE, CSV, EXCEL
        if file_type == "IMAGE":
            file_type = "IMAGE"

        # 4. Run pipeline
        pipeline = PreprocessingPipeline(db=db)
        result = pipeline.process(source=uploaded_file.file_path, source_type=file_type, job_id=job.job_id)

        # 5. Save job status
        if result.success:
            job.processing_status = "Completed"
            job.ocr_completed = file_type in ("PDF", "IMAGE")
            job.entity_extraction_completed = True
            job.database_insertion_completed = True
            job.completed_at = datetime.utcnow()
        else:
            job.processing_status = "Failed"
            job.error_message = result.message or "Pipeline execution failed."
        db.commit()

        return {
            "success": result.success,
            "message": result.message,
            "job_id": job.job_id,
            "errors": result.errors,
            "warnings": result.warnings
        }

    except Exception as exc:
        db.rollback()
        job.processing_status = "Failed"
        job.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File Processing pipeline failed: {exc}"
        )
