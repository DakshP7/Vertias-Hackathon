"""CT nodule detection for uploaded volumes.

Runs the open-source MONAI `lung_nodule_ct_detection` bundle (Apache-2.0, 3D RetinaNet) on a CT volume that a radiologist
uploads (NIfTI, MetaImage or a DICOM series, optionally zipped). It finds nodule CANDIDATES: spots a doctor should look at.
It does NOT say whether a nodule is cancer. The pipeline is the same one that was checked on public LUNA16 scans in
`ml/CellIQ_ct_detector.ipynb` and `ml/CellIQ_ct_improve.ipynb`.

Detection runs in a background thread, one scan at a time (it can take minutes on a CPU). Results are stored in
`<uploads>/ct_<scan id>/` as JPEG slices plus `meta.json`, in the same format as the demo cases in `demo_ct/`.
"""
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

from ..config import BASE_DIR, settings

log = logging.getLogger("celliq")

BUNDLE = BASE_DIR / "models" / "ct_detector" / "lung_nodule_ct_detection"
CT_VERSION = "MONAI lung_nodule_ct_detection v0.6.9 (Apache-2.0)"
SIZE = 384                      # exported slice size in pixels
MIN_SCORE_EXPORT = 0.1          # detections below this are not stored
SCORE_SHOWN = 0.5               # candidates at or above this count as "found"
MAX_ZIP_FILES, MAX_ZIP_BYTES = 4000, 2_000_000_000
MAX_DIM_XY, MAX_DIM_Z, MIN_DIM_Z = 1024, 900, 30
VOLUME_SUFFIXES = (".nii", ".nii.gz", ".mhd", ".mha", ".nrrd")

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ct-detect")


class CTError(ValueError):
    """A problem with the uploaded volume that the user can understand."""


def available() -> tuple[bool, str]:
    if not (BUNDLE / "models" / "model.pt").is_file():
        return False, "The CT detector weights are not installed (models/ct_detector)."
    for mod in ("monai", "SimpleITK", "ignite", "itk"):
        if importlib.util.find_spec(mod) is None:
            return False, f"The Python package '{mod}' is not installed."
    return True, ""


def is_volume_name(name: str) -> bool:
    n = (name or "").lower()
    return n.endswith(VOLUME_SUFFIXES) or n.endswith(".zip")


def ct_dir(scan_id: int) -> Path:
    return settings.upload_dir / f"ct_{scan_id}"


# ------------------------------------------------------------------ reading volumes
def _safe_extract(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_FILES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise CTError("The zip file is too large or has too many files.")
        root = dest.resolve()
        for info in infos:
            target = (dest / info.filename).resolve()
            if root not in target.parents and target != root:
                raise CTError("The zip file contains unsafe file paths.")
        z.extractall(dest)


def _read_dicom_series(folder: Path):
    import SimpleITK as sitk
    best = None
    for sub in [folder, *[p for p in folder.rglob("*") if p.is_dir()]]:
        for sid in sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(sub)) or []:
            files = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(sub), sid)
            if best is None or len(files) > len(best):
                best = files
    if not best:
        return None
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(best)
    return reader.Execute()


def read_volume(path: Path, original_name: str):
    """Return a 3D SimpleITK image in Hounsfield units, or raise CTError."""
    import SimpleITK as sitk
    name = original_name.lower()
    try:
        if name.endswith(".zip"):
            with tempfile.TemporaryDirectory() as tmp:
                _safe_extract(path, Path(tmp))
                found = [p for p in Path(tmp).rglob("*") if p.is_file() and p.name.lower().endswith(VOLUME_SUFFIXES)]
                if found:
                    img = sitk.ReadImage(str(sorted(found)[0]))
                else:
                    img = _read_dicom_series(Path(tmp))
                    if img is None:
                        raise CTError("No CT volume found in the zip. Use a NIfTI/MetaImage file or a DICOM series folder.")
        else:
            suffix = next(s for s in VOLUME_SUFFIXES if name.endswith(s))
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / ("scan" + suffix)
                shutil.copyfile(path, p)
                img = sitk.ReadImage(str(p))
    except CTError:
        raise
    except Exception as exc:  # unreadable or unsupported file
        log.info("CT volume could not be read: %s", type(exc).__name__)
        raise CTError("The file could not be read as a 3D CT volume.") from exc

    if img.GetDimension() == 4:
        raise CTError("4D images are not supported.")
    if img.GetDimension() != 3:
        raise CTError("A single 2D image cannot be analysed by the 3D detector. Upload the whole CT volume.")
    x, y, z = img.GetSize()
    if z < MIN_DIM_Z:
        raise CTError(f"The volume has only {z} slices; at least {MIN_DIM_Z} are needed.")
    if x > MAX_DIM_XY or y > MAX_DIM_XY or z > MAX_DIM_Z:
        raise CTError("The volume is larger than this prototype accepts.")
    img = sitk.Cast(img, sitk.sitkInt16) if img.GetPixelID() != sitk.sitkInt16 else img
    arr = sitk.GetArrayViewFromImage(img)
    lo, hi = int(arr.min()), int(arr.max())
    if lo > -300 or hi < 100:
        raise CTError("The values do not look like a chest CT in Hounsfield units (air should be about -1000).")
    return img


def lung_window(slice_hu: np.ndarray) -> np.ndarray:
    return (np.clip((slice_hu.astype(np.float32) + 1000.0) / 1300.0, 0, 1) * 255).astype("uint8")


def preview_png(img) -> bytes:
    """Middle slice as PNG, used as the scan's thumbnail everywhere in the app."""
    import io

    import SimpleITK as sitk
    arr = sitk.GetArrayViewFromImage(img)
    im = Image.fromarray(lung_window(arr[arr.shape[0] // 2])).resize((512, 512), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ detection
def _unwrap(d):
    if isinstance(d, dict):
        for k in ("validation", "results", "data", "predictions"):
            if isinstance(d.get(k), list):
                return d[k]
        return [d]
    return d


def _pick(rec, keys):
    for k in keys:
        if isinstance(rec, dict) and k in rec:
            return rec[k]
    return None


def _run_bundle(case_dir: Path, work: Path) -> Path:
    cfg = json.loads((BUNDLE / "configs" / "inference.json").read_text(encoding="utf-8"))
    cfg["whether_raw_luna16"] = True              # volumes are written as .mhd in LPS space, like raw LUNA16
    cfg["dataset_dir"] = str(case_dir)
    cfg["data_list_file_path"] = str(work / "datalist.json")
    cfg["output_dir"] = str(work / "det_out")
    cfg["output_filename"] = "result.json"
    cfg["dataloader"]["num_workers"] = 0
    import torch
    if not torch.cuda.is_available():               # the weights were saved on a GPU; load them onto the CPU
        cfg["checkpointloader"]["map_location"] = "cpu"
        cfg["amp"] = False
    (work / "det_out").mkdir(exist_ok=True)
    (work / "datalist.json").write_text(json.dumps({"validation": [{"image": "scan.mhd"}]}), encoding="utf-8")
    cfg_path = work / "infer_cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "monai.bundle", "run", "--config_file", str(cfg_path),
                        "--meta_file", str(BUNDLE / "configs" / "metadata.json")],
                       cwd=str(BUNDLE), capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("CT detector failed: %s", (r.stdout + r.stderr)[-800:])
        raise RuntimeError("The detector run failed.")
    return work / "det_out" / "result.json"


def _export(img, boxes: np.ndarray, scores: np.ndarray, out: Path) -> dict:
    import SimpleITK as sitk
    arr = sitk.GetArrayFromImage(img)                     # z, y, x in HU
    sp = img.GetSpacing()                                 # x, y, z in mm
    out.mkdir(parents=True, exist_ok=True)
    for k in range(arr.shape[0]):
        Image.fromarray(lung_window(arr[k])).resize((SIZE, SIZE), Image.BILINEAR).save(out / f"{k:03d}.jpg", quality=82)
    dets = []
    for b, s in sorted(zip(boxes, scores), key=lambda x: -x[1]):
        if s < MIN_SCORE_EXPORT or len(dets) >= 40:
            continue
        ix, iy, iz = img.TransformPhysicalPointToContinuousIndex([float(b[0]), float(b[1]), float(b[2])])
        dets.append({"score": round(float(s), 3),
                     "center_px": [round(ix * SIZE / arr.shape[2], 1), round(iy * SIZE / arr.shape[1], 1)],
                     "size_px": [round(b[3] / sp[0] * SIZE / arr.shape[2], 1), round(b[4] / sp[1] * SIZE / arr.shape[1], 1)],
                     "slice": int(round(iz)), "depth_slices": round(float(b[5] / sp[2]), 1),
                     "diameter_mm": round(float(max(b[3], b[4])), 1)})
    meta = {"n_slices": int(arr.shape[0]), "slice_size": SIZE, "spacing_mm": [round(s, 3) for s in sp],
            "detections": dets, "radiologist_nodules": [], "model": CT_VERSION}
    (out / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def _finish(scan_id: int, **fields) -> None:
    from ..database import SessionLocal
    from ..models import AIResult
    from sqlalchemy import select
    with SessionLocal() as db:
        res = db.scalar(select(AIResult).where(AIResult.scan_id == scan_id))
        if res:
            for k, v in fields.items():
                setattr(res, k, v)
            db.commit()


def _process(scan_id: int, work: Path) -> None:
    t0 = time.time()
    try:
        import SimpleITK as sitk
        img = sitk.ReadImage(str(work / "case" / "scan.mhd"))
        result_file = _run_bundle(work / "case", work)
        recs = _unwrap(json.loads(result_file.read_text(encoding="utf-8")))
        rec = recs[0] if recs else {}
        boxes = np.array(_pick(rec, ["box", "boxes", "pred_box"]) or [], dtype=float).reshape(-1, 6)
        scores = np.array(_pick(rec, ["label_scores", "scores", "score", "label_score"]) or [], dtype=float).reshape(-1)
        meta = _export(img, boxes, scores, ct_dir(scan_id))
        shown = [d for d in meta["detections"] if d["score"] >= SCORE_SHOWN]
        top = max((d["score"] for d in meta["detections"]), default=0.0)
        if shown:
            msg = (f"Nodule detector: {len(shown)} candidate(s) with score {SCORE_SHOWN:.2f} or higher (top score {top:.2f}). "
                   "Candidates are spots for a doctor to look at, not a diagnosis; a nodule is not necessarily cancer.")
        else:
            msg = ("Nodule detector: no candidates with score 0.50 or higher. This does not rule out disease; "
                   "a doctor must still review the scan.")
        _finish(scan_id, status="analysed", risk_score=round(float(top), 3),
                priority="PRIORITY REVIEW" if shown else "ROUTINE REVIEW", uncertainty="Medium" if shown else "Low",
                message=msg[:300], model_version=CT_VERSION[:60], is_placeholder=False,
                threshold_review=SCORE_SHOWN, threshold_high=1.0)
        log.info("CT scan %s done in %.0fs: %d candidates", scan_id, time.time() - t0, len(shown))
    except Exception as exc:
        log.warning("CT scan %s failed: %s", scan_id, type(exc).__name__)
        _finish(scan_id, status="cannot_assess", priority=None, risk_score=None, uncertainty=None,
                message="The CT detector could not process this volume. Check the file and try again."[:300])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def submit(scan_id: int, img) -> None:
    """Write the volume to a temp folder and queue detection. Returns immediately."""
    import SimpleITK as sitk
    work = Path(tempfile.mkdtemp(prefix=f"celliq_ct{scan_id}_"))
    (work / "case").mkdir()
    sitk.WriteImage(img, str(work / "case" / "scan.mhd"))
    _pool.submit(_process, scan_id, work)


def recover_stale() -> None:
    """After a restart, scans still marked 'processing' will never finish: mark them so users can re-upload."""
    from sqlalchemy import select, update

    from ..database import SessionLocal
    from ..models import AIResult
    with SessionLocal() as db:
        db.execute(update(AIResult).where(AIResult.status == "processing").values(
            status="cannot_assess", message="The server restarted while this scan was being analysed. Please upload it again."))
        db.commit()
