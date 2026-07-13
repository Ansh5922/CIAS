from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordRequestForm

from app.schemas.auth.auth import CitizenRegisterRequest, AdminRegisterRequest, UserResponse, Token, LoginRequest
from app.services.auth.auth_service import AuthService
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.auth.user import User

router = APIRouter()

# ================================
# CITIZEN PORTAL
# ================================
@router.post("/citizen/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_citizen(data: CitizenRegisterRequest, db: Session = Depends(get_db)):
    """Registers a new public citizen."""
    auth_service = AuthService(db)
    return auth_service.register_citizen(data)

@router.post("/citizen/login", response_model=Token)
def login_citizen(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Logs in an existing citizen."""
    auth_service = AuthService(db)
    return auth_service.login_role_specific(
        LoginRequest(email=form_data.username, password=form_data.password), 
        expected_role="Citizen"
    )

# ================================
# ADMIN PORTAL
# ================================
@router.post("/admin/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_admin(data: AdminRegisterRequest, db: Session = Depends(get_db)):
    """Registers a new platform administrator using a secret passcode."""
    auth_service = AuthService(db)
    return auth_service.register_admin(data)

@router.post("/admin/login", response_model=Token)
def login_admin(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Logs in an existing platform administrator."""
    auth_service = AuthService(db)
    return auth_service.login_role_specific(
        LoginRequest(email=form_data.username, password=form_data.password), 
        expected_role="Administration"
    )


# ================================
# UTILITIES
# ================================
@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Retrieves standard information of the logged in user based on the JWT token."""
    return current_user
