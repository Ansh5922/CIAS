from sqlalchemy import Column, BigInteger, String, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Weapon(Base):
    __tablename__ = "weapons"

    weapon_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"), nullable=False)
    
    weapon_type = Column(String(50))
    weapon_name = Column(String(100))
    recovered = Column(Boolean, default=False)
    description = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    case = relationship("CrimeCase")
