import io
import json
import shutil
import tempfile
import uuid
import warnings
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DISCLAIMER, settings
from ..database import get_db
from ..deps import DOCTOR, RADIOLOGIST, audit, current_user, get_patient_or_404, require_roles
from ..models import AIResult, Scan, ScanReview, User
from ..schemas import AIResultOut, ReviewIn, ReviewOut, ScanOut
from ..services import ct_service, ml_service

Image.MAX_IMAGE_PIXELS = 40_000_000

router = APIRouter(tags=["scans"])


def _normalise(data: bytes) -> bytes:
    """Accept PNG/JPEG only; re-encode to a clean PNG (this also strips EXIF metadata)."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # turn decompression-bomb warnings into errors
            img = Image.open(io.BytesIO(data))
            if img.format not in ("PNG", "JPEG"):
                raise HTTPException(400, "Only PNG or JPEG images are accepted (DICOM support comes later).")
            img.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning, ValueError):
        raise HTTPException(400, "File is not a valid, reasonably sized PNG/JPEG image.")
    img = img.convert("L") if img.mode in ("L", "LA", "1") else img.convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _scan_out(scan: Scan, res: AIResult | None) -> ScanOut:
    result = None
    if res:
        result = AIResultOut.model_validate(res)
        result.has_heatmap = bool(res.heatmap_name)
    return ScanOut(id=scan.id, patient_id=scan.patient_id, scan_type=scan.scan_type, uploaded_by=scan.uploaded_by,
                   uploaded_at=scan.uploaded_at, result=result, disclaimer=DISCLAIMER)


def _get_scan(db: Session, scan_id: int) -> tuple[Scan, AIResult | None]:
    scan = db.get(Scan, scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found")
    res = db.scalar(select(AIResult).where(AIResult.scan_id == scan.id))
    return scan, res


@router.post("/patients/{patient_id}/scans", response_model=ScanOut, status_code=201)
def upload_scan(
    patient_id: int,
    scan_type: Literal["ct", "tissue"] = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(RADIOLOGIST)),
    db: Session = Depends(get_db),
):
    get_patient_or_404(db, patient_id)
    if scan_type == "ct" and ct_service.is_volume_name(file.filename or ""):
        return _upload_ct_volume(patient_id, file, user, db)
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB")
    if not data:
        raise HTTPException(400, "Empty file")

    png = _normalise(data)
    analysis = ml_service.analyze(png, scan_type)

    file_name = f"{uuid.uuid4().hex}.png"
    (settings.upload_dir / file_name).write_bytes(png)
    heatmap_name = None
    if analysis.heatmap_png:
        heatmap_name = f"{uuid.uuid4().hex}_heat.png"
        (settings.upload_dir / heatmap_name).write_bytes(analysis.heatmap_png)

    scan = Scan(patient_id=patient_id, scan_type=scan_type, file_name=file_name, uploaded_by=user.id)
    db.add(scan)
    db.flush()
    res = AIResult(
        scan_id=scan.id, status=analysis.status, risk_score=analysis.risk_score, priority=analysis.priority,
        uncertainty=analysis.uncertainty, message=analysis.message, heatmap_name=heatmap_name,
        model_version=analysis.model_version, is_placeholder=analysis.is_placeholder,
        threshold_high=analysis.threshold_high, threshold_review=analysis.threshold_review,
    )
    db.add(res)
    db.commit()
    audit(db, user, "upload_scan", patient_id, f"scan={scan.id} type={scan_type} status={analysis.status}")
    return _scan_out(scan, res)


def _upload_ct_volume(patient_id: int, file: UploadFile, user: User, db: Session) -> ScanOut:
    """A whole CT volume: validate it, save a preview slice, then run the nodule detector in the background."""
    ok, why = ct_service.available()
    if not ok:
        raise HTTPException(503, why)
    limit = settings.ct_max_upload_mb * 1024 * 1024
    name = (file.filename or "").lower()
    suffix = next((s for s in (*ct_service.VOLUME_SUFFIXES, ".zip") if name.endswith(s)), ".bin")
    with tempfile.TemporaryDirectory() as tmp:
        path = f"{tmp}/upload{suffix}"
        size = 0
        with open(path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"File is larger than {settings.ct_max_upload_mb} MB")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "Empty file")
        try:
            img = ct_service.read_volume(__import__("pathlib").Path(path), name)
        except ct_service.CTError as exc:
            raise HTTPException(400, str(exc))
    file_name = f"{uuid.uuid4().hex}.png"
    (settings.upload_dir / file_name).write_bytes(ct_service.preview_png(img))
    scan = Scan(patient_id=patient_id, scan_type="ct", file_name=file_name, uploaded_by=user.id)
    db.add(scan)
    db.flush()
    res = AIResult(scan_id=scan.id, status="processing", risk_score=None, priority=None, uncertainty=None,
                   message="Running the nodule detector on the whole CT volume. This can take several minutes; the page updates when it is done.",
                   heatmap_name=None, model_version=ct_service.CT_VERSION[:60], is_placeholder=False,
                   threshold_high=1.0, threshold_review=ct_service.SCORE_SHOWN)
    db.add(res)
    db.commit()
    audit(db, user, "upload_scan", patient_id, f"scan={scan.id} type=ct volume")
    ct_service.submit(scan.id, img)
    return _scan_out(scan, res)


@router.get("/patients/{patient_id}/scans", response_model=list[ScanOut])
def list_scans(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    rows = db.execute(
        select(Scan, AIResult).join(AIResult, AIResult.scan_id == Scan.id, isouter=True)
        .where(Scan.patient_id == patient_id).order_by(Scan.uploaded_at.desc())
    ).all()
    return [_scan_out(s, r) for s, r in rows]


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(scan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    scan, res = _get_scan(db, scan_id)
    audit(db, user, "view_scan", scan.patient_id, f"scan={scan.id}")
    return _scan_out(scan, res)


def _image_response(name: str) -> FileResponse:
    path = settings.upload_dir / name
    if not path.is_file():
        raise HTTPException(404, "Image file missing")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/scans/{scan_id}/image")
def scan_image(scan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    scan, _ = _get_scan(db, scan_id)
    return _image_response(scan.file_name)


@router.get("/scans/{scan_id}/heatmap")
def scan_heatmap(scan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _, res = _get_scan(db, scan_id)
    if not res or not res.heatmap_name:
        raise HTTPException(404, "No heatmap for this scan")
    return _image_response(res.heatmap_name)


def _review_out(rv: ScanReview, doctor: User) -> ReviewOut:
    return ReviewOut(id=rv.id, scan_id=rv.scan_id, doctor_id=doctor.id, doctor_name=doctor.full_name,
                     verdict=rv.verdict, note=rv.note, created_at=rv.created_at)


@router.get("/scans/{scan_id}/reviews", response_model=list[ReviewOut])
def list_reviews(scan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _get_scan(db, scan_id)
    rows = db.execute(select(ScanReview, User).join(User, User.id == ScanReview.doctor_id)
                      .where(ScanReview.scan_id == scan_id).order_by(ScanReview.created_at)).all()
    return [_review_out(r, u) for r, u in rows]


@router.post("/scans/{scan_id}/reviews", response_model=ReviewOut, status_code=201)
def review_scan(scan_id: int, body: ReviewIn, user: User = Depends(require_roles(DOCTOR)),
                db: Session = Depends(get_db)):
    """A doctor records whether they agree with the AI result. One verdict per doctor per scan (updating replaces it)."""
    scan, res = _get_scan(db, scan_id)
    rv = db.scalar(select(ScanReview).where(ScanReview.scan_id == scan_id, ScanReview.doctor_id == user.id))
    if rv:
        rv.verdict, rv.note = body.verdict, body.note
    else:
        rv = ScanReview(scan_id=scan_id, doctor_id=user.id, verdict=body.verdict, note=body.note)
        db.add(rv)
    db.commit()
    audit(db, user, "review_scan", scan.patient_id, f"scan={scan_id} verdict={body.verdict}")
    return _review_out(rv, user)


@router.get("/scans/{scan_id}/ct")
def scan_ct(scan_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Detector results for an uploaded CT volume (same shape as one case of the CT demo)."""
    scan, res = _get_scan(db, scan_id)
    f = ct_service.ct_dir(scan.id) / "meta.json"
    if scan.scan_type != "ct" or not f.is_file():
        raise HTTPException(404, "No CT detector results for this scan")
    meta = json.loads(f.read_text(encoding="utf-8"))
    meta["case"] = f"scan_{scan.id}"
    return meta


@router.get("/scans/{scan_id}/ct/slice/{index}")
def scan_ct_slice(scan_id: int, index: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    scan, _ = _get_scan(db, scan_id)
    f = ct_service.ct_dir(scan.id) / f"{index:03d}.jpg"
    if scan.scan_type != "ct" or index < 0 or index > 2000 or not f.is_file():
        raise HTTPException(404, "No such slice")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})
