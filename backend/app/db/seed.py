"""Synthetic seed data: demo users, 24 fictional clients and their dispensers. Run: python -m app.db.seed [--reset]

Idempotent: only seeds when there are no users. Clients have fictional initials-only names.
"""

import argparse
import random

from sqlalchemy import func, select, text

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Client, Device, DoseSchedule, User

DEMO_PASSWORD = "Demo@2026!"
USERS = [
    ("coordinator@fleet.example.com", "Carla Coordinator", "care_coordinator"),
    ("support@fleet.example.com", "Sam Support", "support_engineer"),
    ("qa@fleet.example.com", "Quinn QA", "qa_engineer"),
]
TEAMS = ["Team North", "Team South", "Team Centre", "Night team"]
INITIALS = ["A.", "B.", "D.", "E.", "F.", "H.", "J.", "K.", "L.", "M.", "N.", "R.", "S.", "T.", "W.", "Y."]
SURNAMES = ["de Vries", "Jansen", "Haddad", "Bakker", "Visser", "Smit", "Mulder", "Khalil", "Meijer", "Nasser",
            "de Boer", "Saleh", "Bos", "Peters", "Hendriks", "Odeh", "van Dijk", "Dekker", "Brouwer", "Awad"]
SCHEDULES = [["08:00", "12:30", "18:00", "22:00"], ["08:30", "20:30"], ["07:30", "13:00", "19:00"],
             ["09:00", "21:00"], ["08:00", "14:00", "20:00"]]
FIRMWARE = ["2.4.1", "2.4.1", "2.4.1", "2.3.7"]


def reset_all(db) -> None:
    db.execute(text("TRUNCATE audit_logs, ticket_notes, tickets, faults, commands, alerts, telemetry, doses, "
                    "dose_schedules, devices, clients, users RESTART IDENTITY CASCADE"))
    for seq in ("client_code_seq", "alert_code_seq", "ticket_code_seq"):
        db.execute(text(f"ALTER SEQUENCE {seq} RESTART WITH 1001"))


def run(reset: bool = False) -> dict:
    s = get_settings()
    rng = random.Random(s.sim_seed)
    now = get_clock().now()
    with SessionLocal() as db:
        if reset:
            reset_all(db)
            db.commit()
        if db.scalar(select(func.count()).select_from(User)):
            return {"seeded": False}
        pw = hash_password(DEMO_PASSWORD)
        db.add_all(User(email=e, full_name=n, role=r, password_hash=pw) for e, n, r in USERS)
        for i in range(s.fleet_size):
            c = Client(display_name=f"{rng.choice(['Mrs.', 'Mr.'])} {rng.choice(INITIALS)} {rng.choice(SURNAMES)}",
                       care_team=TEAMS[i % len(TEAMS)])
            db.add(c)
            db.flush()
            capacity = 28
            d = Device(serial=f"MD-{24001 + i}", client_id=c.id, firmware=rng.choice(FIRMWARE), roll_capacity=capacity,
                       roll_remaining=rng.choice([3, 5, 8, 12, 16, 20, 24, 28]), commissioned_at=now)
            d.schedule = [DoseSchedule(time_of_day=t) for t in SCHEDULES[i % len(SCHEDULES)]]
            db.add(d)
        db.commit()
        return {"seeded": True, "devices": s.fleet_size}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    print(run(ap.parse_args().reset))
