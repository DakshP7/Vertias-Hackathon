import re
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import DOCTOR, RADIOLOGIST, audit, current_user, get_patient_or_404, require_roles
from ..models import AIResult, Note, Patient, Report, Scan, ScanReview, User, Visit
from ..schemas import PatientIn, PatientListItem, PatientOut, VisitIn, VisitOut

router = APIRouter(prefix="/patients", tags=["patients"])

STATUSES = ["New", "AI analysed", "Under review", "Report ready"]


def list_items(db: Session, patients: list[Patient]) -> list[PatientListItem]:
    if not patients:
        return []
    ids = [p.id for p in patients]

    best: dict[int, tuple[float, str]] = {}
    scan_count: dict[int, int] = {}
    rows = db.execute(
        select(Scan.patient_id, AIResult.risk_score, AIResult.priority)
        .join(AIResult, AIResult.scan_id == Scan.id, isouter=True)
        .where(Scan.patient_id.in_(ids))
    ).all()
    for pid, score, prio in rows:
        scan_count[pid] = scan_count.get(pid, 0) + 1
        if score is not None and (pid not in best or score > best[pid][0]):
            best[pid] = (score, prio)

    note_counts = dict(db.execute(
        select(Note.patient_id, func.count()).where(Note.patient_id.in_(ids)).group_by(Note.patient_id)).all())
    for pid, n in db.execute(
        select(Scan.patient_id, func.count(ScanReview.id)).join(ScanReview, ScanReview.scan_id == Scan.id)
        .where(Scan.patient_id.in_(ids)).group_by(Scan.patient_id)).all():
        note_counts[pid] = note_counts.get(pid, 0) + n
    approved = set(db.scalars(
        select(Report.patient_id).where(Report.patient_id.in_(ids), Report.status == "approved")).all())

    items = []
    for p in patients:
        if p.id in approved:
            status = "Report ready"
        elif note_counts.get(p.id):
            status = "Under review"
        elif scan_count.get(p.id):
            status = "AI analysed"
        else:
            status = "New"
        score, prio = best.get(p.id, (None, None))
        item = PatientListItem.model_validate(p)
        item.status, item.highest_risk, item.highest_priority = status, score, prio
        item.scan_count = scan_count.get(p.id, 0)
        items.append(item)
    return items


@router.get("", response_model=list[PatientListItem])
def list_patients(
    q: str | None = Query(None, max_length=100, description="Search by name or ID (e.g. CIQ-0003)"),
    status: str | None = Query(None, description="New | AI analysed | Under review | Report ready"),
    sort: Literal["risk", "recent", "name"] = "recent",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Patient)
    if q:
        conds = [Patient.name.ilike(f"%{q.strip()}%")]
        m = re.fullmatch(r"(?i)(?:ciq-?)?0*(\d+)", q.strip())
        if m:
            conds.append(Patient.id == int(m.group(1)))
        stmt = stmt.where(or_(*conds))
    items = list_items(db, list(db.scalars(stmt)))
    if status:
        items = [i for i in items if i.status == status]
    if sort == "risk":
        items.sort(key=lambda i: (i.highest_risk is None, -(i.highest_risk or 0)))
    elif sort == "name":
        items.sort(key=lambda i: i.name.lower())
    else:
        items.sort(key=lambda i: i.created_at, reverse=True)
    return items


@router.post("", response_model=PatientOut, status_code=201)
def create_patient(body: PatientIn, user: User = Depends(require_roles(RADIOLOGIST, DOCTOR)),
                   db: Session = Depends(get_db)):
    patient = Patient(**body.model_dump(), created_by=user.id, is_demo=True)
    db.add(patient)
    db.commit()
    audit(db, user, "create_patient", patient.id)
    return patient


@router.get("/{patient_id}", response_model=PatientListItem)
def get_patient(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient = get_patient_or_404(db, patient_id)
    audit(db, user, "view_patient", patient.id)
    return list_items(db, [patient])[0]


@router.put("/{patient_id}", response_model=PatientOut)
def update_patient(patient_id: int, body: PatientIn, user: User = Depends(require_roles(RADIOLOGIST, DOCTOR)),
                   db: Session = Depends(get_db)):
    patient = get_patient_or_404(db, patient_id)
    for k, v in body.model_dump().items():
        setattr(patient, k, v)
    db.commit()
    audit(db, user, "update_patient", patient.id)
    return patient


@router.get("/{patient_id}/visits", response_model=list[VisitOut])
def list_visits(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    return list(db.scalars(select(Visit).where(Visit.patient_id == patient_id).order_by(Visit.visit_date.desc())))


@router.post("/{patient_id}/visits", response_model=VisitOut, status_code=201)
def add_visit(patient_id: int, body: VisitIn, user: User = Depends(require_roles(RADIOLOGIST, DOCTOR)),
              db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    visit = Visit(patient_id=patient_id, created_by=user.id, **body.model_dump())
    db.add(visit)
    db.commit()
    audit(db, user, "add_visit", patient_id)
    return visit
