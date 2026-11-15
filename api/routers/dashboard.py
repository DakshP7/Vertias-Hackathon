from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import ADMIN, DOCTOR, current_user
from ..models import AIResult, AuditLog, Patient, Report, Scan, ScanReview, User
from ..schemas import DashboardOut
from .patients import list_items

router = APIRouter(tags=["dashboard"])


def _scan_status(prio: str | None, res_status: str | None, reviewed: bool, completed: bool) -> str:
    if completed:
        return "Completed"
    if res_status == "processing":
        return "Processing"
    if res_status == "cannot_assess":
        return "Cannot assess"
    if reviewed:
        return "In review"
    if prio == "HIGH PRIORITY":
        return "Urgent"
    return "AI analysed"


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = list_items(db, list(db.scalars(select(Patient))))
    now = datetime.now(timezone.utc)
    week, prev = now - timedelta(days=7), now - timedelta(days=14)
    counts = {
        "patients": len(items),
        "scans": db.scalar(select(func.count()).select_from(Scan)) or 0,
        "scans_7d": db.scalar(select(func.count()).select_from(Scan).where(Scan.uploaded_at >= week)) or 0,
        "scans_prev_7d": db.scalar(select(func.count()).select_from(Scan)
                                   .where(Scan.uploaded_at >= prev, Scan.uploaded_at < week)) or 0,
        "high_priority_patients": sum(1 for i in items if i.highest_priority == "HIGH PRIORITY"),
        "awaiting_review": sum(1 for i in items if i.status == "AI analysed"),
        "reports_ready": sum(1 for i in items if i.status == "Report ready"),
    }
    # Extra counts for the dashboard tiles and the scan-distribution donut (all measured from the database).
    reviewed_n = db.scalar(select(func.count(func.distinct(ScanReview.scan_id)))) or 0
    counts["scans_reviewed"] = reviewed_n
    counts["scans_pending"] = max(counts["scans"] - reviewed_n, 0)
    counts["reports_approved"] = db.scalar(select(func.count()).select_from(Report).where(Report.status == "approved")) or 0
    prios = list(db.scalars(select(AIResult.priority).where(AIResult.priority.is_not(None))))
    counts["risk_high"] = sum(1 for p in prios if p == "HIGH PRIORITY")
    counts["risk_medium"] = sum(1 for p in prios if p == "PRIORITY REVIEW")
    counts["risk_low"] = sum(1 for p in prios if p == "ROUTINE REVIEW")
    open_cases = [i for i in items if i.highest_risk is not None and i.status != "Report ready"]
    open_cases.sort(key=lambda i: -(i.highest_risk or 0))

    completed_patients = set(db.scalars(select(Report.patient_id).where(Report.status == "approved")).all())
    reviewed_scans = set(db.scalars(select(ScanReview.scan_id)).all())
    rows = db.execute(
        select(Scan, AIResult, Patient)
        .join(AIResult, AIResult.scan_id == Scan.id, isouter=True)
        .join(Patient, Patient.id == Scan.patient_id)
        .order_by(Scan.uploaded_at.desc(), Scan.id.desc()).limit(6)
    ).all()
    recent = []
    for s, r, p in rows:
        recent.append({
            "scan_id": s.id, "patient_id": p.id, "display_id": p.display_id, "name": p.name, "age": p.age,
            "sex": p.sex, "smoking_status": p.smoking_status, "scan_type": s.scan_type,
            "uploaded_at": s.uploaded_at.isoformat(),
            "risk_score": r.risk_score if r else None, "priority": r.priority if r else None,
            "uncertainty": r.uncertainty if r else None, "has_heatmap": bool(r and r.heatmap_name),
            "is_placeholder": r.is_placeholder if r else True,
            "threshold_review": r.threshold_review if r else settings.threshold_review,
            "threshold_high": r.threshold_high if r else settings.threshold_high,
            "status": _scan_status(r.priority if r else None, r.status if r else None,
                                   s.id in reviewed_scans, p.id in completed_patients),
        })

    activity: list[dict] = []
    if user.role in (DOCTOR, ADMIN):  # same visibility rule as the audit log
        arows = db.execute(
            select(AuditLog, User.full_name).join(User, User.id == AuditLog.user_id, isouter=True)
            .where(AuditLog.action.notin_(["login", "login_failed", "view_patient", "view_scan"]))
            .order_by(AuditLog.id.desc()).limit(8)
        ).all()
        activity = [{"time": a.timestamp.isoformat(), "user": name or "system", "action": a.action,
                     "patient": f"CIQ-{a.patient_id:04d}" if a.patient_id else ""} for a, name in arows]
    return DashboardOut(user_name=user.full_name, user_role=user.role, counts=counts, urgent=open_cases[:5],
                        recent_scans=recent, recent_activity=activity, email_mode=settings.email_mode)
