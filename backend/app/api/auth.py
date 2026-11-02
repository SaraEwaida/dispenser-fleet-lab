from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.permissions import permissions_for
from app.core.security import create_access_token, get_current_user, login_limiter, verify_password
from app.db.session import get_db
from app.models import User
from app.services.audit import audit
from app.services.runtime import runtime

router = APIRouter(tags=["Auth & system"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role.value}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    key = f"{request.client.host if request.client else '-'}:{email}"
    login_limiter.check(key)
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        login_limiter.record_failure(key)
        audit(db, user, "login_failed", "user", user.id if user else None)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    login_limiter.reset(key)
    audit(db, user, "login", "user", user.id)
    db.commit()
    token, expires = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires, "user": user_out(user)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return {**user_out(user), "permissions": permissions_for(user.role)}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    s = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unreachable",
            "version": s.app_version, "simulator": s.simulator_enabled, "mqtt_messages_received": runtime.stats["received"]}


@router.get("/sim")
def sim_status(_: User = Depends(get_current_user)):
    s = get_settings()
    clock = get_clock()
    return {"now": clock.now().isoformat(), "speed": clock.speed, "simulator_enabled": s.simulator_enabled,
            "grace_minutes": s.dose_grace_minutes, "offline_after_minutes": s.offline_after_minutes,
            "heartbeat_minutes": s.heartbeat_interval_minutes, "runtime": runtime.stats}
