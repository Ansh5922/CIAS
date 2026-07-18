from sqlalchemy import Column, BigInteger, String, Text, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    vehicle_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"), nullable=False)
    
    registration_number = Column(String(50))
    vehicle_type = Column(String(50))
    brand = Column(String(100))
    model = Column(String(100))
    color = Column(String(50))
    owner = Column(String(150))
    remarks = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    case = relationship("CrimeCase")
