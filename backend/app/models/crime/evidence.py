from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Evidence(Base):
    __tablename__ = "evidence"

    evidence_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"))
    uploaded_by = Column(BigInteger, ForeignKey("users.user_id"))
    
    evidence_type = Column(String(30))
    file_name = Column(String(255))
    file_path = Column(Text)
    description = Column(Text)
    storage_provider = Column(String(30))
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    case = relationship("CrimeCase")
    uploader = relationship("User")
