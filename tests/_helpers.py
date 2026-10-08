"""Shared test helpers: workspace temp dirs and fake HTTP opener."""
import json
import os
import uuid
from pathlib import Path

# The DSH sandbox denies writes under %LOCALAPPDATA%\Temp to child processes,
# so tests use a temp dir outside the repo instead of tempfile defaults.
# tempfile.mkdtemp() is also avoided: os.mkdir(0o700) sets a restrictive DACL
# on Windows that the sandbox then blocks writes through; plain mkdir() works.
WORKSPACE_TMP = Path(__file__).resolve().parents[2] / ".tmp-github-publisher-tests"


def make_tempdir():
    WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)
    d = WORKSPACE_TMP / f"td-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    d.mkdir()
    return str(d)


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    """Queues responses (or Exception instances to raise); records requests."""

    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.requests = []
        self.error = error

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError("FakeOpener: no response queued")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def json_response(status, payload, headers=None):
    return FakeResponse(
        status,
        json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
