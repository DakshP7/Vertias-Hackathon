"""AI inference interface.

- Tissue scans (`scan_type == "tissue"`) use the trained tissue model in `models/tissue_v2` (EfficientNet-B0 trained
  on the lung part of LC25000, group-aware split). Risk score = 1 - P(lung_n). Heatmap = Grad-CAM.
  This is a RESEARCH model, not clinically validated. Its score comes from one public dataset.
- CT scans uploaded as a single image are still a PLACEHOLDER (whole CT volumes go to `ct_service`, which runs the MONAI nodule detector): the score is a hash of the image bytes and has no medical
  meaning. Every placeholder result is flagged `is_placeholder=True`.

If PyTorch or the model files are missing, tissue scans fall back to the placeholder (also flagged).
"""
import hashlib
import io
import json
import logging
import threading
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..config import BASE_DIR, settings

log = logging.getLogger("celliq")

PLACEHOLDER_VERSION = "PLACEHOLDER-0 (no trained model)"
TISSUE_VERSION = "tissue-v3 (EfficientNet-B0, LC25000 lung, group split, grayscale-robust recipe)"
MODELS_DIR = BASE_DIR / "models"
MIN_SIDE = 64

# Triage tiers for the tissue model (v3 was trained with label smoothing, so its scores top out around 0.93).
# Review tier = the cancer-vs-normal cut-off chosen on validation images (0.51 in models/tissue_v2/meta.json; on
# validation every cancer slide scored >= 0.82 and every normal slide <= 0.20). The high tier is a heuristic.
TISSUE_HIGH, TISSUE_REVIEW = 0.90, 0.51

MODEL_VERSION = TISSUE_VERSION + " | CT: " + PLACEHOLDER_VERSION  # shown on /health


@dataclass
class Analysis:
    status: str  # analysed | cannot_assess
    risk_score: float | None
    priority: str | None
    uncertainty: str | None
    message: str
    heatmap_png: bytes | None
    model_version: str = PLACEHOLDER_VERSION
    is_placeholder: bool = True
    threshold_high: float = field(default_factory=lambda: settings.threshold_high)
    threshold_review: float = field(default_factory=lambda: settings.threshold_review)


def priority_for(score: float, high: float, review: float) -> str:
    if score >= high:
        return "HIGH PRIORITY"
    if score >= review:
        return "PRIORITY REVIEW"
    return "ROUTINE REVIEW"


def _jet(x: np.ndarray) -> np.ndarray:
    """Simple jet-like colormap, x in [0, 1] -> RGB floats."""
    r = np.clip(1.5 - np.abs(4 * x - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * x - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * x - 1), 0, 1)
    return np.stack([r, g, b], axis=-1)


def _overlay(img: Image.Image, cam: np.ndarray) -> bytes:
    base = np.asarray(img.convert("RGB").resize(cam.shape[::-1]), dtype=np.float32) / 255.0
    blend = 0.55 * base + 0.45 * _jet(cam)
    out = Image.fromarray((np.clip(blend, 0, 1) * 255).astype("uint8"))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _placeholder_heatmap(img: Image.Image, seed: int) -> bytes:
    rng = np.random.default_rng(seed)
    w, h = img.size
    cx, cy = rng.uniform(0.3, 0.7) * w, rng.uniform(0.3, 0.7) * h
    yy, xx = np.mgrid[0:h, 0:w]
    sigma = 0.15 * max(w, h)
    cam = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma**2)))
    return _overlay(img, cam)


def _basic_guard(img: Image.Image) -> Analysis | None:
    """'Cannot assess' guard: reject tiny or almost-blank images instead of guessing."""
    arr = np.asarray(img.convert("L"), dtype=np.float32)
    if min(img.size) < MIN_SIDE:
        return Analysis("cannot_assess", None, None, None,
                        f"Image is too small (minimum {MIN_SIDE}px per side).", None)
    if float(arr.std()) < 3.0:
        return Analysis("cannot_assess", None, None, None,
                        "Image is almost blank or uniform and cannot be assessed.", None)
    return None


def _placeholder(png_bytes: bytes, scan_type: str, img: Image.Image, note: str = "") -> Analysis:
    digest = hashlib.sha256(png_bytes + scan_type.encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    score = round((seed % 10_000) / 10_000, 3)
    margin = abs(score - settings.threshold_review)
    uncertainty = "High" if margin < 0.05 else "Medium" if margin < 0.15 else "Low"
    return Analysis(
        "analysed", score, priority_for(score, settings.threshold_high, settings.threshold_review), uncertainty,
        "PLACEHOLDER result: no trained model for this scan type yet. This score has no medical meaning." + note,
        _placeholder_heatmap(img, seed % (2**32)),
    )


# ---------------------------------------------------------------- tissue model
_tissue = None  # None = not tried yet, False = unavailable, dict = loaded
_lock = threading.Lock()


def _load_tissue():
    global _tissue
    if _tissue is not None:
        return _tissue or None
    d = MODELS_DIR / "tissue_v2"
    try:
        import torch
        import torchvision
        from torchvision import transforms

        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        model = torchvision.models.efficientnet_b0(weights=None)
        model.classifier[1] = torch.nn.Linear(model.classifier[1].in_features, len(meta["classes"]))
        model.load_state_dict(torch.load(d / "model.pt", map_location="cpu", weights_only=True))
        model.eval()
        tf = transforms.Compose([
            transforms.Resize((meta["img_size"], meta["img_size"])), transforms.ToTensor(),
            transforms.Normalize(meta["normalize_mean"], meta["normalize_std"])])
        _tissue = {"torch": torch, "model": model, "tf": tf, "meta": meta,
                   "normal_idx": meta["classes"].index("lung_n")}
        log.info("Loaded tissue model from %s", d)
    except Exception as exc:  # missing torch, files, or mismatched weights
        log.warning("Tissue model unavailable (%s); using placeholder.", type(exc).__name__)
        _tissue = False
    return _tissue or None


def _tissue_analyze(img: Image.Image, t: dict) -> Analysis:
    torch, model, meta = t["torch"], t["model"], t["meta"]
    rgb = img.convert("RGB")

    # Guard: the tissue model expects coloured stained slides. A grayscale image (for example a CT) is out of scope.
    a = np.asarray(rgb.resize((128, 128)), dtype=np.float32)
    colourfulness = float(np.abs(a[..., 0] - a[..., 1]).mean() + np.abs(a[..., 1] - a[..., 2]).mean())
    if colourfulness < 4.0:
        return Analysis("cannot_assess", None, None, None,
                        "This looks like a grayscale image. The tissue model expects stained microscope slides "
                        "(for chest CT, choose the CT scan type).", None)

    x = t["tf"](rgb).unsqueeze(0)
    store: dict = {}

    def fwd_hook(_m, _i, out):
        store["a"] = out
        out.register_hook(lambda g: store.__setitem__("g", g))

    with _lock:  # the model and its hook are shared between requests
        handle = model.features[-1].register_forward_hook(fwd_hook)
        try:
            with torch.enable_grad():
                logits = model(x)
                probs = torch.softmax(logits, dim=1)[0].detach().numpy()
                cls = int(probs.argmax())
                model.zero_grad()
                logits[0, cls].backward()
                w = store["g"].mean(dim=(2, 3), keepdim=True)
                cam = torch.relu((w * store["a"]).sum(1, keepdim=True))
                cam = torch.nn.functional.interpolate(
                    cam, size=(meta["img_size"], meta["img_size"]), mode="bilinear", align_corners=False)[0, 0]
                cam = ((cam - cam.min()) / (cam.max() - cam.min() + 1e-8)).detach().numpy()
        finally:
            handle.remove()

    risk = float(1.0 - probs[t["normal_idx"]])
    top = float(probs[cls])
    # Label smoothing caps the top probability near 0.93, so the bands sit lower than they did for the v2 model.
    uncertainty = "Low" if top >= 0.85 else "Medium" if top >= 0.65 else "High"
    label = meta["classes"][cls]
    return Analysis(
        "analysed", round(risk, 3), priority_for(risk, TISSUE_HIGH, TISSUE_REVIEW), uncertainty,
        f"Research model, not clinically validated. Predicted slide type: {label} ({top * 100:.0f}%). "
        "Trained on one public dataset; see the model card.",
        _overlay(rgb, cam), model_version=TISSUE_VERSION, is_placeholder=False,
        threshold_high=TISSUE_HIGH, threshold_review=TISSUE_REVIEW,
    )


# ---------------------------------------------------------------- entry point
def analyze(png_bytes: bytes, scan_type: str) -> Analysis:
    img = Image.open(io.BytesIO(png_bytes))
    guard = _basic_guard(img)
    if guard:
        return guard
    if scan_type == "tissue":
        t = _load_tissue()
        if t:
            return _tissue_analyze(img, t)
        return _placeholder(png_bytes, scan_type, img, " (tissue model could not be loaded)")
    return _placeholder(png_bytes, scan_type, img,
                        " The 3D nodule detector needs a whole CT volume (NIfTI, MetaImage or a DICOM series as a .zip); a single image cannot be analysed.")
