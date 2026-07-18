from sqlalchemy import Column, BigInteger, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class CrimeMedia(Base):
    __tablename__ = "crime_media"

    media_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"), nullable=False)
    uploaded_by = Column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    
    media_type = Column(String(30))
    file_name = Column(String(255))
    file_path = Column(Text)
    mime_type = Column(String(100))
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    case = relationship("CrimeCase")
    uploader = relationship("User")
