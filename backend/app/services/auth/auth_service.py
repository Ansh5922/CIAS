from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.schemas.auth.auth import RegisterRequest, LoginRequest, UserResponse, Token
from app.repositories.user_repository import UserRepository
from app.repositories.role_repository import RoleRepository
from app.models.auth.user import User
from app.core.security import hash_password, verify_password, create_access_token


class AuthService:
    """Service layer for authentication business logic."""
    def __init__(self, db: Session):
        self.db = db
        self.user_repo = UserRepository(db)
        self.role_repo = RoleRepository(db)

    def register_user(self, data: RegisterRequest) -> User:
        """Contains logic to check for duplicates and create a new user."""
        if self.user_repo.get_by_email(data.email):
            raise HTTPException(status_code=400, detail="Email already registered")

        role = self.role_repo.get_by_name("Citizen")
        if not role:
            raise HTTPException(status_code=500, detail="Default role 'Citizen' not found in database")

        user = User(
            full_name=data.full_name,
            email=data.email,
            phone=data.phone,
            password_hash=hash_password(data.password),
            role_id=role.role_id,
            is_active=True
        )

        return self.user_repo.create(user)

    def login_user(self, data: LoginRequest) -> Token:
        """Validates credentials and responds with a JWT."""
        user = self.user_repo.get_by_email(data.email)
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        
        if not user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")

        access_token = create_access_token(subject=str(user.user_id))
        return Token(access_token=access_token, token_type="bearer")
