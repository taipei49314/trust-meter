"""Tests for the isolated GitHub API client and Actions control surface."""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from tools import github_release as control
from tools import release_bundle as bundle


class _Response:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._stream = io.BytesIO(data)
        self.status = status

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _AssetRedirectOpener:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if len(self.requests) == 1:
            location = "https://release-assets.githubusercontent.com/exact/object"
            raise urllib.error.HTTPError(
                request.full_url, 302, "Found", {"Location": location}, None,
            )
        return _Response(self.body)


class _RedirectingJsonOpener:
    def open(self, request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 302, "Found",
            {"Location": "https://example.invalid/token-sink"}, None,
        )


class _RejectedJsonOpener:
    def open(self, request, timeout):
        body = (
            b'{"message":"Resource not accessible by integration",'
            b'"documentation_url":"https://docs.example.invalid/private-body"}'
        )
        headers = {"X-Accepted-GitHub-Permissions": "contents=write"}
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", headers, io.BytesIO(body),
        )


class _WhitespaceTokenEchoOpener:
    def __init__(self, token: str) -> None:
        self.token = token

    def open(self, request, timeout):
        normalized = " ".join(self.token.split())
        body = json_bytes({"message": f"prefix {self.token} suffix"})
        headers = {"X-Accepted-GitHub-Permissions": f"prefix {normalized} suffix"}
        raise urllib.error.HTTPError(
            request.full_url, 403, "Forbidden", headers, io.BytesIO(body),
        )


def json_bytes(payload: dict) -> bytes:
    """Encode a small synthetic GitHub response without non-stdlib fixtures."""
    import json

    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _write_bundle(root: Path) -> Path:
    target = root / "release-bundle"
    assets = target / "release-assets"
    controls = target / "control"
    assets.mkdir(parents=True)
    controls.mkdir()
    wheel, sdist, schema, checksum = bundle.release_asset_names()
    payload = {wheel: b"wheel\n", sdist: b"sdist\n", schema: b"{}\n"}
    for name, data in payload.items():
        (assets / name).write_bytes(data)
    ledger = "".join(
        f"{hashlib.sha256(payload[name]).hexdigest()}  {name}\n"
        for name in sorted(payload)
    )
    (assets / checksum).write_text(ledger, encoding="ascii", newline="\n")
    for name in bundle.CONTROL_SCRIPT_NAMES:
        (controls / name).write_text("# control\n", encoding="utf-8")
    (controls / bundle.RELEASE_NOTES_NAME).write_text(
        "# Trust Meter v0.2.1\n\nSynthetic release notes.\n",
        encoding="utf-8", newline="\n",
    )
    return target


@pytest.mark.parametrize("url", [
    "http://api.github.com/path",
    "https://example.invalid/path",
    "https://api.github.com:444/path",
    "https://user@api.github.com/path",
])
def test_strict_url_rejects_noncanonical_origins(url):
    with pytest.raises(bundle.ReleaseError) as error:
        control._strict_url(url, {bundle.GITHUB_API_HOST})

    assert "GitHub URL" in str(error.value)


def test_json_api_never_follows_authenticated_redirect():
    api = control.GitHubApi("bounded-token", "https://api.github.com")
    api._opener = _RedirectingJsonOpener()

    with pytest.raises(bundle.ReleaseError) as error:
        api.get(f"/repos/{bundle.REPOSITORY}/releases/1")

    assert "status=302" in str(error.value)


def test_http_error_is_safe_bounded_and_actionable_without_token_or_body():
    token = "secret-token-that-must-never-appear"
    api = control.GitHubApi(token, "https://api.github.com")
    api._opener = _RejectedJsonOpener()

    with pytest.raises(bundle.ReleaseError) as error:
        api.get(f"/repos/{bundle.REPOSITORY}/releases/371228377")

    message = str(error.value)
    assert "method=GET" in message
    assert f"path=/repos/{bundle.REPOSITORY}/releases/371228377" in message
    assert "status=403" in message
    assert "Resource not accessible by integration" in message
    assert "accepted_permissions='contents=write'" in message
    assert token not in message and "documentation_url" not in message


@pytest.mark.parametrize("token", ["secret  token", "s" * 300])
def test_http_error_redacts_raw_and_normalized_token_before_formatting(token):
    normalized = " ".join(token.split())
    api = control.GitHubApi(token, "https://api.github.com")
    api._opener = _WhitespaceTokenEchoOpener(token)

    with pytest.raises(bundle.ReleaseError) as error:
        api.get(f"/repos/{bundle.REPOSITORY}/releases/371228377")

    message = str(error.value)
    assert token not in message
    assert normalized not in message
    assert token[:64] not in message
    assert message.count("<redacted>") == 2


def test_asset_redirect_strips_authorization_and_rejects_second_redirect():
    api = control.GitHubApi("bounded-token", "https://api.github.com")
    opener = _AssetRedirectOpener(b"exact remote bytes")
    api._opener = opener

    downloaded = api.download_asset({
        "url": f"https://api.github.com/repos/{bundle.REPOSITORY}/releases/assets/7",
    })

    assert downloaded == b"exact remote bytes"
    assert opener.requests[0].get_header("Authorization") == "Bearer bounded-token"
    assert opener.requests[1].get_header("Authorization") is None


def test_isolated_control_script_can_verify_a_prepared_bundle(tmp_path):
    target = _write_bundle(tmp_path)

    result = subprocess.run(
        [sys.executable, "-I", "tools/github_release.py", "verify-bundle",
         "--bundle-dir", str(target), "--version", bundle.RELEASE_VERSION],
        text=True, capture_output=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "verified exact release bundle" in result.stdout


def test_release_workflow_is_dispatch_only_promotion_not_rebuild():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow and "release.published" not in workflow
    assert "draft-rehearsal" in workflow and "inspect-draft" in workflow
    assert "python -m build" not in workflow and "twine" not in workflow.lower()
    assert "pypi" not in workflow.lower() and "--clobber" not in workflow
    assert "environment:\n      name: github-release" in workflow
    assert "READY_FOR_HUMAN_PUBLICATION" in workflow
    assert "python -I" in workflow


def test_prepare_job_is_read_only_and_never_reads_draft_or_tag_state():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    prepare_job = workflow.split("  prepare:", 1)[1].split("  release-gate:", 1)[0]

    assert "actions: read" in prepare_job and "contents: read" in prepare_job
    assert "contents: write" not in prepare_job
    assert "inspect-ci" in prepare_job and "inspect-prepared" in prepare_job
    assert "inspect-draft" not in prepare_job
    assert "DRAFT_RELEASE_ID" not in prepare_job
    assert "--draft-release-id" not in prepare_job
    assert "--tag-object-sha" not in prepare_job


def test_all_private_draft_modes_share_protected_write_scoped_job_without_checkout():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    gate_job = workflow.split("  release-gate:", 1)[1]

    assert "if: inputs.mode != 'rehearsal'" in gate_job
    assert "environment:\n      name: github-release" in gate_job
    assert "contents: write" in gate_job and "actions: read" in gate_job
    assert "actions/checkout@" not in gate_job
    assert "--mode \"$RELEASE_MODE\"" in gate_job
    assert "if: inputs.mode == 'upload-draft'" in gate_job


def test_approval_secret_is_mapped_only_in_upload_step():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    secret = "${{ secrets.TRUST_METER_RELEASE_APPROVAL }}"
    upload_step = workflow.split(
        "      - name: Upload exact assets and read them back while release stays draft", 1,
    )[1].split("      - name: Record read-only protected gate", 1)[0]

    assert workflow.count(secret) == 1
    assert secret in upload_step
    assert secret not in workflow.split(
        "      - name: Upload exact assets and read them back while release stays draft", 1,
    )[0]


def test_release_workflow_rebinds_all_cross_job_subject_and_artifact_fields():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    for value in (
        "--control-sha \"$CONTROL_SHA\"", "--subject-sha \"$SUBJECT_SHA\"",
        "--ci-run-attempt \"$BOUND_CI_RUN_ATTEMPT\"",
        "--ci-artifact-id \"$BOUND_CI_ARTIFACT_ID\"",
        "--ci-artifact-digest \"$BOUND_CI_ARTIFACT_DIGEST\"",
        "--prepared-artifact-id \"$PREPARED_ARTIFACT_ID\"",
        "--prepared-artifact-digest \"$PREPARED_ARTIFACT_DIGEST\"",
        "--prepared-artifact-size \"$PREPARED_ARTIFACT_SIZE\"",
        "--prepared-workflow-run-id \"$PREPARED_WORKFLOW_RUN_ID\"",
        "--release-notes-sha256 \"$BOUND_RELEASE_NOTES_SHA256\"",
        "--draft-release-id \"$DRAFT_RELEASE_ID\"",
        "--release-notes release-bundle/control/RELEASE_NOTES-v0.2.1.md",
    ):
        assert value in workflow
    assert "--tag-object-sha \"$BOUND_TAG_OBJECT_SHA\"" in workflow
    assert "--tag-kind \"$BOUND_TAG_KIND\"" in workflow


def test_release_workflow_has_full_sha_actions_and_node24_artifact_pins():
    workflows = "\n".join(
        Path(name).read_text(encoding="utf-8")
        for name in (".github/workflows/trust.yml", ".github/workflows/release.yml")
    )
    refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", workflows)

    assert refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs)
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflows
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in workflows
    assert "digest-mismatch: error" in workflows
