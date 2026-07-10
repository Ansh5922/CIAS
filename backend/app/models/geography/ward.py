from sqlalchemy import Column, BigInteger, String, Integer, Numeric, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Ward(Base):
    __tablename__ = "wards"

    ward_id = Column(BigInteger, primary_key=True, index=True)
    ward_name = Column(String(100))
    ward_number = Column(Integer)
    population = Column(Integer)
    area_sq_km = Column(Numeric(10, 2))
    # PostGIS geometry could be added later if needed (e.g. using geoalchemy2)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    locations = relationship("Location", back_populates="ward")
