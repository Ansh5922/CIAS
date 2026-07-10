from sqlalchemy import Column, BigInteger, String, Boolean, DateTime, ForeignKey, Text, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True, index=True)
    full_name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False)
    phone = Column(String(15))
    password_hash = Column(Text, nullable=False)
    role_id = Column(BigInteger, ForeignKey("roles.role_id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True))
    profile_photo_url = Column(Text)
    failed_login_attempts = Column(Integer, default=0)
    account_locked = Column(Boolean, default=False)

    # Relationships
    role = relationship("Role", back_populates="users")
    # Will add other back_populates later as models are built
