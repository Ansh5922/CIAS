from sqlalchemy import Column, BigInteger, String, Text, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Location(Base):
    __tablename__ = "locations"

    location_id = Column(BigInteger, primary_key=True, index=True)
    address = Column(Text)
    landmark = Column(String(255))
    city = Column(String(100))
    state = Column(String(100))
    postal_code = Column(String(10))
    ward_id = Column(BigInteger, ForeignKey("wards.ward_id"))
    latitude = Column(Numeric(10, 8))
    longitude = Column(Numeric(11, 8))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    ward = relationship("Ward", back_populates="locations")
