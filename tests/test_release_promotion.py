"""Tests for live GitHub candidate binding and draft-only promotion gates."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from tools import release_bundle as bundle
from tools import release_promotion as promotion
from tests.test_release_bundle import write_bundle


TARGET_SHA = "a" * 40
OTHER_SHA = "e" * 40
TAG_SHA = "b" * 40
CI_RUN_ID = 101
CI_RUN_ATTEMPT = 2
CI_ARTIFACT_ID = 202
CI_DIGEST = "d" * 64
DRAFT_RELEASE_ID = 303
PREPARED_ARTIFACT_ID = 404
WORKFLOW_RUN_ID = 505
PREPARED_DIGEST = "c" * 64


def _run() -> dict:
    return {
        "id": CI_RUN_ID,
        "repository": {"full_name": bundle.REPOSITORY},
        "head_repository": {"full_name": bundle.REPOSITORY},
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": bundle.DEFAULT_BRANCH,
        "head_sha": TARGET_SHA,
        "path": bundle.CI_WORKFLOW_PATH,
        "run_attempt": CI_RUN_ATTEMPT,
    }


def _jobs() -> dict:
    jobs = [
        {"name": name, "status": "completed", "conclusion": "success"}
        for name in sorted(promotion.EXPECTED_CI_JOBS)
    ]
    return {"total_count": len(jobs), "jobs": jobs}


def _ci_artifacts(*, duplicate: bool = False) -> dict:
    artifact = {
        "id": CI_ARTIFACT_ID,
        "name": bundle.CI_ARTIFACT_NAME,
        "expired": False,
        "workflow_run": {
            "id": CI_RUN_ID,
            "head_branch": bundle.DEFAULT_BRANCH,
            "head_sha": TARGET_SHA,
        },
        "digest": f"sha256:{CI_DIGEST}",
        "size_in_bytes": 123,
    }
    artifacts = [artifact, copy.deepcopy(artifact)] if duplicate else [artifact]
    return {"total_count": len(artifacts), "artifacts": artifacts}


def _release(assets: list[dict] | None = None) -> dict:
    return {
        "id": DRAFT_RELEASE_ID,
        "tag_name": bundle.RELEASE_TAG,
        "target_commitish": TARGET_SHA,
        "draft": True,
        "prerelease": False,
        "published_at": None,
        "upload_url": (
            f"https://uploads.github.com/repos/{bundle.REPOSITORY}/releases/"
            f"{DRAFT_RELEASE_ID}/assets{{?name,label}}"
        ),
        "assets": [] if assets is None else assets,
    }


def _prepared_artifact() -> dict:
    return {
        "id": PREPARED_ARTIFACT_ID,
        "name": bundle.PREPARED_ARTIFACT_NAME,
        "expired": False,
        "size_in_bytes": 456,
        "workflow_run": {
            "id": WORKFLOW_RUN_ID,
            "head_branch": bundle.DEFAULT_BRANCH,
            "head_sha": TARGET_SHA,
        },
        "digest": f"sha256:{PREPARED_DIGEST}",
    }


class FakeApi:
    """In-memory GitHub state with optional post-download drift hooks."""

    def __init__(self, *, annotated: bool = False, nested: bool = False) -> None:
        self.annotated = annotated
        self.nested = nested
        self.master_sha = TARGET_SHA
        self.tag_target = TARGET_SHA
        self.run = _run()
        self.jobs = _jobs()
        self.ci_artifacts = _ci_artifacts()
        self.release = _release()
        self.prepared_artifact = _prepared_artifact()
        self.uploads: list[str] = []
        self.downloads: dict[int, bytes] = {}
        self.download_count = 0
        self.final_drift = ""
        self.drift_tag_after_upload = False

    def _tag_reference(self) -> dict:
        return {
            "ref": f"refs/tags/{bundle.RELEASE_TAG}",
            "object": {
                "type": "tag" if self.annotated else "commit",
                "sha": TAG_SHA if self.annotated else self.tag_target,
            },
        }

    def get(self, path: str) -> dict:
        run_path = f"/repos/{bundle.REPOSITORY}/actions/runs/{CI_RUN_ID}"
        if path == f"/repos/{bundle.REPOSITORY}/git/ref/heads/{bundle.DEFAULT_BRANCH}":
            return {"object": {"type": "commit", "sha": self.master_sha}}
        if path == run_path:
            return copy.deepcopy(self.run)
        if path == f"{run_path}/attempts/{CI_RUN_ATTEMPT}/jobs?per_page=100":
            return copy.deepcopy(self.jobs)
        if path == f"{run_path}/artifacts?name={bundle.CI_ARTIFACT_NAME}&per_page=100":
            return copy.deepcopy(self.ci_artifacts)
        if path == f"/repos/{bundle.REPOSITORY}/releases/{DRAFT_RELEASE_ID}":
            return copy.deepcopy(self.release)
        if path == f"/repos/{bundle.REPOSITORY}/git/ref/tags/{bundle.RELEASE_TAG}":
            return self._tag_reference()
        if path == f"/repos/{bundle.REPOSITORY}/git/tags/{TAG_SHA}":
            object_type = "tag" if self.nested else "commit"
            return {"tag": bundle.RELEASE_TAG,
                    "object": {"type": object_type, "sha": self.tag_target}}
        if path == f"/repos/{bundle.REPOSITORY}/actions/artifacts/{PREPARED_ARTIFACT_ID}":
            return copy.deepcopy(self.prepared_artifact)
        raise AssertionError(f"unexpected API path: {path}")

    def upload(self, upload_url: str, name: str, data: bytes) -> dict:
        expected = (
            f"https://uploads.github.com/repos/{bundle.REPOSITORY}/releases/"
            f"{DRAFT_RELEASE_ID}/assets"
        )
        assert upload_url == expected and name not in self.uploads
        asset_id = 700 + len(self.uploads)
        asset = {
            "id": asset_id,
            "name": name,
            "state": "uploaded",
            "size": len(data),
            "digest": f"sha256:{hashlib.sha256(data).hexdigest()}",
            "url": (
                f"https://api.github.com/repos/{bundle.REPOSITORY}/releases/"
                f"assets/{asset_id}"
            ),
        }
        self.uploads.append(name)
        self.downloads[asset_id] = data
        self.release["assets"].append(asset)
        if self.drift_tag_after_upload:
            self.tag_target = OTHER_SHA
        return copy.deepcopy(asset)

    def download_asset(self, asset: dict) -> bytes:
        self.download_count += 1
        data = self.downloads[asset["id"]]
        if self.download_count == len(bundle.release_asset_names()):
            if self.final_drift == "master":
                self.master_sha = OTHER_SHA
            elif self.final_drift == "asset-id":
                self.release["assets"][0]["id"] += 50
        return data


def _prime_remote_assets(api: FakeApi, target: Path) -> None:
    files = bundle.verify_release_bundle(target)
    upload_url = (
        f"https://uploads.github.com/repos/{bundle.REPOSITORY}/releases/"
        f"{DRAFT_RELEASE_ID}/assets"
    )
    for name in bundle.release_asset_names():
        api.upload(upload_url, name, files[name].read_bytes())


def _upload(api: FakeApi, target: Path, **overrides: object) -> None:
    arguments = {
        "bundle_dir": target,
        "target_sha": TARGET_SHA,
        "version": bundle.RELEASE_VERSION,
        "ci_run_id": CI_RUN_ID,
        "draft_release_id": DRAFT_RELEASE_ID,
        "ci_run_attempt": CI_RUN_ATTEMPT,
        "ci_artifact_id": CI_ARTIFACT_ID,
        "ci_artifact_digest": CI_DIGEST,
        "tag_object_sha": TARGET_SHA,
        "prepared_artifact_id": PREPARED_ARTIFACT_ID,
        "prepared_artifact_digest": PREPARED_DIGEST,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "approval": bundle.APPROVAL_VALUE,
    }
    arguments.update(overrides)
    promotion.upload_draft_assets(api, **arguments)


def test_dispatch_context_binds_trusted_workflow_sha_to_master_target():
    promotion.validate_dispatch_context(
        event_name="workflow_dispatch", repository=bundle.REPOSITORY,
        ref="refs/heads/master", ref_name="master", ref_type="branch",
        server_url="https://github.com", api_url="https://api.github.com",
        workflow_sha=TARGET_SHA, target_sha=TARGET_SHA,
    )

    assert TARGET_SHA == "a" * 40


@pytest.mark.parametrize("field", ["ref", "workflow_sha", "api_url"])
def test_dispatch_context_rejects_wrong_ref_sha_or_origin(field):
    values = {
        "event_name": "workflow_dispatch",
        "repository": bundle.REPOSITORY,
        "ref": "refs/heads/master",
        "ref_name": "master",
        "ref_type": "branch",
        "server_url": "https://github.com",
        "api_url": "https://api.github.com",
        "workflow_sha": TARGET_SHA,
        "target_sha": TARGET_SHA,
    }
    values[field] = {"ref": "refs/heads/feature", "workflow_sha": OTHER_SHA,
                     "api_url": "https://example.invalid"}[field]

    with pytest.raises(bundle.ReleaseError) as error:
        promotion.validate_dispatch_context(**values)

    assert str(error.value)


def test_inspect_accepts_exact_jobs_artifact_lightweight_tag_and_empty_draft():
    candidate = promotion.inspect_candidate(
        FakeApi(), target_sha=TARGET_SHA, version=bundle.RELEASE_VERSION,
        ci_run_id=CI_RUN_ID, draft_release_id=DRAFT_RELEASE_ID,
    )

    assert candidate.tag_kind == "lightweight"
    assert candidate.ci_artifact_id == CI_ARTIFACT_ID
    assert candidate.ci_run_attempt == CI_RUN_ATTEMPT


def test_inspect_accepts_one_direct_annotated_tag():
    candidate = promotion.inspect_candidate(
        FakeApi(annotated=True), target_sha=TARGET_SHA,
        version=bundle.RELEASE_VERSION, ci_run_id=CI_RUN_ID,
        draft_release_id=DRAFT_RELEASE_ID,
    )

    assert candidate.tag_kind == "annotated" and candidate.tag_object_sha == TAG_SHA


def test_inspect_rejects_nested_annotated_tag():
    with pytest.raises(bundle.ReleaseError) as error:
        promotion.inspect_candidate(
            FakeApi(annotated=True, nested=True), target_sha=TARGET_SHA,
            version=bundle.RELEASE_VERSION, ci_run_id=CI_RUN_ID,
            draft_release_id=DRAFT_RELEASE_ID,
        )

    assert "directly to one target commit" in str(error.value)


@pytest.mark.parametrize("fault", ["missing", "failed", "renamed"])
def test_inspect_rejects_job_matrix_drift(fault):
    api = FakeApi()
    if fault == "missing":
        api.jobs["jobs"].pop()
        api.jobs["total_count"] -= 1
    elif fault == "failed":
        api.jobs["jobs"][0]["conclusion"] = "failure"
    else:
        api.jobs["jobs"][0]["name"] = "Unexpected job"

    with pytest.raises(bundle.ReleaseError) as error:
        promotion.inspect_candidate(
            api, target_sha=TARGET_SHA, version=bundle.RELEASE_VERSION,
            ci_run_id=CI_RUN_ID, draft_release_id=DRAFT_RELEASE_ID,
        )

    assert "CI job" in str(error.value) or "every exact CI job" in str(error.value)


def test_inspect_rejects_duplicate_or_wrong_bound_ci_artifact():
    api = FakeApi()
    api.ci_artifacts = _ci_artifacts(duplicate=True)

    with pytest.raises(bundle.ReleaseError) as error:
        promotion.inspect_candidate(
            api, target_sha=TARGET_SHA, version=bundle.RELEASE_VERSION,
            ci_run_id=CI_RUN_ID, draft_release_id=DRAFT_RELEASE_ID,
        )

    assert "one unique release-dist" in str(error.value)


@pytest.mark.parametrize("fault", ["master", "run", "draft-target", "nonempty"])
def test_inspect_rejects_mutable_or_inexact_candidate_state(fault):
    api = FakeApi()
    if fault == "master":
        api.master_sha = OTHER_SHA
    elif fault == "run":
        api.run["conclusion"] = "failure"
    elif fault == "draft-target":
        api.release["target_commitish"] = "master"
    else:
        api.release["assets"] = [{"name": "partial"}]

    with pytest.raises(bundle.ReleaseError) as error:
        promotion.inspect_candidate(
            api, target_sha=TARGET_SHA, version=bundle.RELEASE_VERSION,
            ci_run_id=CI_RUN_ID, draft_release_id=DRAFT_RELEASE_ID,
        )

    assert str(error.value)


def test_upload_is_create_only_and_rehashes_exact_remote_bytes(tmp_path):
    api = FakeApi()
    target = write_bundle(tmp_path)

    _upload(api, target)

    assert api.uploads == list(bundle.release_asset_names())
    assert api.download_count == len(bundle.release_asset_names())
    assert api.release["draft"] is True


@pytest.mark.parametrize("binding", ["ci_artifact_id", "ci_artifact_digest",
                                      "ci_run_attempt", "tag_object_sha"])
def test_upload_rejects_cross_job_binding_drift(tmp_path, binding):
    values = {
        "ci_artifact_id": CI_ARTIFACT_ID + 1,
        "ci_artifact_digest": "f" * 64,
        "ci_run_attempt": CI_RUN_ATTEMPT + 1,
        "tag_object_sha": OTHER_SHA,
    }

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(FakeApi(), write_bundle(tmp_path), **{binding: values[binding]})

    assert "bindings differ" in str(error.value)


def test_upload_rejects_prepared_artifact_branch_sha_or_size_drift(tmp_path):
    api = FakeApi()
    api.prepared_artifact["workflow_run"]["head_sha"] = OTHER_SHA

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, write_bundle(tmp_path))

    assert "prepared artifact branch or SHA mismatch" in str(error.value)


def test_upload_rejects_partial_existing_assets_and_requires_new_draft(tmp_path):
    api = FakeApi()
    target = write_bundle(tmp_path)
    files = bundle.verify_release_bundle(target)
    name = bundle.release_asset_names()[0]
    api.upload(
        f"https://uploads.github.com/repos/{bundle.REPOSITORY}/releases/"
        f"{DRAFT_RELEASE_ID}/assets", name, files[name].read_bytes(),
    )

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, target)

    assert "missing, partial, or contains drift" in str(error.value)


def test_upload_accepts_exact_idempotent_remote_set_without_clobber(tmp_path):
    api = FakeApi()
    target = write_bundle(tmp_path)
    _prime_remote_assets(api, target)
    initial = list(api.uploads)

    _upload(api, target)

    assert api.uploads == initial


def test_upload_rejects_remote_download_hash_mismatch(tmp_path):
    api = FakeApi()
    target = write_bundle(tmp_path)
    _prime_remote_assets(api, target)
    first_id = api.release["assets"][0]["id"]
    api.downloads[first_id] = b"remote bytes changed"

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, target)

    assert "downloaded release asset" in str(error.value)


@pytest.mark.parametrize("drift", ["master", "asset-id"])
def test_upload_final_gate_rejects_post_download_toctou_drift(tmp_path, drift):
    api = FakeApi()
    target = write_bundle(tmp_path)
    _prime_remote_assets(api, target)
    api.final_drift = drift

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, target)

    expected = {
        "master": "live master no longer matches target SHA",
        "asset-id": "remote release asset API URL mismatch",
    }[drift]
    assert expected in str(error.value)


def test_upload_rechecks_tag_before_every_mutation(tmp_path):
    api = FakeApi()
    api.drift_tag_after_upload = True

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, write_bundle(tmp_path))

    assert "lightweight tag" in str(error.value) or "tag binding changed" in str(error.value)
