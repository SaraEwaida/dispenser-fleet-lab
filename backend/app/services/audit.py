from typing import Any

from sqlalchemy.orm import Session

from app.core.redaction import redact
from app.core.request_context import get_request_id
from app.models import AuditLog, User


def audit(db: Session, actor: User | None, action: str, entity_type: str, entity_id: Any, changes: dict | None = None) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None, request_id=get_request_id(),
                    changes=redact(changes or {})))
