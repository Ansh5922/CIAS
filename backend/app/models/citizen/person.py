from sqlalchemy import Column, BigInteger, String, Text, SmallInteger, Boolean, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Person(Base):
    __tablename__ = "persons"

    person_id = Column(BigInteger, primary_key=True, index=True)
    full_name = Column(String(150))
    gender = Column(String(20))
    age = Column(SmallInteger)
    phone = Column(String(20))
    address = Column(Text)
    identification_mark = Column(Text)
    is_unknown = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
