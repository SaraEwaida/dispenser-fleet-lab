import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import has_permission
from app.db.session import get_db
from app.models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user: User) -> tuple[str, int]:
    s = get_settings()
    expires = s.jwt_expires_minutes * 60
    payload = {
        "sub": str(user.id), "role": user.role.value,
        "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(seconds=expires),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), expires


def _unauthorized(message: str = "Authentication required.") -> HTTPException:
    return HTTPException(status_code=401, detail=message, headers={"WWW-Authenticate": "Bearer"})


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise _unauthorized()
    s = get_settings()
    try:
        payload = jwt.decode(creds.credentials, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired. Please sign in again.")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized("Account not available.")
    request.state.user_id = user.id
    request.state.user_role = user.role.value
    return user


def require(permission: str):
    """Dependency factory: `user: User = Depends(require("alerts:handle"))`."""

    def checker(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not has_permission(user.role, permission):
            from app.services.audit import audit  # local import avoids a cycle

            audit(db, user, "permission_denied", "permission", permission,
                  {"method": request.method, "path": request.url.path})
            db.commit()
            raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")
        return user

    return checker


class LoginRateLimiter:
    """In-memory sliding window per (ip, email). Single-instance demo; a shared store would be needed to scale out."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Raise 429 if this key already has too many *failed* attempts in the last minute."""
        limit = get_settings().login_attempts_per_minute
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            retry = int(60 - (now - q[0])) + 1
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again shortly.",
                                headers={"Retry-After": str(retry)})

    def record_failure(self, key: str) -> None:
        self._hits[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


login_limiter = LoginRateLimiter()
