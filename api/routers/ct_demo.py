"""Precomputed CT nodule-detector demo.

The detections were produced in Google Colab by the open-source MONAI `lung_nodule_ct_detection` bundle (Apache-2.0)
on 4 public LUNA16 scans (CC BY 4.0, from LIDC-IDRI, CC BY 3.0). The app only DISPLAYS the saved results: it does not
run the detector. Files live in `demo_ct/case_N/` (JPEG slices + meta.json) and `demo_ct/summary.json`.
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import BASE_DIR, DISCLAIMER
from ..database import get_db
from ..deps import audit, current_user
from ..models import User

router = APIRouter(prefix="/ct-demo", tags=["ct-demo"])

DEMO_DIR = BASE_DIR / "demo_ct"
CASE_RE = re.compile(r"^case_\d{1,3}$")

CREDITS = ("Detector: MONAI lung_nodule_ct_detection (Apache-2.0). Data: LUNA16 (CC BY 4.0, https://luna16.grand-challenge.org), "
           "derived from LIDC-IDRI (CC BY 3.0). Results were computed offline; this page only shows them.")


def _case_dir(case: str):
    if not CASE_RE.match(case):
        raise HTTPException(404, "Unknown case")
    d = DEMO_DIR / case
    if not d.is_dir():
        raise HTTPException(404, "Unknown case")
    return d


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(404, "Demo data not available")


def _evaluation():
    f = DEMO_DIR / "eval" / "eval_summary.json"
    if not f.is_file():
        return None
    d = _read_json(f)
    d.pop("froc", None)  # the curve points are drawn in froc.png
    return d


@router.get("/eval/froc.png")
def froc_image(user: User = Depends(current_user)):
    f = DEMO_DIR / "eval" / "froc.png"
    if not f.is_file():
        raise HTTPException(404, "No evaluation picture")
    return FileResponse(f, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@router.get("")
def list_cases(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not DEMO_DIR.is_dir():
        return {"summary": None, "evaluation": None, "cases": [], "credits": CREDITS, "disclaimer": DISCLAIMER}
    cases = []
    for d in sorted((p for p in DEMO_DIR.iterdir() if p.is_dir() and CASE_RE.match(p.name)), key=lambda p: int(p.name.split("_")[1])):
        meta = _read_json(d / "meta.json")
        cases.append({"case": d.name, "n_slices": meta["n_slices"], "marked_nodules": len(meta["radiologist_nodules"]),
                      "detections": len(meta["detections"]),
                      "top_score": max((x["score"] for x in meta["detections"]), default=None)})
    summary = _read_json(DEMO_DIR / "summary.json") if (DEMO_DIR / "summary.json").is_file() else None
    audit(db, user, "view_ct_demo", None, f"{len(cases)} cases")
    return {"summary": summary, "evaluation": _evaluation(), "cases": cases, "credits": CREDITS, "disclaimer": DISCLAIMER}


@router.get("/{case}")
def case_meta(case: str, user: User = Depends(current_user)):
    return _read_json(_case_dir(case) / "meta.json")


@router.get("/{case}/slice/{index}")
def case_slice(case: str, index: int, user: User = Depends(current_user)):
    d = _case_dir(case)
    if index < 0 or index > 2000:
        raise HTTPException(404, "No such slice")
    f = d / f"{index:03d}.jpg"
    if not f.is_file():
        raise HTTPException(404, "No such slice")
    return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})
