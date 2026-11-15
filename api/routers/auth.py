from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import audit, current_user
from ..models import User
from ..schemas import LoginIn, TokenOut, UserOut
from ..security import hash_password, make_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Used so a login for an unknown username takes about as long as a real one.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        audit(db, None, "login_failed", detail=f"username={body.username[:40]}")
        raise HTTPException(401, "Incorrect username or password")
    audit(db, user, "login")
    return TokenOut(access_token=make_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
