from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import DISCLAIMER, settings
from ..database import get_db
from ..deps import DOCTOR, audit, current_user, get_patient_or_404, require_roles
from ..models import AIResult, EmailLog, Note, Patient, Report, Scan, ScanReview, User, now
from ..schemas import EmailIn, EmailLogOut, ReportEdit, ReportOut
from ..services import email_service, pdf_service, report_service

router = APIRouter(tags=["reports"])


def _out(r: Report) -> ReportOut:
    out = ReportOut.model_validate(r)
    out.disclaimer = DISCLAIMER
    return out


def _get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    return report


def _build_pdf(db: Session, report: Report) -> tuple[Patient, bytes]:
    patient: Patient = db.get(Patient, report.patient_id)
    approver = db.get(User, report.approved_by)
    when = report.approved_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    pdf = pdf_service.report_pdf(patient.display_id, patient.name, report.final_text or "",
                                 approver.full_name if approver else "a doctor", when)
    return patient, pdf


@router.post("/patients/{patient_id}/report", response_model=ReportOut, status_code=201)
def generate_report(patient_id: int, user: User = Depends(require_roles(DOCTOR)), db: Session = Depends(get_db)):
    """Draft a plain-language patient report (Gemini if configured, else a template)."""
    patient = get_patient_or_404(db, patient_id)
    scans = db.execute(
        select(Scan, AIResult).join(AIResult, AIResult.scan_id == Scan.id, isouter=True)
        .where(Scan.patient_id == patient_id).order_by(Scan.uploaded_at)
    ).all()
    if not scans:
        raise HTTPException(400, "This patient has no scans yet, so there is nothing to report on.")
    notes = list(db.scalars(select(Note).where(Note.patient_id == patient_id).order_by(Note.created_at)))
    reviews = list(db.scalars(select(ScanReview).join(Scan, Scan.id == ScanReview.scan_id)
                              .where(Scan.patient_id == patient_id).order_by(ScanReview.created_at)))
    text, source = report_service.generate(patient, [(s, r) for s, r in scans], notes, reviews)
    report = Report(patient_id=patient_id, draft_text=text, source=source, created_by=user.id)
    db.add(report)
    db.commit()
    audit(db, user, "generate_report", patient_id, f"report={report.id} source={source}")
    return _out(report)


@router.get("/patients/{patient_id}/reports", response_model=list[ReportOut])
def list_reports(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    return [_out(r) for r in db.scalars(
        select(Report).where(Report.patient_id == patient_id).order_by(Report.created_at.desc()))]


@router.put("/reports/{report_id}", response_model=ReportOut)
def edit_report(report_id: int, body: ReportEdit, user: User = Depends(require_roles(DOCTOR)),
                db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    if report.status != "draft":
        raise HTTPException(409, "Approved reports cannot be edited. Generate a new draft instead.")
    report.draft_text = body.draft_text
    db.commit()
    audit(db, user, "edit_report", report.patient_id, f"report={report.id}")
    return _out(report)


@router.put("/reports/{report_id}/approve", response_model=ReportOut)
def approve_report(report_id: int, user: User = Depends(require_roles(DOCTOR)), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    if report.status == "approved":
        raise HTTPException(409, "Report is already approved")
    report.final_text = report_service.with_disclaimer(report.draft_text)
    report.status = "approved"
    report.approved_by = user.id
    report.approved_at = now()
    db.commit()
    audit(db, user, "approve_report", report.patient_id, f"report={report.id}")
    return _out(report)


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    if report.status != "approved":
        raise HTTPException(409, "Only approved reports can be downloaded as PDF")
    patient, pdf = _build_pdf(db, report)
    audit(db, user, "download_report", patient.id, f"report={report.id}")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{patient.display_id}-report.pdf"'})


@router.post("/reports/{report_id}/send", response_model=EmailLogOut, status_code=201)
def send_report(report_id: int, body: EmailIn, user: User = Depends(require_roles(DOCTOR)),
                db: Session = Depends(get_db)):
    """Email an APPROVED report (PDF attached). In 'outbox' mode nothing leaves this computer."""
    report = _get_report(db, report_id)
    if report.status != "approved":
        raise HTTPException(409, "Only approved reports can be emailed")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.scalar(select(func.count()).select_from(EmailLog)
                       .where(EmailLog.sent_by == user.id, EmailLog.created_at >= since)) or 0
    if recent >= settings.max_emails_per_hour:
        raise HTTPException(429, "Email limit reached for this hour. Try again later.")
    patient, pdf = _build_pdf(db, report)
    msg = email_service.build_message(body.recipient, patient.display_id, user.full_name, pdf,
                                      f"{patient.display_id}-report.pdf")
    try:
        mode = email_service.deliver(msg)
    except RuntimeError as exc:
        audit(db, user, "email_failed", patient.id, f"report={report.id}")
        raise HTTPException(502, str(exc))
    entry = EmailLog(report_id=report.id, sent_by=user.id, recipient=body.recipient, mode=mode)
    db.add(entry)
    db.commit()
    audit(db, user, "email_report", patient.id, f"report={report.id} to={body.recipient} mode={mode}")
    return entry


@router.get("/reports/{report_id}/emails", response_model=list[EmailLogOut])
def report_emails(report_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _get_report(db, report_id)
    return list(db.scalars(select(EmailLog).where(EmailLog.report_id == report_id).order_by(EmailLog.created_at.desc())))
