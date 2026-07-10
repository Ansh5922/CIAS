from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Complaint(Base):
    __tablename__ = "complaints"

    complaint_id = Column(BigInteger, primary_key=True, index=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"))
    location_id = Column(BigInteger, ForeignKey("locations.location_id"))
    
    title = Column(String(255))
    description = Column(Text)
    complaint_type = Column(String(100))
    status = Column(String(30))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")
    location = relationship("Location")
