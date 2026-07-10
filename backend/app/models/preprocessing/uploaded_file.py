from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    file_id = Column(BigInteger, primary_key=True, index=True)
    uploaded_by = Column(BigInteger, ForeignKey("users.user_id"))
    original_file_name = Column(String(255))
    stored_file_name = Column(String(255))
    file_type = Column(String(20))
    mime_type = Column(String(100))
    file_size = Column(BigInteger)
    storage_provider = Column(String(30))
    file_path = Column(Text)
    upload_status = Column(String(30))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    uploader = relationship("User")
