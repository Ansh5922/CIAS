from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.schemas.auth.auth import CitizenRegisterRequest, AdminRegisterRequest, LoginRequest, UserResponse, Token
from app.repositories.user_repository import UserRepository
from app.repositories.role_repository import RoleRepository
from app.models.auth.user import User
from app.core.security import hash_password, verify_password, create_access_token
from app.core.config import settings


class AuthService:
    """Service layer for authentication business logic."""
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.role_repo = RoleRepository(db)

    def _register_base_user(self, data: CitizenRegisterRequest | AdminRegisterRequest, role_name: str) -> User:
        """Base registration logic checking for duplicates and assigning role."""
        if self.user_repo.get_by_email(data.email):
            raise HTTPException(status_code=400, detail="Email already registered")

        role = self.role_repo.get_by_name(role_name)
        if not role:
            raise HTTPException(status_code=500, detail=f"Role '{role_name}' not found in database")

        user = User(
            full_name=data.full_name,
            email=data.email,
            phone=data.phone,
            password_hash=hash_password(data.password),
            role_id=role.role_id,
            is_active=True
        )

        return self.user_repo.create(user)

    def register_citizen(self, data: CitizenRegisterRequest) -> User:
        """Logic for registering a public citizen."""
        return self._register_base_user(data, "Citizen")

    def register_admin(self, data: AdminRegisterRequest) -> User:
        """Logic for registering an admin requiring a valid secret key."""
        if data.admin_registration_secret != settings.ADMIN_REGISTRATION_SECRET:
            raise HTTPException(status_code=401, detail="Invalid administrator registration secret")
            
        return self._register_base_user(data, "Administration")

    def login_role_specific(self, data: LoginRequest, expected_role: str) -> Token:
        """Validates credentials and issues a JWT only if the user possesses the expected role bound to this portal."""
        user = self.user_repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")
            
        if not user.role or user.role.role_name != expected_role:
             raise HTTPException(status_code=403, detail="You do not have the required permissions to access this portal")

        access_token = create_access_token(subject=str(user.user_id))
        return Token(access_token=access_token, token_type="bearer")
