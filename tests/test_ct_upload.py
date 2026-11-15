"""CT volume upload: input checks and bookkeeping. The detector itself is not run here (it needs the downloaded weights
and takes minutes), so `ct_service.submit` is replaced by a no-op."""
import tempfile
from pathlib import Path

import numpy as np
import pytest

sitk = pytest.importorskip("SimpleITK")

from api.services import ct_service  # noqa: E402


def nifti_bytes(arr: np.ndarray, spacing=(0.7, 0.7, 2.5)) -> bytes:
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing(spacing)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "v.nii.gz"
        sitk.WriteImage(img, str(p))
        return p.read_bytes()


def ct_like(z=40, y=48, x=48) -> np.ndarray:
    a = np.full((z, y, x), -900, dtype=np.int16)      # lung
    a[:, 10:20, 10:20] = 300                          # bone
    a[:, 0:3, :] = -1000                              # air
    return a


def post(client, tokens, data: bytes, name: str, who="rad1", pid=1):
    return client.post(f"/patients/{pid}/scans", headers=tokens[who], data={"scan_type": "ct"},
                       files={"file": (name, data, "application/octet-stream")})


@pytest.fixture(autouse=True)
def no_detector(monkeypatch):
    calls = []
    monkeypatch.setattr(ct_service, "submit", lambda scan_id, img: calls.append(scan_id))
    monkeypatch.setattr(ct_service, "available", lambda: (True, ""))
    return calls


def test_volume_accepted_and_marked_processing(client, tokens, no_detector):
    pid = client.post("/patients", json={"name": "CT Person", "age": 60, "sex": "male"}, headers=tokens["doc1"]).json()["id"]
    r = post(client, tokens, nifti_bytes(ct_like()), "scan.nii.gz", pid=pid)
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["status"] == "processing" and res["is_placeholder"] is False and res["priority"] is None
    assert no_detector == [r.json()["id"]]
    sid = r.json()["id"]
    assert client.get(f"/scans/{sid}/image", headers=tokens["doc1"]).status_code == 200       # preview slice exists
    assert client.get(f"/scans/{sid}/ct", headers=tokens["doc1"]).status_code == 404          # no results yet
    assert client.get(f"/scans/{sid}/ct/slice/0", headers=tokens["doc1"]).status_code == 404
    status = client.get("/dashboard", headers=tokens["doc1"]).json()["recent_scans"][0]["status"]
    assert status == "Processing"


def test_only_radiologists_upload_volumes(client, tokens):
    assert post(client, tokens, nifti_bytes(ct_like()), "scan.nii.gz", who="doc1").status_code == 403


def test_rejects_bad_volumes(client, tokens):
    assert post(client, tokens, b"not an image", "x.nii.gz").status_code == 400                      # unreadable
    assert post(client, tokens, nifti_bytes(ct_like(z=10)), "short.nii.gz").status_code == 400        # too few slices
    assert post(client, tokens, nifti_bytes(np.random.default_rng(0).integers(0, 200, (40, 48, 48)).astype(np.int16)),
                "mri.nii.gz").status_code == 400                                                     # not Hounsfield-like
    assert post(client, tokens, nifti_bytes(ct_like()[0]), "flat.nii.gz").status_code == 400          # 2D image
    assert post(client, tokens, b"", "empty.nii.gz").status_code == 400


def test_unsafe_zip_rejected(client, tokens):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../evil.mhd", "x")
    assert post(client, tokens, buf.getvalue(), "evil.zip").status_code == 400


def test_single_ct_image_is_flagged_placeholder(client, tokens):
    from .test_api import png_bytes, upload
    r = upload(client, tokens, 1, png_bytes(seed=7), scan_type="ct").json()
    assert r["result"]["is_placeholder"] is True and "whole CT volume" in r["result"]["message"]
