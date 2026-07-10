from sqlalchemy import Column, BigInteger, String, Text, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class CrimeNews(Base):
    __tablename__ = "crime_news"

    news_id = Column(BigInteger, primary_key=True, index=True)
    case_id = Column(BigInteger, ForeignKey("crime_cases.case_id"))
    
    title = Column(String(500))
    source_name = Column(String(150))
    article_url = Column(Text)
    article_text = Column(Text)
    published_at = Column(DateTime(timezone=True))
    extracted = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    case = relationship("CrimeCase")
