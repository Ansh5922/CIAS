from pydantic import BaseModel, EmailStr
from typing import Optional


class CitizenRegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None


class AdminRegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    admin_registration_secret: str
    phone: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    user_id: int
    full_name: str
    email: str
    phone: Optional[str] = None
    role_id: int
    is_active: bool

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[str] = None
