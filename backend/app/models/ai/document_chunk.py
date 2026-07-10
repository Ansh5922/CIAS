from sqlalchemy import Column, BigInteger, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    chunk_id = Column(BigInteger, primary_key=True, index=True)
    document_id = Column(BigInteger, ForeignKey("rag_documents.document_id"))
    chunk_number = Column(Integer)
    chunk_text = Column(Text)
    embedding_model = Column(String(100))
    embedding_generated = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("RagDocument")
