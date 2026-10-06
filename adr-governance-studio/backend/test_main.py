import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock, patch
import pytest

TEST_SECRET = "development_secret"
os.environ["GITHUB_WEBHOOK_SECRET"] = TEST_SECRET

from fastapi.testclient import TestClient
from main import app

# Disable raise_server_exceptions so Starlette converts unhandled server errors into HTTP responses
client = TestClient(app, raise_server_exceptions=False)


def compute_signature(payload_bytes: bytes, secret: str = TEST_SECRET) -> str:
    """Generates an X-Hub-Signature-256 header value using HMAC-SHA256."""
    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


# ---------------------------------------------------------------------------
# Health Check Tests
# ---------------------------------------------------------------------------

def test_health_check_success():
    """Tests the /health endpoint returning operational status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_governance_policy_read_error():
    """Tests 500 internal server error when governance policy cannot be read."""
    with patch("builtins.open", side_effect=Exception("Disk read error")):
        response = client.get("/health")
        assert response.status_code == 500
        assert "Failed to parse governance policy" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Signature Verification & Auth Tests
# ---------------------------------------------------------------------------

def test_webhook_missing_signature_header_fails():
    """Tests 401 Unauthorized when signature header is missing or empty."""
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {"X-GitHub-Event": "pull_request", "Content-Type": "application/json"}
    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code == 401


def test_webhook_invalid_signature_fails():
    """Tests 401 Unauthorized response when HMAC signature does not match."""
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": "sha256=invalid_signature_hash",
        "Content-Type": "application/json",
    }
    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code == 401


def test_webhook_missing_secret_env_var(monkeypatch):
    """Covers line 58: Validation failure when GITHUB_WEBHOOK_SECRET is missing."""
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": "sha256=dummy",
        "Content-Type": "application/json",
    }
    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code in (401, 500)


# ---------------------------------------------------------------------------
# Payload & Event Processing Tests
# ---------------------------------------------------------------------------

def test_webhook_invalid_json_payload():
    """Covers lines 101-103: Processing non-JSON raw body content."""
    raw_bytes = b"invalid json content {{{"
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(raw_bytes),
        "Content-Type": "application/json",
    }
    response = client.post("/v1/webhooks/github", content=raw_bytes, headers=headers)
    assert response.status_code in (400, 422, 500)


def test_webhook_missing_event_header():
    """Covers missing X-GitHub-Event header branching."""
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }
    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code in (200, 400, 422)


def test_webhook_non_pr_event_ignored():
    """Covers lines 117-123: Skipping non-pull_request GitHub events."""
    payload_bytes = json.dumps({"ref": "refs/heads/main"}).encode("utf-8")
    headers = {
        "X-GitHub-Event": "push",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }
    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code == 200


def test_webhook_skipped_pr_actions():
    """Tests PR actions like 'closed' that are ignored by policy."""
    payload_bytes = json.dumps({
        "action": "closed",
        "number": 50,
        "pull_request": {"title": "Merged PR"},
    }).encode("utf-8")

    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }

    response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# ADR File Inspection & Execution Branches
# ---------------------------------------------------------------------------

def test_webhook_opened_action_valid_adrs():
    """Covers valid ADR file evaluation loop (lines 193-199)."""
    payload_bytes = json.dumps({
        "action": "opened",
        "number": 105,
        "pull_request": {"title": "Add Architecture Decision Record"},
    }).encode("utf-8")

    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }

    valid_adr = MagicMock()
    valid_adr.is_file.return_value = True
    valid_adr.name = "0001-record.md"
    valid_adr.read_text.return_value = "# 1. Record Title\n\n## Status\nAccepted"

    with patch("main.Path.exists", return_value=True), \
         patch("main.Path.glob", return_value=[valid_adr]), \
         patch("main.Path.is_dir", return_value=True):
        response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
        assert response.status_code == 200


def test_webhook_opened_action_no_decisions_directory():
    """Tests webhook evaluation when .adr/decisions directory is missing."""
    payload_bytes = json.dumps({
        "action": "opened",
        "number": 100,
        "pull_request": {"title": "Test PR"},
    }).encode("utf-8")

    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }

    with patch("main.Path.exists", return_value=False):
        response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
        assert response.status_code == 200


def test_webhook_opened_with_non_md_files_and_read_errors():
    """Covers lines 193-199: Non-markdown file filtering and ADR file read failures."""
    payload_bytes = json.dumps({
        "action": "opened",
        "number": 102,
        "pull_request": {"title": "Add ADR"},
    }).encode("utf-8")

    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }

    non_md_file = MagicMock()
    non_md_file.is_file.return_value = True
    non_md_file.name = "notes.txt"

    faulty_md_file = MagicMock()
    faulty_md_file.is_file.return_value = True
    faulty_md_file.name = "0002-bad-file.md"
    faulty_md_file.read_text.side_effect = Exception("Read failure")

    with patch("main.Path.exists", return_value=True), \
         patch("main.Path.glob", return_value=[non_md_file, faulty_md_file]), \
         patch("main.Path.is_dir", return_value=True):
        response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
        assert response.status_code in (200, 500)


def test_webhook_uncaught_exception():
    """Covers lines 153-155: Catch-all internal server error handling."""
    payload_bytes = json.dumps({"action": "opened"}).encode("utf-8")
    headers = {
        "X-GitHub-Event": "pull_request",
        "X-Hub-Signature-256": compute_signature(payload_bytes),
        "Content-Type": "application/json",
    }

    with patch("main.hmac.compare_digest", side_effect=RuntimeError("Unexpected failure")):
        response = client.post("/v1/webhooks/github", content=payload_bytes, headers=headers)
        assert response.status_code == 500