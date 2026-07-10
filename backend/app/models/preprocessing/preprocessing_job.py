from sqlalchemy import Column, BigInteger, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class PreprocessingJob(Base):
    __tablename__ = "preprocessing_jobs"

    job_id = Column(BigInteger, primary_key=True, index=True)
    file_id = Column(BigInteger, ForeignKey("uploaded_files.file_id"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    processing_status = Column(String(30))
    ocr_completed = Column(Boolean, default=False)
    entity_extraction_completed = Column(Boolean, default=False)
    database_insertion_completed = Column(Boolean, default=False)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    file = relationship("UploadedFile")
