from sqlalchemy import Column, BigInteger, String, Text, SmallInteger, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class CrimeType(Base):
    __tablename__ = "crime_types"

    crime_type_id = Column(BigInteger, primary_key=True, index=True)
    crime_name = Column(String(100))
    description = Column(Text)
    severity_level = Column(SmallInteger)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    cases = relationship("CrimeCase", back_populates="crime_type")
