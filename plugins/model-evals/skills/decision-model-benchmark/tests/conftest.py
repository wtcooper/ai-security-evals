"""Shared fixtures: the skill root on sys.path and a mock server per test."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mock_server  # noqa: E402


@pytest.fixture
def server():
    srv = mock_server.MockServer(port=0).start()
    yield srv
    srv.stop()


@pytest.fixture
def make_server():
    """Start mock servers with custom settings; all are stopped after the test."""
    started = []

    def make(**kwargs):
        srv = mock_server.MockServer(port=0, **kwargs).start()
        started.append(srv)
        return srv

    yield make
    for srv in started:
        srv.stop()
