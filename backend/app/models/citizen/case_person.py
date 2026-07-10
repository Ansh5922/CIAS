from sqlalchemy import Column, BigInteger, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class CasePerson(Base):
    __tablename__ = "case_persons"

    case_person_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"))
    person_id = Column(BigInteger, ForeignKey("persons.person_id"))
    role = Column(String(20))
    remarks = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    case = relationship("CrimeCase")
    person = relationship("Person")
