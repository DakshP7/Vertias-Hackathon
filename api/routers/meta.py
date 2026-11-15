import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import DISCLAIMER, settings
from ..database import get_db
from ..deps import ADMIN, DOCTOR, current_user, require_roles
from ..models import AuditLog, User
from ..services import ml_service
from ..services.ml_service import MODEL_VERSION, MODELS_DIR, TISSUE_HIGH, TISSUE_REVIEW, TISSUE_VERSION

router = APIRouter(tags=["meta"])


def _tissue_metrics() -> dict | None:
    f = MODELS_DIR / "tissue_v2" / "metrics.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ct_demo_card() -> dict:
    demo = MODELS_DIR.parent / "demo_ct"
    try:
        summary = json.loads((demo / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "not available"}
    ev = None
    try:
        ev = json.loads((demo / "eval" / "eval_summary.json").read_text(encoding="utf-8"))
        ev.pop("froc", None)
    except (OSError, ValueError):
        pass
    card = {
        "state": "precomputed demo of an open-source detector (not run live in the app)",
        "model": summary.get("model"),
        "data": summary.get("data"),
        "caveat": "Finds nodule candidates; it does not say whether a nodule is cancer.",
    }
    if ev:
        card["evaluation"] = ev
        card["note"] = ev.get("note")
        card["caveat"] += (f" Tested on {ev['n_scans']} public scans with {ev['n_marked_nodules']} marked nodules, so the intervals are wide. "
                           "False alarms are probably overstated because the reference list of ignorable findings was not available.")
    else:
        card["measured"] = summary.get("thresholds")
        card["note"] = summary.get("note")
        card["caveat"] += " Only 4 scans, so these figures are very noisy."
    card["improvement_attempt"] = ("Tried to improve it on 40 more public scans (41 marked nodules): keeping only the top-scoring candidates "
                                   "per scan, and second-stage filters trained to reject false alarms. None clearly beat the detector's own "
                                   "score (it found 73% of marked nodules at 1 false alarm per scan, range 62% to 88%; the best variant, "
                                   "top 3 per scan, scored 76%, within the noise), so the detector is used as it is.")
    return card


@router.get("/health")
def health():
    return {"status": "ok", "model": MODEL_VERSION, "gemini_configured": bool(settings.gemini_key),
            "email_mode": settings.email_mode}


@router.get("/model-card")
def model_card(user: User = Depends(current_user)):
    m = _tissue_metrics()
    tissue_ready = m is not None
    return {
        "status": "tissue_trained_ct_placeholder" if tissue_ready else "no_trained_model",
        "model_version": MODEL_VERSION,
        "intended_use": "Research prototype that flags lung scans for priority review by a doctor.",
        "not_intended_for": "Diagnosis, treatment decisions, or use with real patient data.",
        "models": {
            "tissue": {
                "state": "trained research model" if tissue_ready else "not available",
                "version": TISSUE_VERSION,
                "data": "LC25000 lung images (lung_aca, lung_n, lung_scc): about 750 originals augmented to 13,501 images",
                "method": "EfficientNet-B0 transfer learning; near-duplicate images grouped so copies never sit in "
                          "both train and test; random grayscale (50%) and brightness/contrast jitter, label smoothing, "
                          "cosine schedule; Grad-CAM heatmap",
                "risk_score": "1 - P(lung_n). Priority tiers (heuristic): high >= "
                              f"{TISSUE_HIGH:.2f}, review >= {TISSUE_REVIEW:.2f}",
                "measured": m,
            },
            "ct_detector_demo": _ct_demo_card(),
            "ct": {
                "state": "open-source nodule detector runs on uploaded CT volumes; single CT images get a flagged placeholder score",
                "note": "Uploaded whole CT volumes (NIfTI, MetaImage or a zipped DICOM series) are analysed by the MONAI lung nodule "
                        "detector. It marks nodule candidates for a doctor to look at; it does not say whether a nodule is cancer, and "
                        "its score is not a cancer probability. Earlier trial CT classifiers scored near-perfectly but a border-only test "
                        "showed they relied on dataset artifacts, so they are not used. Runs on the server's CPU unless a GPU is present, "
                        "so a scan can take several minutes.",
            },
        },
        "thresholds": {"tissue_high": TISSUE_HIGH, "tissue_review": TISSUE_REVIEW,
                       "ct_placeholder_high": settings.threshold_high, "ct_placeholder_review": settings.threshold_review,
                       "note": "Tissue review tier = the cancer-vs-normal cut-off chosen on validation images; the high tier "
                               "(0.90) is a heuristic. The model was trained with label smoothing, so its scores top out "
                               "around 0.93 and the uncertainty bands (Low >= 0.85, Medium >= 0.65) are heuristics too."},
        "limitations": [
            "Tissue model: one public dataset made from about 750 original photos; even with grouping, about half the "
            "test images have a lookalike in training at similarity 0.85, so the score is probably optimistic.",
            "Tissue model labels are slide types (adenocarcinoma, squamous cell, normal), not a diagnosis, and it was "
            "never tested on slides from another lab or stain.",
            "Heatmaps are coarse: they show where the model looked, not proof that it is right.",
            "CT: the detector was checked on 24 and then 40 public scans only (about 73% to 78% of marked nodules found at 1 false alarm "
            "per scan). Single CT images (not whole volumes) get a placeholder score with no medical meaning. The CT nodule demo page "
            "shows saved results on 4 public scans.",
            "No clinical or multi-hospital validation.",
        ],
        "disclaimer": DISCLAIMER,
    }


@router.get("/metrics")
def metrics(user: User = Depends(current_user)):
    m = _tissue_metrics()
    return {"status": "tissue_only" if m else "not_trained", "tissue": m, "ct": None}


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    user_name: str = ""
    action: str
    patient_id: int | None
    detail: str
    timestamp: datetime


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    patient_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(require_roles(DOCTOR, ADMIN)),
    db: Session = Depends(get_db),
):
    stmt = (select(AuditLog, User.full_name).join(User, User.id == AuditLog.user_id, isouter=True)
            .order_by(AuditLog.id.desc()).limit(limit))
    if patient_id is not None:
        stmt = stmt.where(AuditLog.patient_id == patient_id)
    return [AuditOut(id=a.id, user_id=a.user_id, user_name=name or "", action=a.action, patient_id=a.patient_id,
                     detail=a.detail, timestamp=a.timestamp) for a, name in db.execute(stmt)]
