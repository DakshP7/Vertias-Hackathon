"""Create demo accounts and FAKE demo patients. Safe to run more than once.

    python -m api.seed

DEMO ONLY: these passwords are for local testing. Do not reuse them anywhere,
and never deploy publicly with them. Change or replace before any real hosting.
"""
from sqlalchemy import select

from .database import Base, SessionLocal, engine
from .models import Patient, User, Visit
from .security import hash_password

DEMO_USERS = [
    # username, full name, role, password
    ("rad1", "Dr. Asha Rao (Radiologist)", "radiologist", "Radiology#Demo1"),
    ("doc1", "Dr. Vikram Shah", "doctor", "Doctor#Demo1"),
    ("doc2", "Dr. Meera Iyer", "doctor", "Doctor#Demo2"),
    ("admin", "Demo Admin", "admin", "Admin#Demo1"),
]

DEMO_PATIENTS = [
    dict(name="Demo Patient A", age=63, sex="male", contact="demo-a@example.invalid", smoking_status="former",
         pack_years=30, family_history=True, conditions="Hypertension", symptoms="Persistent cough for 6 weeks"),
    dict(name="Demo Patient B", age=47, sex="female", contact="demo-b@example.invalid", smoking_status="never",
         pack_years=0, family_history=False, conditions="", symptoms="None reported"),
    dict(name="Demo Patient C", age=71, sex="male", contact="demo-c@example.invalid", smoking_status="current",
         pack_years=45, family_history=False, conditions="COPD", symptoms="Shortness of breath, weight loss"),
]


def seed() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        for username, full_name, role, pw in DEMO_USERS:
            if not db.scalar(select(User).where(User.username == username)):
                db.add(User(username=username, full_name=full_name, role=role, password_hash=hash_password(pw)))
        db.commit()
        if not db.scalar(select(Patient)):
            creator = db.scalar(select(User).where(User.username == "rad1"))
            for p in DEMO_PATIENTS:
                patient = Patient(**p, created_by=creator.id, is_demo=True)
                db.add(patient)
                db.flush()
                db.add(Visit(patient_id=patient.id, visit_date="2026-11-01", reason="Screening visit",
                             created_by=creator.id))
            db.commit()
    print("Seeded demo users and fake patients. See api/seed.py for the demo logins.")


if __name__ == "__main__":
    seed()
