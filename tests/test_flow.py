"""Tests for the dashboard, doctor review of AI results, and emailing approved reports."""
import email
from email import policy
from pathlib import Path

from .test_api import png_bytes, upload


def make_patient_with_scan(client, tokens, name="Flow Person", seed=50):
    pid = client.post("/patients", json={"name": name, "age": 61, "sex": "male"}, headers=tokens["doc1"]).json()["id"]
    scan = upload(client, tokens, pid, png_bytes(seed=seed)).json()
    return pid, scan["id"]


def test_dashboard(client, tokens):
    make_patient_with_scan(client, tokens, "Dash Person", seed=60)
    d = client.get("/dashboard", headers=tokens["doc1"]).json()
    assert d["counts"]["patients"] >= 1 and d["counts"]["scans"] >= 1
    assert d["email_mode"] == "outbox"
    scores = [p["highest_risk"] for p in d["urgent"]]
    assert scores == sorted(scores, reverse=True) and len(d["urgent"]) <= 5
    assert d["recent_activity"]  # doctors see recent activity
    assert d["counts"]["scans_7d"] >= 1 and "scans_prev_7d" in d["counts"]
    assert d["user_role"] == "doctor"
    rs = d["recent_scans"]
    assert 1 <= len(rs) <= 6
    assert {"scan_id", "patient_id", "name", "scan_type", "status", "has_heatmap", "is_placeholder"} <= set(rs[0])
    assert rs[0]["status"] in {"Urgent", "In review", "Completed", "AI analysed", "Cannot assess"}
    times = [r["uploaded_at"] for r in rs]
    assert times == sorted(times, reverse=True)  # newest first

    rad = client.get("/dashboard", headers=tokens["rad1"]).json()
    assert rad["recent_activity"] == []  # same visibility rule as the audit log
    assert client.get("/dashboard").status_code == 401


def test_doctor_review_of_ai_result(client, tokens):
    pid, scan_id = make_patient_with_scan(client, tokens, "Review Person", seed=61)
    body = {"verdict": "agree", "note": "Consistent with symptoms."}
    assert client.post(f"/scans/{scan_id}/reviews", json=body, headers=tokens["rad1"]).status_code == 403
    assert client.post(f"/scans/{scan_id}/reviews", json={"verdict": "maybe"}, headers=tokens["doc1"]).status_code == 422
    assert client.post(f"/scans/{scan_id}/reviews", json=body, headers=tokens["doc1"]).status_code == 201
    assert client.post(f"/scans/{scan_id}/reviews", json={"verdict": "disagree"}, headers=tokens["doc2"]).status_code == 201

    # a doctor changing their mind replaces their verdict instead of adding a second one
    client.post(f"/scans/{scan_id}/reviews", json={"verdict": "needs_more", "note": "Repeat imaging."}, headers=tokens["doc1"])
    rows = client.get(f"/scans/{scan_id}/reviews", headers=tokens["rad1"]).json()
    assert sorted(r["verdict"] for r in rows) == ["disagree", "needs_more"]
    assert client.get(f"/patients/{pid}", headers=tokens["doc1"]).json()["status"] == "Under review"

    rep = client.post(f"/patients/{pid}/report", headers=tokens["doc1"]).json()
    assert "Doctor review" in rep["draft_text"]


def test_email_flow_outbox(client, tokens):
    pid, _ = make_patient_with_scan(client, tokens, "Mail Person", seed=62)
    rep = client.post(f"/patients/{pid}/report", headers=tokens["doc1"]).json()
    rid = rep["id"]
    to = {"recipient": "patient@example.invalid"}

    # not approved yet
    assert client.post(f"/reports/{rid}/send", json=to, headers=tokens["doc1"]).status_code == 409
    client.put(f"/reports/{rid}/approve", headers=tokens["doc1"])

    # only doctors; recipient must look like one email address
    assert client.post(f"/reports/{rid}/send", json=to, headers=tokens["rad1"]).status_code == 403
    for bad in ("", "no-at-sign", "a@b", "a@b.com, c@d.com", "a@b.com\nBcc: x@y.com", "<a@b.com>"):
        assert client.post(f"/reports/{rid}/send", json={"recipient": bad}, headers=tokens["doc1"]).status_code == 422, bad

    before = set(Path(__import__("os").environ["CELLIQ_OUTBOX"]).glob("*.eml"))
    r = client.post(f"/reports/{rid}/send", json=to, headers=tokens["doc1"])
    assert r.status_code == 201, r.text
    assert r.json()["mode"] == "outbox" and r.json()["recipient"] == to["recipient"]

    new = set(Path(__import__("os").environ["CELLIQ_OUTBOX"]).glob("*.eml")) - before
    assert len(new) == 1
    msg = email.message_from_bytes(new.pop().read_bytes(), policy=policy.default)
    assert msg["To"] == to["recipient"]
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1 and attachments[0].get_content_type() == "application/pdf"
    assert attachments[0].get_content().startswith(b"%PDF")

    log = client.get(f"/reports/{rid}/emails", headers=tokens["doc2"]).json()
    assert len(log) == 1 and log[0]["mode"] == "outbox"
    actions = {e["action"] for e in client.get("/audit", params={"limit": 500}, headers=tokens["doc1"]).json()}
    assert "email_report" in actions


def test_email_rate_limit(client, tokens, monkeypatch):
    from api.config import settings
    monkeypatch.setattr(settings, "max_emails_per_hour", 1)
    pid, _ = make_patient_with_scan(client, tokens, "Limit Person", seed=63)
    rid = client.post(f"/patients/{pid}/report", headers=tokens["doc2"]).json()["id"]
    client.put(f"/reports/{rid}/approve", headers=tokens["doc2"])
    to = {"recipient": "x@example.invalid"}
    first = client.post(f"/reports/{rid}/send", json=to, headers=tokens["doc2"]).status_code
    second = client.post(f"/reports/{rid}/send", json=to, headers=tokens["doc2"]).status_code
    assert first in (201, 429)  # doc2 may already have sent earlier in the session
    assert second == 429


def stained_png(size=256, seed=5) -> bytes:
    """A synthetic pink/purple 'slide-like' image. NOT a real slide: used only to exercise the code path."""
    import io as _io
    import numpy as _np
    from PIL import Image as _Image
    rng = _np.random.default_rng(seed)
    base = _np.array([200, 120, 190], dtype=float)
    arr = (base + rng.normal(0, 25, (size, size, 3)) + _np.linspace(-20, 20, size)[None, :, None]).clip(0, 255).astype("uint8")
    buf = _io.BytesIO()
    _Image.fromarray(arr, "RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_tissue_scan_uses_real_model(client, tokens):
    import pytest
    pytest.importorskip("torch")
    pid = client.post("/patients", json={"name": "Tissue Person", "age": 58, "sex": "female"}, headers=tokens["doc1"]).json()["id"]
    r = upload(client, tokens, pid, stained_png(), scan_type="tissue")
    assert r.status_code == 201, r.text
    res = r.json()["result"]
    assert res["status"] == "analysed"
    assert res["is_placeholder"] is False
    assert res["model_version"].startswith("tissue-v3")
    assert 0.0 <= res["risk_score"] <= 1.0 and res["has_heatmap"] is True
    assert res["threshold_high"] == 0.90 and res["threshold_review"] == 0.51
    assert "not clinically validated" in res["message"]
    heat = client.get(f"/scans/{r.json()['id']}/heatmap", headers=tokens["doc1"])
    assert heat.status_code == 200 and heat.headers["content-type"] == "image/png"
    # deterministic: same image, same score
    again = upload(client, tokens, pid, stained_png(), scan_type="tissue").json()["result"]
    assert again["risk_score"] == res["risk_score"]


def test_tissue_model_rejects_grayscale_and_ct_stays_placeholder(client, tokens):
    pid = client.post("/patients", json={"name": "Guard Person", "age": 50, "sex": "male"}, headers=tokens["doc1"]).json()["id"]
    gray = upload(client, tokens, pid, png_bytes(seed=33), scan_type="tissue").json()["result"]
    assert gray["status"] == "cannot_assess" and "grayscale" in gray["message"]
    ct = upload(client, tokens, pid, png_bytes(seed=34), scan_type="ct").json()["result"]
    assert ct["is_placeholder"] is True and ct["model_version"].startswith("PLACEHOLDER")


def test_ct_demo_endpoints(client, tokens):
    import pytest
    from pathlib import Path
    if not (Path(__file__).resolve().parent.parent / "demo_ct" / "summary.json").is_file():
        pytest.skip("demo_ct data not present")
    assert client.get("/ct-demo").status_code == 401  # needs a login

    info = client.get("/ct-demo", headers=tokens["rad1"]).json()
    assert len(info["cases"]) == 4 and "LUNA16" in info["credits"]
    assert info["summary"]["thresholds"]["0.9"]["marked_nodules"] == 8
    ev = info["evaluation"]
    assert ev["n_scans"] == 24 and ev["n_marked_nodules"] == 27 and "froc" not in ev
    assert 0 < ev["sensitivity_at_false_alarms_per_scan"]["1"] <= 1 and ev["bootstrap_95_interval"]["1"][0] < ev["bootstrap_95_interval"]["1"][1]
    pic = client.get("/ct-demo/eval/froc.png", headers=tokens["doc1"])
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/png"
    assert client.get("/ct-demo/eval/froc.png").status_code == 401
    first = info["cases"][0]
    meta = client.get(f"/ct-demo/{first['case']}", headers=tokens["doc1"]).json()
    assert meta["n_slices"] == first["n_slices"] and len(meta["detections"]) == first["detections"]
    assert all(0 <= d["score"] <= 1 for d in meta["detections"])

    img = client.get(f"/ct-demo/{first['case']}/slice/0", headers=tokens["doc1"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert client.get(f"/ct-demo/{first['case']}/slice/{meta['n_slices']}", headers=tokens["doc1"]).status_code == 404

    # only strict case names are accepted: no path tricks, no unknown cases
    for bad in ("case_999", "%2e%2e", "summary.json", "case_1%2F..%2F..", "CASE_1", "case_1.jpg"):
        assert client.get(f"/ct-demo/{bad}", headers=tokens["doc1"]).status_code in (404, 422), bad
    assert client.get("/ct-demo/case_1/slice/-1", headers=tokens["doc1"]).status_code == 404


def test_model_card_lists_ct_detector_demo(client, tokens):
    mc = client.get("/model-card", headers=tokens["doc1"]).json()
    demo = mc["models"]["ct_detector_demo"]
    assert "precomputed" in demo["state"] and demo["evaluation"]["n_scans"] == 24 and "wide" in demo["caveat"]
