"""Tests for split read-only preparation and protected draft promotion gates."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from tools import release_bundle as bundle
from tools import release_promotion as promotion
from tests.test_release_bundle import SYNTHETIC_RELEASE_NOTES, write_bundle


SUBJECT_SHA = "a" * 40
OTHER_SHA = "e" * 40
TAG_SHA = "b" * 40
CI_RUN_ID = 101
CI_RUN_ATTEMPT = 2
CI_ARTIFACT_ID = 202
CI_DIGEST = "d" * 64
DRAFT_RELEASE_ID = 303
PREPARED_ARTIFACT_ID = 404
PREPARED_WORKFLOW_RUN_ID = 505
PREPARED_DIGEST = "c" * 64
PREPARED_SIZE = 456
NOTES_DIGEST = hashlib.sha256(SYNTHETIC_RELEASE_NOTES.encode("utf-8")).hexdigest()


def _run() -> dict:
    return {
        "id": CI_RUN_ID,
        "repository": {"full_name": bundle.REPOSITORY},
        "head_repository": {"full_name": bundle.REPOSITORY},
        "status": "completed",
        "conclusion": "success",
        "event": "push",
        "head_branch": bundle.DEFAULT_BRANCH,
        "head_sha": SUBJECT_SHA,
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
            "head_sha": SUBJECT_SHA,
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
        "name": bundle.RELEASE_NAME,
        "body": SYNTHETIC_RELEASE_NOTES,
        "target_commitish": SUBJECT_SHA,
        "draft": True,
        "prerelease": False,
        "published_at": None,
        "immutable": False,
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
        "size_in_bytes": PREPARED_SIZE,
        "workflow_run": {
            "id": PREPARED_WORKFLOW_RUN_ID,
            "head_branch": bundle.DEFAULT_BRANCH,
            "head_sha": SUBJECT_SHA,
        },
        "digest": f"sha256:{PREPARED_DIGEST}",
    }


class FakeApi:
    """In-memory GitHub state with optional post-download drift hooks."""

    def __init__(self, *, annotated: bool = False, nested: bool = False) -> None:
        self.annotated = annotated
        self.nested = nested
        self.master_sha = SUBJECT_SHA
        self.tag_target = SUBJECT_SHA
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
        self.get_paths: list[str] = []

    def _tag_reference(self) -> dict:
        return {
            "ref": f"refs/tags/{bundle.RELEASE_TAG}",
            "object": {
                "type": "tag" if self.annotated else "commit",
                "sha": TAG_SHA if self.annotated else self.tag_target,
            },
        }

    def get(self, path: str) -> dict:
        self.get_paths.append(path)
        run_path = f"/repos/{bundle.REPOSITORY}/actions/runs/{CI_RUN_ID}"
        if path == f"/repos/{bundle.REPOSITORY}/git/ref/heads/{bundle.DEFAULT_BRANCH}":
            return {"object": {"type": "commit", "sha": self.master_sha}}
        if path.startswith(f"/repos/{bundle.REPOSITORY}/actions/runs/") \
                and "/attempts/" not in path and not path.endswith("/artifacts?name=release-dist&per_page=100"):
            return copy.deepcopy(self.run)
        if path == f"{run_path}/attempts/{CI_RUN_ATTEMPT}/jobs?per_page=100":
            return copy.deepcopy(self.jobs)
        if path == f"{run_path}/artifacts?name={bundle.CI_ARTIFACT_NAME}&per_page=100":
            return copy.deepcopy(self.ci_artifacts)
        if path.startswith(f"/repos/{bundle.REPOSITORY}/releases/") \
                and "/assets/" not in path:
            return copy.deepcopy(self.release)
        if path == f"/repos/{bundle.REPOSITORY}/git/ref/tags/{bundle.RELEASE_TAG}":
            return self._tag_reference()
        if path == f"/repos/{bundle.REPOSITORY}/git/tags/{TAG_SHA}":
            object_type = "tag" if self.nested else "commit"
            return {"tag": bundle.RELEASE_TAG,
                    "object": {"type": object_type, "sha": self.tag_target}}
        if path.startswith(f"/repos/{bundle.REPOSITORY}/actions/artifacts/"):
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
            elif self.final_drift == "release-body":
                self.release["body"] += "misleading extra text\n"
            elif self.final_drift == "prepared-size":
                self.prepared_artifact["size_in_bytes"] += 1
        return data


def _prime_remote_assets(api: FakeApi, target: Path) -> None:
    files = bundle.verify_release_bundle(target)
    upload_url = (
        f"https://uploads.github.com/repos/{bundle.REPOSITORY}/releases/"
        f"{DRAFT_RELEASE_ID}/assets"
    )
    for name in bundle.release_asset_names():
        api.upload(upload_url, name, files[name].read_bytes())


def _inspect(api: FakeApi, target: Path, **overrides: object) -> promotion.Candidate:
    arguments = {
        "mode": bundle.DRAFT_REHEARSAL_MODE,
        "bundle_dir": target,
        "subject_sha": SUBJECT_SHA,
        "version": bundle.RELEASE_VERSION,
        "ci_run_id": CI_RUN_ID,
        "ci_run_attempt": CI_RUN_ATTEMPT,
        "ci_artifact_id": CI_ARTIFACT_ID,
        "ci_artifact_digest": CI_DIGEST,
        "draft_release_id": DRAFT_RELEASE_ID,
        "prepared_artifact_id": PREPARED_ARTIFACT_ID,
        "prepared_artifact_digest": PREPARED_DIGEST,
        "prepared_artifact_size": PREPARED_SIZE,
        "prepared_workflow_run_id": PREPARED_WORKFLOW_RUN_ID,
        "release_notes": SYNTHETIC_RELEASE_NOTES,
        "release_notes_sha256": NOTES_DIGEST,
    }
    arguments.update(overrides)
    return promotion.inspect_draft_candidate(api, **arguments)


def _upload(api: FakeApi, target: Path, **overrides: object) -> None:
    arguments = {
        "bundle_dir": target,
        "subject_sha": SUBJECT_SHA,
        "version": bundle.RELEASE_VERSION,
        "ci_run_id": CI_RUN_ID,
        "draft_release_id": DRAFT_RELEASE_ID,
        "ci_run_attempt": CI_RUN_ATTEMPT,
        "ci_artifact_id": CI_ARTIFACT_ID,
        "ci_artifact_digest": CI_DIGEST,
        "tag_object_sha": SUBJECT_SHA,
        "tag_kind": "lightweight",
        "prepared_artifact_id": PREPARED_ARTIFACT_ID,
        "prepared_artifact_digest": PREPARED_DIGEST,
        "prepared_artifact_size": PREPARED_SIZE,
        "prepared_workflow_run_id": PREPARED_WORKFLOW_RUN_ID,
        "approval": bundle.APPROVAL_VALUE,
        "release_notes": SYNTHETIC_RELEASE_NOTES,
        "release_notes_sha256": NOTES_DIGEST,
    }
    arguments.update(overrides)
    promotion.upload_draft_assets(api, **arguments)


def test_dispatch_context_binds_control_and_subject_sha():
    promotion.validate_dispatch_context(
        event_name="workflow_dispatch", repository=bundle.REPOSITORY,
        ref="refs/heads/master", ref_name="master", ref_type="branch",
        server_url="https://github.com", api_url="https://api.github.com",
        control_sha=SUBJECT_SHA, subject_sha=SUBJECT_SHA,
    )

    assert SUBJECT_SHA == "a" * 40


@pytest.mark.parametrize("field", ["ref", "control_sha", "api_url"])
def test_dispatch_context_rejects_wrong_ref_sha_or_origin(field):
    values = {
        "event_name": "workflow_dispatch",
        "repository": bundle.REPOSITORY,
        "ref": "refs/heads/master",
        "ref_name": "master",
        "ref_type": "branch",
        "server_url": "https://github.com",
        "api_url": "https://api.github.com",
        "control_sha": SUBJECT_SHA,
        "subject_sha": SUBJECT_SHA,
    }
    values[field] = {"ref": "refs/heads/feature", "control_sha": OTHER_SHA,
                     "api_url": "https://example.invalid"}[field]

    with pytest.raises(bundle.ReleaseError) as error:
        promotion.validate_dispatch_context(**values)

    assert str(error.value)


def test_prepare_inspection_never_reads_tag_or_release_endpoints():
    api = FakeApi()

    candidate = promotion.inspect_ci_candidate(
        api, subject_sha=SUBJECT_SHA, version=bundle.RELEASE_VERSION,
        ci_run_id=CI_RUN_ID,
    )

    assert candidate.ci_artifact_id == CI_ARTIFACT_ID
    assert not any("/git/ref/tags/" in path or "/releases/" in path
                   for path in api.get_paths)


def test_prepare_binds_prepared_artifact_without_release_visibility():
    api = FakeApi()

    size = promotion.inspect_prepared_artifact(
        api, artifact_id=PREPARED_ARTIFACT_ID, digest=PREPARED_DIGEST,
        workflow_run_id=PREPARED_WORKFLOW_RUN_ID, subject_sha=SUBJECT_SHA,
    )

    assert size == PREPARED_SIZE
    assert not any("/git/ref/tags/" in path or "/releases/" in path
                   for path in api.get_paths)


def test_draft_rehearsal_reads_exact_empty_draft_without_tag_or_upload(tmp_path):
    api = FakeApi()

    candidate = _inspect(api, write_bundle(tmp_path))

    assert candidate.tag_object_sha is None and candidate.asset_ids == ()
    assert not any("/git/ref/tags/" in path for path in api.get_paths)
    assert api.uploads == []


def test_dry_run_reads_empty_draft_and_binds_annotated_tag_without_upload(tmp_path):
    api = FakeApi(annotated=True)

    candidate = _inspect(
        api, write_bundle(tmp_path), mode=bundle.DRY_RUN_MODE,
    )

    assert (candidate.tag_object_sha, candidate.tag_kind) == (TAG_SHA, "annotated")
    assert api.uploads == []


def test_draft_rehearsal_succeeds_even_if_tag_endpoint_would_be_unavailable(tmp_path):
    class NoTagApi(FakeApi):
        def get(self, path: str) -> dict:
            if "/git/ref/tags/" in path:
                raise AssertionError("draft-rehearsal must not read a tag")
            return super().get(path)

    _inspect(NoTagApi(), write_bundle(tmp_path))


@pytest.mark.parametrize("mode", ["rehearsal", "unknown", "upload_draft"])
def test_protected_inspection_rejects_wrong_mode(tmp_path, mode):
    with pytest.raises(bundle.ReleaseError) as error:
        _inspect(FakeApi(), write_bundle(tmp_path), mode=mode)

    assert "protected draft mode" in str(error.value)


@pytest.mark.parametrize(
    "fault", ["id", "target", "name", "body", "state", "immutable", "nonempty"],
)
def test_read_only_draft_modes_reject_draft_metadata_or_asset_drift(tmp_path, fault):
    api = FakeApi()
    if fault == "id":
        api.release["id"] += 1
    elif fault == "target":
        api.release["target_commitish"] = "master"
    elif fault == "name":
        api.release["name"] = "Trust Meter v0.2.1 production-ready"
    elif fault == "body":
        api.release["body"] += "misleading extra text\n"
    elif fault == "state":
        api.release["draft"] = False
    elif fault == "immutable":
        api.release["immutable"] = True
    else:
        api.release["assets"] = [{"name": "partial"}]

    with pytest.raises(bundle.ReleaseError):
        _inspect(api, write_bundle(tmp_path))

    assert api.uploads == []


@pytest.mark.parametrize("fault", ["wrong", "nested"])
def test_dry_run_rejects_wrong_or_nested_tag_without_mutation(tmp_path, fault):
    api = FakeApi(annotated=fault == "nested", nested=fault == "nested")
    if fault == "wrong":
        api.tag_target = OTHER_SHA

    with pytest.raises(bundle.ReleaseError) as error:
        _inspect(api, write_bundle(tmp_path), mode=bundle.DRY_RUN_MODE)

    assert "subject" in str(error.value)
    assert api.uploads == []


@pytest.mark.parametrize(
    "binding", ["ci_run_id", "ci_run_attempt", "ci_artifact_id",
                 "ci_artifact_digest", "draft_release_id", "prepared_artifact_id",
                 "prepared_artifact_digest", "prepared_artifact_size",
                 "prepared_workflow_run_id", "release_notes_sha256"],
)
def test_protected_job_rejects_cross_job_binding_drift(tmp_path, binding):
    values = {
        "ci_run_id": CI_RUN_ID + 1,
        "ci_run_attempt": CI_RUN_ATTEMPT + 1,
        "ci_artifact_id": CI_ARTIFACT_ID + 1,
        "ci_artifact_digest": "f" * 64,
        "draft_release_id": DRAFT_RELEASE_ID + 1,
        "prepared_artifact_id": PREPARED_ARTIFACT_ID + 1,
        "prepared_artifact_digest": "f" * 64,
        "prepared_artifact_size": PREPARED_SIZE + 1,
        "prepared_workflow_run_id": PREPARED_WORKFLOW_RUN_ID + 1,
        "release_notes_sha256": "f" * 64,
    }

    with pytest.raises(bundle.ReleaseError) as error:
        _inspect(FakeApi(), write_bundle(tmp_path), **{binding: values[binding]})

    assert str(error.value)


@pytest.mark.parametrize("fault", ["ci-head", "prepared-head", "prepared-size"])
def test_protected_job_rejects_remote_artifact_drift(tmp_path, fault):
    api = FakeApi()
    if fault == "ci-head":
        api.ci_artifacts["artifacts"][0]["workflow_run"]["head_sha"] = OTHER_SHA
    elif fault == "prepared-head":
        api.prepared_artifact["workflow_run"]["head_sha"] = OTHER_SHA
    else:
        api.prepared_artifact["size_in_bytes"] += 1

    with pytest.raises(bundle.ReleaseError) as error:
        _inspect(api, write_bundle(tmp_path))

    assert str(error.value)


def test_upload_is_create_only_and_rehashes_exact_remote_bytes(tmp_path):
    api = FakeApi()

    _upload(api, write_bundle(tmp_path))

    assert api.uploads == list(bundle.release_asset_names())
    assert api.download_count == len(bundle.release_asset_names())
    assert api.release["draft"] is True


def test_upload_rejects_gate_tag_binding_drift_before_mutation(tmp_path):
    with pytest.raises(bundle.ReleaseError) as error:
        _upload(FakeApi(), write_bundle(tmp_path), tag_object_sha=OTHER_SHA)

    assert "tag bindings differ" in str(error.value)


def test_upload_rejects_gate_tag_kind_drift_before_mutation(tmp_path):
    with pytest.raises(bundle.ReleaseError) as error:
        _upload(FakeApi(), write_bundle(tmp_path), tag_kind="annotated")

    assert "tag bindings differ" in str(error.value)


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


@pytest.mark.parametrize(
    "drift", ["master", "asset-id", "release-body", "prepared-size"],
)
def test_upload_final_gate_rejects_post_download_toctou_drift(tmp_path, drift):
    api = FakeApi()
    target = write_bundle(tmp_path)
    _prime_remote_assets(api, target)
    api.final_drift = drift

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, target)

    assert str(error.value)


def test_upload_rechecks_tag_before_every_mutation(tmp_path):
    api = FakeApi()
    api.drift_tag_after_upload = True

    with pytest.raises(bundle.ReleaseError) as error:
        _upload(api, write_bundle(tmp_path))

    assert "lightweight tag" in str(error.value) or "tag binding changed" in str(error.value)
