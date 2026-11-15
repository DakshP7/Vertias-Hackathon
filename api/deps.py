from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditLog, Patient, User
from .security import read_token

bearer = HTTPBearer(auto_error=False)

RADIOLOGIST, DOCTOR, ADMIN = "radiologist", "doctor", "admin"


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise HTTPException(401, "Not authenticated")
    payload = read_token(cred.credentials)
    if not payload:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or disabled")
    return user


def require_roles(*roles: str):
    """Role checks are enforced on the server, never only hidden in the UI."""
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"This action needs one of these roles: {', '.join(roles)}")
        return user
    return checker


def get_patient_or_404(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "Patient not found")
    return patient


def audit(db: Session, user: User | None, action: str, patient_id: int | None = None, detail: str = "") -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, patient_id=patient_id, detail=detail[:300]))
    db.commit()
