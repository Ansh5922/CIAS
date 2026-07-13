from fastapi import APIRouter, Depends, UploadFile, File, Form, status
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import require_admin
from app.models.auth.user import User
from app.services.storage.file_storage_service import FileStorageService
from app.schemas.upload.upload import UploadResponse

router = APIRouter()

@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def upload_file(
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Upload a new file securely directly bypassing the route.
    
    - **Authorization**: Extracted automatically checking for 'Administration' role.
    - **Constraints**: PDF, JPG, JPEG, PNG, CSV, XLSX only. 50 MB limits.
    - **Outcome**: Resolves MIME dynamically, dumps in safe UUID chunk, maps to postgres uploaded_files.
    """
    storage_service = FileStorageService(db)
    result = storage_service.save_file(file=file, uploader_id=current_user.user_id, description=description)
    return result
