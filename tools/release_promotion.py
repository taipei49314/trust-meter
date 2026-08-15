"""Bind and promote a verified Trust Meter artifact to one draft release."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

try:
    from tools.release_bundle import (
        APPROVAL_VALUE,
        CI_ARTIFACT_NAME,
        CI_WORKFLOW_PATH,
        DEFAULT_BRANCH,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        PREPARED_ARTIFACT_NAME,
        RELEASE_NAME,
        RELEASE_TAG,
        RELEASE_VERSION,
        REPOSITORY,
        ReleaseError,
        exact_sha,
        exact_sha256,
        exact_release_notes,
        exact_version,
        github_origin,
        positive_integer,
        release_asset_names,
        require,
        sha256,
        verify_release_bundle,
    )
except ModuleNotFoundError:
    from release_bundle import (  # type: ignore[no-redef]
        APPROVAL_VALUE,
        CI_ARTIFACT_NAME,
        CI_WORKFLOW_PATH,
        DEFAULT_BRANCH,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        PREPARED_ARTIFACT_NAME,
        RELEASE_NAME,
        RELEASE_TAG,
        RELEASE_VERSION,
        REPOSITORY,
        ReleaseError,
        exact_sha,
        exact_sha256,
        exact_release_notes,
        exact_version,
        github_origin,
        positive_integer,
        release_asset_names,
        require,
        sha256,
        verify_release_bundle,
    )


EXPECTED_CI_JOBS = frozenset({
    "Build and verify distribution",
    "Installed wheel (Ubuntu 24.04 / Python 3.11)",
    "Installed wheel (Windows 2025 / Python 3.14)",
    "Required",
    *(f"Source tests ({system}, Python {version})"
      for system in ("ubuntu-24.04", "windows-2025")
      for version in ("3.11", "3.12", "3.13", "3.14")),
})


class GitHubReader(Protocol):
    """Provide the bounded GitHub reads needed by promotion gates."""

    def get(self, path: str) -> dict:
        """Return one GitHub API object."""

    def download_asset(self, asset: dict) -> bytes:
        """Download one release asset without forwarding authorization."""


class GitHubWriter(GitHubReader, Protocol):
    """Provide create-only release asset upload in addition to reads."""

    def upload(self, upload_url: str, name: str, data: bytes) -> dict:
        """Create one release asset and return its API representation."""


@dataclass(frozen=True)
class CiCandidate:
    """Record the exact master CI run and distribution artifact binding."""

    target_sha: str
    ci_run_id: int
    ci_run_attempt: int
    ci_artifact_id: int
    ci_artifact_digest: str


@dataclass(frozen=True)
class Candidate(CiCandidate):
    """Add the exact tag, release notes, and draft release binding."""

    draft_release_id: int
    tag_object_sha: str
    tag_kind: str
    release_notes_sha256: str


def validate_dispatch_context(
    *, event_name: str, repository: str, ref: str, ref_name: str,
    ref_type: str, server_url: str, api_url: str, workflow_sha: str,
    target_sha: str,
) -> None:
    """Require a dispatch of trusted controls at the exact target commit."""
    target_sha = exact_sha(target_sha, "target SHA")
    require(event_name == "workflow_dispatch", "event must be workflow_dispatch")
    require(repository == REPOSITORY, "repository does not match the release contract")
    require(ref_type == "branch", "dispatch ref type must be branch")
    require(ref_name == DEFAULT_BRANCH, f"dispatch branch must be {DEFAULT_BRANCH}")
    require(ref == f"refs/heads/{DEFAULT_BRANCH}", "dispatch ref must be immutable here")
    require(server_url == github_origin("github.com"), "unexpected GitHub server origin")
    require(api_url == github_origin(GITHUB_API_HOST), "unexpected GitHub API origin")
    require(exact_sha(workflow_sha, "workflow SHA") == target_sha,
            "trusted workflow SHA must equal the target SHA")


def _digest(raw: object, label: str) -> str:
    require(isinstance(raw, str) and raw.startswith("sha256:"),
            f"{label} must use the sha256 prefix")
    return exact_sha256(raw.removeprefix("sha256:"), label)


def _resolve_master(api: GitHubReader, target_sha: str) -> None:
    path = f"/repos/{REPOSITORY}/git/ref/heads/{DEFAULT_BRANCH}"
    reference = api.get(path)
    obj = reference.get("object")
    require(isinstance(obj, dict) and obj.get("type") == "commit",
            "live master ref must resolve directly to a commit")
    require(obj.get("sha") == target_sha, "live master no longer matches target SHA")


def _resolve_tag(api: GitHubReader, target_sha: str) -> tuple[str, str]:
    reference = api.get(f"/repos/{REPOSITORY}/git/ref/tags/{RELEASE_TAG}")
    obj = reference.get("object")
    require(isinstance(obj, dict), "tag reference is malformed")
    object_type, object_sha = obj.get("type"), obj.get("sha")
    require(isinstance(object_sha, str), "tag object SHA is missing")
    exact_sha(object_sha, "tag object SHA")
    if object_type == "commit":
        require(object_sha == target_sha, "lightweight tag does not match target SHA")
        return object_sha, "lightweight"
    require(object_type == "tag", "tag must point directly to a commit or one tag object")
    annotated = api.get(f"/repos/{REPOSITORY}/git/tags/{object_sha}")
    peeled = annotated.get("object")
    require(annotated.get("tag") == RELEASE_TAG and isinstance(peeled, dict),
            "annotated tag metadata does not match the exact tag")
    require(peeled.get("type") == "commit" and peeled.get("sha") == target_sha,
            "annotated tag must peel directly to one target commit")
    return object_sha, "annotated"


def _validate_run(run: dict, target_sha: str, ci_run_id: int) -> int:
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    require(run.get("id") == ci_run_id, "CI run ID mismatch")
    require(isinstance(repository, dict) and repository.get("full_name") == REPOSITORY,
            "CI run repository mismatch")
    require(isinstance(head_repository, dict)
            and head_repository.get("full_name") == REPOSITORY,
            "CI run head repository mismatch")
    require(run.get("event") == "push" and run.get("head_branch") == DEFAULT_BRANCH,
            "CI run must be a master push")
    require(run.get("head_sha") == target_sha and run.get("path") == CI_WORKFLOW_PATH,
            "CI run source does not match target workflow and SHA")
    require(run.get("status") == "completed" and run.get("conclusion") == "success",
            "CI run must have completed successfully")
    return positive_integer(run.get("run_attempt"), "CI run attempt")


def _validate_jobs(payload: dict) -> None:
    jobs = payload.get("jobs")
    require(isinstance(jobs, list), "CI jobs response is malformed")
    require(payload.get("total_count") == len(EXPECTED_CI_JOBS),
            "CI job count does not match the exact release matrix")
    require(len(jobs) == len(EXPECTED_CI_JOBS), "CI jobs response is incomplete")
    names = [job.get("name") for job in jobs if isinstance(job, dict)]
    require(len(names) == len(jobs) and len(set(names)) == len(names),
            "CI job names must be present and unique")
    require(set(names) == EXPECTED_CI_JOBS, "CI job names do not match the exact matrix")
    require(all(job.get("status") == "completed" and job.get("conclusion") == "success"
                for job in jobs), "every exact CI job must complete successfully")


def _validate_ci_artifact(payload: dict, target_sha: str, ci_run_id: int) -> tuple[int, str]:
    artifacts = payload.get("artifacts")
    require(payload.get("total_count") == 1 and isinstance(artifacts, list)
            and len(artifacts) == 1, "CI must expose one unique release-dist artifact")
    artifact = artifacts[0]
    require(isinstance(artifact, dict) and artifact.get("name") == CI_ARTIFACT_NAME,
            "CI artifact name mismatch")
    require(artifact.get("expired") is False, "CI artifact is expired")
    artifact_id = positive_integer(artifact.get("id"), "CI artifact ID")
    positive_integer(artifact.get("size_in_bytes"), "CI artifact size")
    workflow = artifact.get("workflow_run")
    require(isinstance(workflow, dict) and workflow.get("id") == ci_run_id,
            "CI artifact workflow run ID mismatch")
    require(workflow.get("head_branch") == DEFAULT_BRANCH
            and workflow.get("head_sha") == target_sha,
            "CI artifact branch or SHA mismatch")
    return artifact_id, _digest(artifact.get("digest"), "CI artifact digest")


def _release_assets(release: dict) -> list[dict]:
    assets = release.get("assets")
    require(isinstance(assets, list) and all(isinstance(asset, dict) for asset in assets),
            "draft release assets response is malformed")
    names = [asset.get("name") for asset in assets]
    require(all(isinstance(name, str) for name in names) and len(set(names)) == len(names),
            "draft release contains duplicate or malformed asset names")
    return assets


def _validate_draft(
    release: dict, target_sha: str, draft_release_id: int, release_notes: str,
) -> list[dict]:
    require(release.get("id") == draft_release_id, "draft release ID mismatch")
    require(release.get("tag_name") == RELEASE_TAG, "draft release tag mismatch")
    require(release.get("name") == RELEASE_NAME, "draft release name mismatch")
    require(release.get("body") == release_notes,
            "draft release body does not match canonical release notes")
    require(release.get("target_commitish") == target_sha,
            "draft release target_commitish must be the exact target SHA")
    require(release.get("draft") is True and release.get("prerelease") is False,
            "release must remain a non-prerelease draft")
    require(release.get("published_at") is None, "draft release is already published")
    return _release_assets(release)


def inspect_ci_candidate(
    api: GitHubReader, *, target_sha: str, version: str, ci_run_id: int,
) -> CiCandidate:
    """Bind live master and its exact successful CI distribution artifact."""
    exact_version(version)
    target_sha = exact_sha(target_sha, "target SHA")
    ci_run_id = positive_integer(ci_run_id, "CI run ID")
    _resolve_master(api, target_sha)
    run_path = f"/repos/{REPOSITORY}/actions/runs/{ci_run_id}"
    attempt = _validate_run(api.get(run_path), target_sha, ci_run_id)
    jobs_path = f"{run_path}/attempts/{attempt}/jobs?per_page=100"
    _validate_jobs(api.get(jobs_path))
    artifacts_path = f"{run_path}/artifacts?name={CI_ARTIFACT_NAME}&per_page=100"
    artifact_id, digest = _validate_ci_artifact(
        api.get(artifacts_path), target_sha, ci_run_id,
    )
    return CiCandidate(target_sha, ci_run_id, attempt, artifact_id, digest)


def inspect_candidate(
    api: GitHubReader, *, target_sha: str, version: str, ci_run_id: int,
    draft_release_id: int, release_notes: str, require_empty: bool = True,
) -> Candidate:
    """Bind live master, an exact successful CI attempt, tag, notes, and draft."""
    release_notes = exact_release_notes(release_notes)
    draft_release_id = positive_integer(draft_release_id, "draft release ID")
    ci = inspect_ci_candidate(
        api, target_sha=target_sha, version=version, ci_run_id=ci_run_id,
    )
    target_sha = ci.target_sha
    tag_object_sha, tag_kind = _resolve_tag(api, target_sha)
    release_path = f"/repos/{REPOSITORY}/releases/{draft_release_id}"
    assets = _validate_draft(
        api.get(release_path), target_sha, draft_release_id, release_notes,
    )
    require(not require_empty or not assets, "prepare requires an exact empty draft release")
    return Candidate(
        ci.target_sha, ci.ci_run_id, ci.ci_run_attempt, ci.ci_artifact_id,
        ci.ci_artifact_digest, draft_release_id, tag_object_sha, tag_kind,
        sha256(release_notes.encode("utf-8")),
    )


def _validate_prepared_artifact(
    api: GitHubReader, *, artifact_id: int, digest: str, workflow_run_id: int,
    target_sha: str,
) -> None:
    path = f"/repos/{REPOSITORY}/actions/artifacts/{artifact_id}"
    artifact = api.get(path)
    require(artifact.get("id") == artifact_id
            and artifact.get("name") == PREPARED_ARTIFACT_NAME,
            "prepared Actions artifact identity mismatch")
    require(artifact.get("expired") is False, "prepared Actions artifact is expired")
    positive_integer(artifact.get("size_in_bytes"), "prepared Actions artifact size")
    require(_digest(artifact.get("digest"), "prepared artifact digest") == digest,
            "prepared Actions artifact digest mismatch")
    workflow = artifact.get("workflow_run")
    require(isinstance(workflow, dict) and workflow.get("id") == workflow_run_id,
            "prepared artifact workflow run ID mismatch")
    require(workflow.get("head_branch") == DEFAULT_BRANCH
            and workflow.get("head_sha") == target_sha,
            "prepared artifact branch or SHA mismatch")


def _remote_asset_map(assets: list[dict], files: dict[str, Path]) -> dict[str, dict]:
    require(len(assets) == len(files), "draft asset set is missing, partial, or contains drift")
    remote = {asset.get("name"): asset for asset in assets}
    require(set(remote) == set(files), "draft asset set is missing, partial, or contains drift")
    for name, asset in remote.items():
        data = files[name].read_bytes()
        asset_id = positive_integer(asset.get("id"), f"remote asset ID for {name}")
        expected_url = (
            f"{github_origin(GITHUB_API_HOST)}/repos/{REPOSITORY}/releases/"
            f"assets/{asset_id}"
        )
        require(asset.get("url") == expected_url,
                f"remote release asset API URL mismatch: {name}")
        require(asset.get("state") == "uploaded" and asset.get("size") == len(data),
                f"remote release asset metadata mismatch: {name}")
        require(_digest(asset.get("digest"), f"remote asset digest for {name}") == sha256(data),
                f"remote release asset digest mismatch: {name}")
    return remote


def _upload_url(release: dict, draft_release_id: int) -> str:
    expected = (
        f"{github_origin(GITHUB_UPLOAD_HOST)}/repos/{REPOSITORY}/releases/"
        f"{draft_release_id}/assets{{?name,label}}"
    )
    require(release.get("upload_url") == expected, "draft release upload URL mismatch")
    return expected.removesuffix("{?name,label}")


def _mutation_gate(
    api: GitHubReader, files: dict[str, Path], candidate: Candidate,
    uploaded: set[str], release_notes: str,
) -> str:
    _resolve_master(api, candidate.target_sha)
    tag_sha, tag_kind = _resolve_tag(api, candidate.target_sha)
    require((tag_sha, tag_kind) == (candidate.tag_object_sha, candidate.tag_kind),
            "tag binding changed before draft mutation")
    path = f"/repos/{REPOSITORY}/releases/{candidate.draft_release_id}"
    release = api.get(path)
    assets = _validate_draft(
        release, candidate.target_sha, candidate.draft_release_id, release_notes,
    )
    require({asset.get("name") for asset in assets} == uploaded,
            "draft assets changed before create-only upload")
    for asset in assets:
        _remote_asset_map([asset], {asset["name"]: files[asset["name"]]})
    return _upload_url(release, candidate.draft_release_id)


def _upload_from_empty(
    api: GitHubWriter, files: dict[str, Path], candidate: Candidate,
    release_notes: str,
) -> None:
    uploaded: set[str] = set()
    for name in release_asset_names():
        upload_url = _mutation_gate(api, files, candidate, uploaded, release_notes)
        response = api.upload(upload_url, name, files[name].read_bytes())
        require(response.get("name") == name, "GitHub returned the wrong uploaded asset")
        uploaded.add(name)


def _download_and_rehash(
    api: GitHubReader, remote: dict[str, dict], files: dict[str, Path],
) -> dict[str, int]:
    asset_ids: dict[str, int] = {}
    for name in release_asset_names():
        expected = files[name].read_bytes()
        downloaded = api.download_asset(remote[name])
        require(len(downloaded) == len(expected) and sha256(downloaded) == sha256(expected),
                f"downloaded release asset does not match prepared bytes: {name}")
        asset_ids[name] = positive_integer(remote[name].get("id"), f"asset ID for {name}")
    return asset_ids


def _final_remote_gate(
    api: GitHubReader, files: dict[str, Path], candidate: Candidate,
    asset_ids: dict[str, int], release_notes: str,
) -> None:
    _resolve_master(api, candidate.target_sha)
    tag_sha, tag_kind = _resolve_tag(api, candidate.target_sha)
    require((tag_sha, tag_kind) == (candidate.tag_object_sha, candidate.tag_kind),
            "tag binding changed during remote verification")
    path = f"/repos/{REPOSITORY}/releases/{candidate.draft_release_id}"
    release = api.get(path)
    assets = _validate_draft(
        release, candidate.target_sha, candidate.draft_release_id, release_notes,
    )
    remote = _remote_asset_map(assets, files)
    final_ids = {name: asset["id"] for name, asset in remote.items()}
    require(final_ids == asset_ids, "draft release asset identities changed during verification")


def _require_bound_candidate(
    candidate: Candidate, *, ci_artifact_id: int, ci_artifact_digest: str,
    ci_run_attempt: int, tag_object_sha: str, release_notes_sha256: str,
) -> None:
    expected = (
        ci_artifact_id, ci_artifact_digest, ci_run_attempt, tag_object_sha,
        release_notes_sha256,
    )
    actual = (candidate.ci_artifact_id, candidate.ci_artifact_digest,
              candidate.ci_run_attempt, candidate.tag_object_sha,
              candidate.release_notes_sha256)
    require(actual == expected, "prepare and upload candidate bindings differ")


def upload_draft_assets(
    api: GitHubWriter, *, bundle_dir: Path, target_sha: str, version: str,
    ci_run_id: int, draft_release_id: int, ci_run_attempt: int,
    ci_artifact_id: int, ci_artifact_digest: str, tag_object_sha: str,
    prepared_artifact_id: int, prepared_artifact_digest: str,
    workflow_run_id: int, approval: str, release_notes: str,
    release_notes_sha256: str,
) -> None:
    """Create exact assets in one bound draft, then download and reverify."""
    require(approval == APPROVAL_VALUE, "release approval kill switch is not armed")
    release_notes = exact_release_notes(release_notes)
    files = verify_release_bundle(bundle_dir, exact_version(version))
    candidate = inspect_candidate(
        api, target_sha=target_sha, version=version, ci_run_id=ci_run_id,
        draft_release_id=draft_release_id, release_notes=release_notes,
        require_empty=False,
    )
    _require_bound_candidate(
        candidate, ci_artifact_id=ci_artifact_id,
        ci_artifact_digest=exact_sha256(ci_artifact_digest, "CI artifact digest"),
        ci_run_attempt=positive_integer(ci_run_attempt, "CI run attempt"),
        tag_object_sha=exact_sha(tag_object_sha, "bound tag object SHA"),
        release_notes_sha256=exact_sha256(
            release_notes_sha256, "bound release notes digest",
        ),
    )
    prepared_digest = exact_sha256(prepared_artifact_digest, "prepared artifact digest")
    _validate_prepared_artifact(
        api, artifact_id=positive_integer(prepared_artifact_id, "prepared artifact ID"),
        digest=prepared_digest, workflow_run_id=workflow_run_id,
        target_sha=candidate.target_sha,
    )
    path = f"/repos/{REPOSITORY}/releases/{candidate.draft_release_id}"
    assets = _validate_draft(
        api.get(path), candidate.target_sha, candidate.draft_release_id, release_notes,
    )
    if not assets:
        _upload_from_empty(api, files, candidate, release_notes)
        assets = _validate_draft(
            api.get(path), candidate.target_sha, candidate.draft_release_id,
            release_notes,
        )
    remote = _remote_asset_map(assets, files)
    asset_ids = _download_and_rehash(api, remote, files)
    _final_remote_gate(api, files, candidate, asset_ids, release_notes)
