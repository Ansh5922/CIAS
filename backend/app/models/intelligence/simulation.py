from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Simulation(Base):
    __tablename__ = "simulations"

    simulation_id = Column(BigInteger, primary_key=True, index=True)
    simulation_name = Column(String(255))
    simulation_type = Column(String(100))
    description = Column(Text)
    parameters = Column(JSONB)
    results = Column(JSONB)
    created_by = Column(BigInteger, ForeignKey("users.user_id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    creator = relationship("User")
