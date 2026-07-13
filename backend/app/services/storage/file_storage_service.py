import os
import uuid
import shutil
import logging
from typing import Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.upload_repository import UploadRepository
from app.models.preprocessing.uploaded_file import UploadedFile

# Configure Logger
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class FileStorageService:
    ALLOWED_MIME_TYPES = {
        "application/pdf": "pdf",
        "image/jpeg": "images",
        "image/jpg": "images",
        "image/png": "images",
        "text/csv": "csv",
        "application/csv": "csv",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel"
    }

    ALLOWED_EXTENSIONS = {
        ".pdf": "pdf",
        ".jpg": "images",
        ".jpeg": "images",
        ".png": "images",
        ".csv": "csv",
        ".xlsx": "excel"
    }

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    def __init__(self, db: Session):
        self.db = db
        self.repository = UploadRepository(db)
        self.base_dir = settings.UPLOAD_DIR

    def validate_file(self, file: UploadFile) -> str:
        """Validates file constraints: empty, size, mime, extension."""
        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded")
        
        # Extension validation
        _, ext = os.path.splitext(file.filename)
        ext = ext.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Unsupported file extension: {ext}")
            
        # MIME validation
        if file.content_type not in self.ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=f"Unsupported media type: {file.content_type}")
            
        return ext

    def generate_unique_filename(self, original_filename: str, ext: str) -> str:
        """Generates a UUID tied strictly to the valid extension."""
        unique_id = str(uuid.uuid4())
        return f"{unique_id}{ext}"

    def determine_storage_directory(self, ext: str) -> str:
        """Returns the specific categorical subdirectory."""
        sub_dir = self.ALLOWED_EXTENSIONS.get(ext, "temp")
        dir_path = os.path.join(self.base_dir, sub_dir)
        os.makedirs(dir_path, exist_ok=True) # Failsafe although app startup checks it
        return dir_path, sub_dir

    def save_file(self, file: UploadFile, uploader_id: int, description: Optional[str] = None) -> UploadedFile:
        """Executes full save routine and persists metadata into Repository."""
        logger.info(f"User {uploader_id} attempting to upload file '{file.filename}'")

        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)
        
        # Size limit check
        if file_size > self.MAX_FILE_SIZE:
             logger.warning(f"File upload failed. User: {uploader_id}, Error: Exceeded size limit ({file_size} bytes)")
             raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large. Maximum size is 50MB")
        
        if file_size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

        ext = self.validate_file(file)
        stored_filename = self.generate_unique_filename(file.filename, ext)
        dir_path, sub_dir = self.determine_storage_directory(ext)
        full_path = os.path.join(dir_path, stored_filename)

        try:
            # Save file synchronously in efficient chunks
            with open(full_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            logger.info(f"File '{file.filename}' successfully saved to {full_path}")
            
            db_file_category_map = {
                "pdf": "PDF",
                "images": "Image",
                "csv": "CSV",
                "excel": "Excel"
            }
            db_file_category = db_file_category_map.get(sub_dir, "Other")

            # Map object for DB injection
            uploaded_file = UploadedFile(
                uploaded_by=uploader_id,
                original_file_name=file.filename,
                stored_file_name=stored_filename,
                file_type=db_file_category,
                mime_type=file.content_type,
                file_size=file_size,
                storage_provider="local",
                file_path=full_path,
                upload_status="Uploaded"
            )

            result = self.repository.create_uploaded_file(uploaded_file)
            logger.info(f"Upload stored in DB successfully as file_id: {result.file_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed handling upload '{file.filename}'. Reason: {str(e)}")
            if os.path.exists(full_path):
                os.remove(full_path) # Cleanup artifact
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save the file locally. Error: {str(e)}")
