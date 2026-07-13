from sqlalchemy.orm import Session
from app.models.preprocessing.uploaded_file import UploadedFile

class UploadRepository:
    """Repository for database operations related to UploadedFiles."""
    def __init__(self, db: Session):
        self.db = db

    def create_uploaded_file(self, uploaded_file: UploadedFile) -> UploadedFile:
        self.db.add(uploaded_file)
        self.db.commit()
        self.db.refresh(uploaded_file)
        return uploaded_file

    def get_uploaded_file(self, file_id: int) -> UploadedFile | None:
        return self.db.query(UploadedFile).filter(UploadedFile.file_id == file_id).first()
