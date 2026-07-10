from sqlalchemy import Column, BigInteger, String, Text, SmallInteger, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class CrimeCase(Base):
    __tablename__ = "crime_cases"

    case_id = Column(BigInteger, primary_key=True, index=True)
    case_number = Column(String(100), unique=True)
    crime_type_id = Column(BigInteger, ForeignKey("crime_types.crime_type_id"))
    location_id = Column(BigInteger, ForeignKey("locations.location_id"))
    police_station_id = Column(BigInteger, ForeignKey("police_stations.station_id"))
    
    title = Column(String(255))
    description = Column(Text)
    incident_time = Column(DateTime(timezone=True))
    reported_time = Column(DateTime(timezone=True))
    priority = Column(SmallInteger)
    source = Column(String(30))
    confidence_score = Column(Numeric(5, 2))
    status = Column(String(30))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    crime_type = relationship("CrimeType", back_populates="cases")
