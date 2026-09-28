import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["MERIDIAN_DATA"] = tempfile.mkdtemp(prefix="meridian-test-")
os.environ["SIGNING_KEY"] = "test-signing-key"
os.environ["CONNECTOR_KEY"] = "test-connector-key"

from meridian import db
from meridian.app import app
from meridian.seed import PASSWORD, seed


@pytest.fixture(scope="session")
def client():
    seed()
    with TestClient(app) as test_client:
        yield test_client
    import shutil
    shutil.rmtree(Path(os.environ["MERIDIAN_DATA"]))


@pytest.fixture
def auth(client):
    def login(email="elliot@atlas.test", workspace="atlas"):
        response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"], "X-Workspace": workspace}
    return login


@pytest.fixture(autouse=True)
def clear_cache(client):
    db.execute("DELETE FROM retrieval_cache")
