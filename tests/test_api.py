import io

import numpy as np
from PIL import Image


def png_bytes(size=128, seed=0, blank=False) -> bytes:
    rng = np.random.default_rng(seed)
    arr = np.zeros((size, size), dtype="uint8") if blank else rng.integers(0, 255, (size, size), dtype="uint8")
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def upload(client, tokens, patient_id, data, scan_type="ct", who="rad1", name="scan.png"):
    return client.post(f"/patients/{patient_id}/scans", headers=tokens[who],
                       data={"scan_type": scan_type}, files={"file": (name, data, "image/png")})


def test_builtin_ui_served_with_csp(client):
    r = client.get("/app/")
    assert r.status_code == 200 and "CellIQ" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/", follow_redirects=False).headers["location"] == "/app/"


# ---------- auth ----------
def test_health_and_disclaimer_header(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "X-CellIQ-Disclaimer" in r.headers


def test_login_wrong_password(client):
    r = client.post("/auth/login", json={"username": "doc1", "password": "wrong"})
    assert r.status_code == 401


def test_requires_token(client):
    assert client.get("/patients").status_code == 401
    assert client.get("/patients", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_me(client, tokens):
    assert client.get("/auth/me", headers=tokens["doc1"]).json()["role"] == "doctor"


# ---------- patients ----------
def test_patient_crud_and_roles(client, tokens):
    body = {"name": "Test Person", "age": 55, "sex": "female", "smoking_status": "former", "pack_years": 10}
    assert client.post("/patients", json=body, headers=tokens["admin"]).status_code == 403
    r = client.post("/patients", json=body, headers=tokens["doc1"])
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["display_id"] == f"CIQ-{pid:04d}"
    assert r.json()["is_demo"] is True

    body["age"] = 56
    assert client.put(f"/patients/{pid}", json=body, headers=tokens["rad1"]).json()["age"] == 56
    assert client.get(f"/patients/{pid}", headers=tokens["admin"]).json()["status"] == "New"


def test_patient_validation(client, tokens):
    bad = {"name": "", "age": 500, "sex": "robot"}
    assert client.post("/patients", json=bad, headers=tokens["doc1"]).status_code == 422


def test_search_filter(client, tokens):
    r = client.get("/patients", params={"q": "Demo Patient A"}, headers=tokens["doc2"])
    assert r.status_code == 200 and len(r.json()) == 1
    pid = r.json()[0]["id"]
    r = client.get("/patients", params={"q": f"CIQ-{pid:04d}"}, headers=tokens["doc2"])
    assert [p["id"] for p in r.json()] == [pid]


def test_visits(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    r = client.post(f"/patients/{pid}/visits", json={"visit_date": "2026-11-05", "reason": "Follow-up"},
                    headers=tokens["doc1"])
    assert r.status_code == 201
    assert client.post(f"/patients/{pid}/visits", json={"visit_date": "5 Nov", "reason": "x"},
                       headers=tokens["doc1"]).status_code == 422


# ---------- scans ----------
def test_only_radiologist_can_upload(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    assert upload(client, tokens, pid, png_bytes(), who="doc1").status_code == 403
    assert upload(client, tokens, pid, png_bytes(), who="admin").status_code == 403


def test_upload_and_result(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    r = upload(client, tokens, pid, png_bytes(seed=1), scan_type="ct")
    assert r.status_code == 201, r.text
    scan = r.json()
    res = scan["result"]
    assert res["status"] == "analysed"
    assert res["is_placeholder"] is True
    assert 0 <= res["risk_score"] <= 1
    assert res["priority"] in {"HIGH PRIORITY", "PRIORITY REVIEW", "ROUTINE REVIEW"}
    assert scan["disclaimer"]

    # any doctor can view the images
    img = client.get(f"/scans/{scan['id']}/image", headers=tokens["doc2"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    heat = client.get(f"/scans/{scan['id']}/heatmap", headers=tokens["doc2"])
    assert heat.status_code == 200
    assert client.get(f"/scans/{scan['id']}/image").status_code == 401  # no token

    # same input -> same placeholder output (deterministic)
    again = upload(client, tokens, pid, png_bytes(seed=1), scan_type="ct").json()["result"]
    assert again["risk_score"] == res["risk_score"]


def test_cannot_assess_blank_image(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    res = upload(client, tokens, pid, png_bytes(blank=True)).json()["result"]
    assert res["status"] == "cannot_assess" and res["risk_score"] is None and not res["has_heatmap"]


def test_rejects_bad_files(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    assert upload(client, tokens, pid, b"not an image at all").status_code == 400
    assert upload(client, tokens, pid, b"").status_code == 400
    gif = io.BytesIO()
    Image.new("RGB", (80, 80)).save(gif, format="GIF")
    assert upload(client, tokens, pid, gif.getvalue()).status_code == 400
    r = client.post(f"/patients/{pid}/scans", headers=tokens["rad1"], data={"scan_type": "xray"},
                    files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 422


def test_unknown_patient(client, tokens):
    assert upload(client, tokens, 999999, png_bytes()).status_code == 404


def test_risk_sorted_worklist(client, tokens):
    items = client.get("/patients", params={"sort": "risk"}, headers=tokens["doc1"]).json()
    scored = [i["highest_risk"] for i in items if i["highest_risk"] is not None]
    assert scored == sorted(scored, reverse=True)
    first_none = next((k for k, i in enumerate(items) if i["highest_risk"] is None), len(items))
    assert all(i["highest_risk"] is None for i in items[first_none:])  # unscored patients last


# ---------- notes ----------
def test_notes_shared_between_doctors(client, tokens):
    pid = client.get("/patients", headers=tokens["doc1"]).json()[0]["id"]
    assert client.post(f"/patients/{pid}/notes", json={"text": "Looks suspicious, recheck."},
                       headers=tokens["doc1"]).status_code == 201
    assert client.post(f"/patients/{pid}/notes", json={"text": "Agree with Dr. Shah."},
                       headers=tokens["doc2"]).status_code == 201
    notes = client.get(f"/patients/{pid}/notes", headers=tokens["rad1"]).json()
    authors = {n["author_name"] for n in notes}
    assert "Dr. Vikram Shah" in authors and "Dr. Meera Iyer" in authors
    assert client.post(f"/patients/{pid}/notes", json={"text": "hi"}, headers=tokens["admin"]).status_code == 403
    assert client.post(f"/patients/{pid}/notes", json={"text": ""}, headers=tokens["doc1"]).status_code == 422


def test_note_scan_must_belong_to_patient(client, tokens):
    pats = client.get("/patients", headers=tokens["doc1"]).json()
    a, b = pats[0]["id"], pats[1]["id"]
    scan_id = upload(client, tokens, a, png_bytes(seed=7)).json()["id"]
    r = client.post(f"/patients/{b}/notes", json={"text": "x", "scan_id": scan_id}, headers=tokens["doc1"])
    assert r.status_code == 400


# ---------- reports ----------
def test_report_flow(client, tokens):
    body = {"name": "Report Person", "age": 60, "sex": "male", "symptoms": "cough"}
    pid = client.post("/patients", json=body, headers=tokens["doc1"]).json()["id"]

    # no scans yet
    assert client.post(f"/patients/{pid}/report", headers=tokens["doc1"]).status_code == 400
    upload(client, tokens, pid, png_bytes(seed=21))
    client.post(f"/patients/{pid}/notes", json={"text": "Report Person to be rescanned."}, headers=tokens["doc1"])

    # only doctors generate/approve
    assert client.post(f"/patients/{pid}/report", headers=tokens["rad1"]).status_code == 403
    r = client.post(f"/patients/{pid}/report", headers=tokens["doc1"])
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["status"] == "draft" and rep["source"] == "template" and rep["final_text"] is None
    assert "demonstration" in rep["draft_text"].lower()  # placeholder results are labelled

    # PDF blocked until approved
    assert client.get(f"/reports/{rep['id']}/pdf", headers=tokens["doc1"]).status_code == 409

    edited = client.put(f"/reports/{rep['id']}", json={"draft_text": rep["draft_text"] + "\nEdited."},
                        headers=tokens["doc2"])
    assert edited.status_code == 200
    assert client.put(f"/reports/{rep['id']}/approve", headers=tokens["rad1"]).status_code == 403
    ok = client.put(f"/reports/{rep['id']}/approve", headers=tokens["doc2"])
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    assert "research and educational prototype" in ok.json()["final_text"]
    assert client.put(f"/reports/{rep['id']}/approve", headers=tokens["doc1"]).status_code == 409
    assert client.put(f"/reports/{rep['id']}", json={"draft_text": "x"}, headers=tokens["doc1"]).status_code == 409

    pdf = client.get(f"/reports/{rep['id']}/pdf", headers=tokens["doc1"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get(f"/patients/{pid}", headers=tokens["doc1"]).json()["status"] == "Report ready"


def test_gemini_input_is_scrubbed():
    from api.models import Note, Patient
    from api.services.report_service import build_findings

    p = Patient(id=5, name="Jane Quill", age=50, sex="female", contact="jane@example.com",
                symptoms="Jane has a cough", created_by=1)
    n = Note(patient_id=5, author_id=1, text="Call Jane Quill on +91 98765 43210 or jane@example.com re CIQ-0005")
    text = build_findings(p, [], [n])
    for secret in ("Jane", "Quill", "98765", "jane@example.com", "CIQ-0005"):
        assert secret not in text, f"leaked: {secret}"


# ---------- audit / meta ----------
def test_audit_log_access_and_content(client, tokens):
    assert client.get("/audit", headers=tokens["rad1"]).status_code == 403
    log = client.get("/audit", params={"limit": 500}, headers=tokens["doc1"]).json()
    actions = {e["action"] for e in log}
    assert {"login", "login_failed", "upload_scan", "add_note"} <= actions


def test_model_card(client, tokens):
    mc = client.get("/model-card", headers=tokens["doc1"]).json()
    assert mc["status"] == "tissue_trained_ct_placeholder"
    assert mc["models"]["tissue"]["measured"]["n_test"] == 1711
    assert "placeholder" in mc["models"]["ct"]["state"]
    mt = client.get("/metrics", headers=tokens["doc1"]).json()
    assert mt["status"] == "tissue_only" and mt["tissue"]["test_accuracy"] > 0.9 and mt["ct"] is None
