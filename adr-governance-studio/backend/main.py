import os
import json
import hmac
import hashlib
import requests
from pathlib import Path
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Request, Header, HTTPException, status, Depends
from pydantic import BaseModel

app = FastAPI(title="ADR Governance API", version="1.0.0")

# Secret key configured for GitHub Webhooks (defaults to local dev key)
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "local_adr_dev_secret_123")
# Optional GitHub token for fetching PR file contents/diffs from GitHub REST API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


# ---------------------------------------------------------------------------
# Governance Policy Loader
# ---------------------------------------------------------------------------
def load_governance_policy() -> Dict[str, Any]:
    """Locates and loads .adr/governance.json relative to project root."""
    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent  # C:\Repository\adr-governance-studio
    policy_path = repo_root / ".adr" / "governance.json"

    if not policy_path.exists():
        return {
            "version": "1.0",
            "requiredFields": ["id", "title", "status"],
            "allowedStatuses": ["Proposed", "Accepted", "Rejected", "Superseded", "Deprecated"],
            "rules": []
        }

    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse governance policy at {policy_path}: {str(e)}"
        )


# ---------------------------------------------------------------------------
# HMAC Signature Verification
# ---------------------------------------------------------------------------
async def verify_github_signature(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """Validates incoming GitHub Webhook X-Hub-Signature-256 header."""
    if not x_hub_signature_256:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header"
        )

    if not x_hub_signature_256.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature format"
        )

    raw_body = await request.body()
    expected_hmac = hmac.new(
        key=WEBHOOK_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    expected_signature = f"sha256={expected_hmac}"

    if not hmac.compare_digest(expected_signature, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HMAC signature verification failed"
        )


# ---------------------------------------------------------------------------
# Helper Linter Function
# ---------------------------------------------------------------------------
def lint_adr_content(content: str, policy: Dict[str, Any], required_tags: Optional[List[str]] = None) -> List[str]:
    """Internal helper to validate raw ADR Markdown against policy rules."""
    errors = []
    required_fields = policy.get("requiredFields", ["id", "title", "status"])
    allowed_statuses = policy.get("allowedStatuses", [])
    custom_rules = policy.get("rules", [])

    lines = content.splitlines()

    # 1. Frontmatter Required Fields Check
    for field in required_fields:
        field_pattern = f"{field}:"
        if not any(line.strip().lower().startswith(field_pattern.lower()) for line in lines):
            errors.append(f"Missing required frontmatter key: '{field}'")

    # 2. Status Lifecycle Validation
    if allowed_statuses:
        status_line = next((line for line in lines if line.strip().lower().startswith("status:")), None)
        if status_line:
            status_value = status_line.split(":", 1)[1].strip()
            if status_value not in allowed_statuses:
                errors.append(
                    f"Invalid status '{status_value}'. Must be one of: {', '.join(allowed_statuses)}"
                )

    # 3. Custom Governance Rule Checks
    for rule in custom_rules:
        req_section = rule.get("requiredSection")
        if req_section:
            section_header = f"## {req_section}".lower()
            if not any(line.strip().lower() == section_header for line in lines):
                errors.append(f"[{rule.get('id', 'RULE')}] Missing required section header: '## {req_section}'")

    # 4. Mandatory Tag Check
    if required_tags:
        tags_line = next((line for line in lines if line.strip().lower().startswith("tags:")), None)
        if not tags_line:
            errors.append("Missing required 'tags:' key in frontmatter")
        else:
            for tag in required_tags:
                if tag.lower() not in tags_line.lower():
                    errors.append(f"Missing required tag: '{tag}'")

    return errors


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------
class LintRequest(BaseModel):
    content: str
    required_tags: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check():
    policy = load_governance_policy()
    return {
        "status": "ok",
        "service": "ADR Governance Engine",
        "governance_loaded": True,
        "policy_version": policy.get("version", "unknown")
    }


@app.post("/v1/lint")
def lint_adr(req: LintRequest):
    """Direct API endpoint for linting single ADR Markdown content."""
    policy = load_governance_policy()
    errors = lint_adr_content(req.content, policy, req.required_tags)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "policy_applied": policy.get("version", "1.0")
    }


@app.post("/v1/webhooks/github")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    _: None = Depends(verify_github_signature)
):
    """Processes incoming GitHub pull_request webhooks and lints modified ADRs."""
    payload = await request.json()

    if x_github_event != "pull_request":
        return {"message": f"Event '{x_github_event}' ignored"}

    action = payload.get("action")
    pr_number = payload.get("number")
    pull_request = payload.get("pull_request", {})

    # Execute linting on relevant PR lifecycle actions
    if action not in ["opened", "synchronize", "reopened"]:
        return {"message": f"PR #{pr_number} action '{action}' skipped"}

    policy = load_governance_policy()
    repo_root = Path(__file__).resolve().parent.parent
    
    lint_results = []
    
    # 1. Fetch changed files list from payload or GitHub REST API
    # Option A: Check if files array is supplied directly in payload or fetch from PR URL
    pr_files_url = pull_request.get("url", "") + "/files" if pull_request.get("url") else ""
    changed_files = []

    if pr_files_url and GITHUB_TOKEN:
        try:
            headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
            res = requests.get(pr_files_url, headers=headers, timeout=5)
            if res.status_code == 200:
                changed_files = [f.get("filename") for f in res.json()]
        except Exception:
            pass  # Fallback to local filesystem scanning if API fetch fails

    # Option B: Fallback local disk scan for changed files matching .adr/decisions/
    decisions_dir = repo_root / ".adr" / "decisions"
    
    if decisions_dir.exists():
        for adr_file in decisions_dir.glob("*.md"):
            rel_path = f".adr/decisions/{adr_file.name}"
            # If changed_files was successfully fetched, filter; otherwise scan local file system
            if not changed_files or rel_path in changed_files:
                try:
                    with open(adr_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    file_errors = lint_adr_content(content, policy)
                    lint_results.append({
                        "file": rel_path,
                        "valid": len(file_errors) == 0,
                        "errors": file_errors
                    })
                except Exception as e:
                    lint_results.append({
                        "file": rel_path,
                        "valid": False,
                        "errors": [f"Failed to read file: {str(e)}"]
                    })

    all_passed = all(res["valid"] for res in lint_results) if lint_results else True

    return {
        "message": f"Processed PR #{pr_number} action '{action}'",
        "adrs_evaluated": len(lint_results),
        "compliant": all_passed,
        "results": lint_results
    }