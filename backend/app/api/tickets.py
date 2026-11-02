from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.common import Page, PageParams, iso, page_params, paginate
from app.core.errors import AppError, not_found, unprocessable
from app.core.security import require
from app.db.session import get_db
from app.models import Alert, Device, Priority, Ticket, TicketNote, TicketStatus, User
from app.services.audit import audit

router = APIRouter(tags=["Support tickets"])

T = TicketStatus
TRANSITIONS = {T.open: {T.investigating, T.escalated, T.resolved}, T.investigating: {T.escalated, T.resolved},
               T.escalated: {T.investigating, T.resolved}, T.resolved: {T.investigating}}


def ticket_out(t: Ticket, detail: bool = False) -> dict:
    out = {"id": t.id, "code": t.code, "subject": t.subject, "priority": t.priority.value, "status": t.status.value,
           "reporter": t.reporter, "device_serial": t.device.serial if t.device else None, "alert_id": t.alert_id,
           "created_at": iso(t.created_at), "updated_at": iso(t.updated_at)}
    if detail:
        out.update(description=t.description, resolution=t.resolution, notes=[
            {"id": n.id, "body": n.body, "author": n.author.full_name, "created_at": iso(n.created_at)} for n in t.notes])
    return out


@router.get("/tickets", response_model=Page[dict])
def list_tickets(q: str | None = Query(None, max_length=60), status: list[TicketStatus] | None = Query(None),
                 p: PageParams = Depends(page_params), _: User = Depends(require("tickets:read")), db: Session = Depends(get_db)):
    stmt = select(Ticket).outerjoin(Device).options(joinedload(Ticket.device)).order_by(Ticket.created_at.desc())
    if q and q.strip():
        t = f"%{q.strip()}%"
        stmt = stmt.where(or_(Ticket.code.ilike(t), Ticket.subject.ilike(t), Device.serial.ilike(t), Ticket.reporter.ilike(t)))
    if status:
        stmt = stmt.where(Ticket.status.in_(status))
    items, total = paginate(db, stmt, p)
    return Page(items=[ticket_out(t) for t in items], total=total, page=p.page, page_size=p.page_size)


class TicketIn(BaseModel):
    subject: str = Field(min_length=5, max_length=160)
    description: str = Field(min_length=10, max_length=5000)
    reporter: str = Field(min_length=2, max_length=120)
    priority: Priority = Priority.medium
    device_serial: str | None = Field(default=None, max_length=20)
    alert_id: int | None = None


def _load(db: Session, ticket_id: int) -> Ticket:
    t = db.scalars(select(Ticket).where(Ticket.id == ticket_id)
                   .options(joinedload(Ticket.device), selectinload(Ticket.notes).joinedload(TicketNote.author))).first()
    if t is None:
        raise not_found("Ticket")
    return t


@router.post("/tickets", status_code=201)
def create_ticket(body: TicketIn, user: User = Depends(require("tickets:create")), db: Session = Depends(get_db)):
    device_id = None
    if body.alert_id is not None:
        alert = db.get(Alert, body.alert_id)
        if alert is None:
            raise unprocessable("Alert does not exist.", "alert_id", "INVALID_REFERENCE")
        device_id = alert.device_id
    if body.device_serial:
        d = db.scalar(select(Device).where(Device.serial == body.device_serial.strip()))
        if d is None:
            raise unprocessable("Unknown device serial.", "device_serial", "INVALID_REFERENCE")
        if device_id and device_id != d.id:
            raise unprocessable("The alert belongs to a different device.", "device_serial")
        device_id = d.id
    t = Ticket(subject=body.subject.strip(), description=body.description.strip(), reporter=body.reporter.strip(),
               priority=body.priority, device_id=device_id, alert_id=body.alert_id, created_by=user.id)
    db.add(t)
    db.flush()
    audit(db, user, "create", "ticket", t.code)
    db.commit()
    return ticket_out(_load(db, t.id), detail=True)


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, _: User = Depends(require("tickets:read")), db: Session = Depends(get_db)):
    return ticket_out(_load(db, ticket_id), detail=True)


class StatusIn(BaseModel):
    status: TicketStatus
    resolution: str | None = Field(default=None, max_length=5000)


@router.post("/tickets/{ticket_id}/status")
def change_status(ticket_id: int, body: StatusIn, user: User = Depends(require("tickets:manage")), db: Session = Depends(get_db)):
    t = _load(db, ticket_id)
    if body.status not in TRANSITIONS[t.status]:
        raise AppError(409, "INVALID_TRANSITION", f"Cannot move a ticket from {t.status.value} to {body.status.value}.")
    if body.status == T.resolved:
        if not (body.resolution and body.resolution.strip()):
            raise unprocessable("A resolution is required.", "resolution")
        t.resolution = body.resolution.strip()
    audit(db, user, "status_change", "ticket", t.code, {"status": {"from": t.status.value, "to": body.status.value}})
    t.status = body.status
    db.commit()
    return ticket_out(_load(db, ticket_id), detail=True)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.post("/tickets/{ticket_id}/notes", status_code=201)
def add_note(ticket_id: int, body: NoteIn, user: User = Depends(require("tickets:manage")), db: Session = Depends(get_db)):
    t = _load(db, ticket_id)
    db.add(TicketNote(ticket_id=t.id, author_id=user.id, body=body.body.strip()))
    db.commit()
    db.expire_all()
    return ticket_out(_load(db, ticket_id), detail=True)
