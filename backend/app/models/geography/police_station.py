from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class PoliceStation(Base):
    __tablename__ = "police_stations"

    station_id = Column(BigInteger, primary_key=True, index=True)
    station_name = Column(String(150))
    station_code = Column(String(30))
    address = Column(Text)
    phone = Column(String(20))
    email = Column(String(150))
    ward_id = Column(BigInteger, ForeignKey("wards.ward_id"))
    location_id = Column(BigInteger, ForeignKey("locations.location_id"))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    ward = relationship("Ward")
    location = relationship("Location")
