from sqlalchemy import Column, BigInteger, String, Numeric, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Hotspot(Base):
    __tablename__ = "hotspots"

    hotspot_id = Column(BigInteger, primary_key=True, index=True)
    location_id = Column(BigInteger, ForeignKey("locations.location_id"))
    risk_score = Column(Numeric(5, 2))
    hotspot_level = Column(String(20))
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    location = relationship("Location")
