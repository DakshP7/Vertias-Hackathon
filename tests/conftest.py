import os
import tempfile
from pathlib import Path

# Point the app at a throwaway DB and upload folder BEFORE it is imported.
_tmp = tempfile.mkdtemp(prefix="celliq_test_")
os.environ["CELLIQ_DB"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["CELLIQ_UPLOADS"] = str(Path(_tmp) / "uploads")
os.environ["CELLIQ_JWT_SECRET"] = "test-secret-not-for-real-use-0123456789abcdef"
os.environ["GEMINI_API_KEY"] = ""  # tests must never call Gemini
os.environ["GMAIL_ADDRESS"] = ""  # tests must never send real email
os.environ["GMAIL_APP_PASSWORD"] = ""
os.environ["CELLIQ_OUTBOX"] = str(Path(_tmp) / "outbox")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from api.seed import DEMO_USERS, seed  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        seed()
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for username, _, _, pw in DEMO_USERS:
        r = client.post("/auth/login", json={"username": username, "password": pw})
        assert r.status_code == 200, r.text
        out[username] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return out
