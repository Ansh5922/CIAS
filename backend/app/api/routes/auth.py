from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas.auth.auth import RegisterRequest, UserResponse, Token, LoginRequest
from app.services.auth.auth_service import AuthService
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.auth.user import User

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Registers a new user by routing to the Authentication Service."""
    auth_service = AuthService(db)
    return auth_service.register_user(data)

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Logs in by validating OAuth2 Form credentials and returns a JWT token."""
    auth_service = AuthService(db)
    return auth_service.login_user(LoginRequest(email=form_data.username, password=form_data.password))

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retrieves standard information of the logged in user based on the JWT token."""
    return current_user
