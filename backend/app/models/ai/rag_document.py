from sqlalchemy import Column, BigInteger, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class RagDocument(Base):
    __tablename__ = "rag_documents"

    document_id = Column(BigInteger, primary_key=True, index=True)
    file_id = Column(BigInteger, ForeignKey("uploaded_files.file_id"))
    document_title = Column(String(255))
    document_type = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    file = relationship("UploadedFile")
