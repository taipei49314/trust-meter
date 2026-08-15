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
    for name in bundle.CONTROL_NAMES:
        (controls / name).write_text("# control\n", encoding="utf-8")
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

    assert "status 302" in str(error.value)


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


def test_release_workflow_is_dispatch_only_promote_not_rebuild():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow and "release.published" not in workflow
    assert "python -m build" not in workflow and "twine" not in workflow.lower()
    assert "pypi" not in workflow.lower() and "--clobber" not in workflow
    assert "environment:\n      name: github-release" in workflow
    assert "READY_FOR_HUMAN_PUBLICATION" in workflow
    assert "python -I" in workflow


def test_release_workflow_has_full_sha_actions_and_minimal_write_scope():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", workflow)
    upload_job = workflow.split("  upload-draft:", 1)[1]

    assert refs and all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs)
    assert "permissions: {}" in workflow
    assert "contents: write" not in workflow.split("  upload-draft:", 1)[0]
    assert "actions/checkout@" not in upload_job
    assert "contents: write" in upload_job and "actions: read" in upload_job


def test_release_workflow_carries_exact_prepare_bindings_into_upload():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "ci_artifact_id: ${{ steps.inspect.outputs.ci_artifact_id }}" in workflow
    assert "ci_artifact_digest: ${{ steps.inspect.outputs.ci_artifact_digest }}" in workflow
    assert "tag_object_sha: ${{ steps.inspect.outputs.tag_object_sha }}" in workflow
    assert "--ci-run-attempt \"$BOUND_CI_RUN_ATTEMPT\"" in workflow
    assert "--prepared-artifact-digest \"$PREPARED_ARTIFACT_DIGEST\"" in workflow


def test_ci_artifact_boundary_uses_verified_node24_action_pins():
    workflows = "\n".join(
        Path(name).read_text(encoding="utf-8")
        for name in (".github/workflows/trust.yml", ".github/workflows/release.yml")
    )

    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflows
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in workflows
    assert "digest-mismatch: error" in workflows
