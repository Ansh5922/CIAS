from sqlalchemy.orm import Session
from app.models.auth.role import Role

class RoleRepository:
    """Repository for database operations related to Role."""
    def __init__(self, db: Session):
        self.db = db

    def get_by_name(self, role_name: str) -> Role | None:
        return self.db.query(Role).filter(Role.role_name == role_name).first()

    def get_by_id(self, role_id: int) -> Role | None:
        return self.db.query(Role).filter(Role.role_id == role_id).first()
