from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UploadResponse(BaseModel):
    file_id: int
    original_file_name: str
    stored_file_name: str
    upload_status: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


class FileMetadata(BaseModel):
    original_file_name: str
    stored_file_name: str
    file_type: str
    mime_type: str
    file_size: int
    storage_provider: str = "local"
    file_path: str
    upload_status: str = "Uploaded"
