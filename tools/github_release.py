"""Run the fail-closed Trust Meter GitHub draft release control plane."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import BinaryIO


# Isolated mode omits the script directory. Add only this fixed control directory;
# environment paths and user site initialization remain disabled by ``python -I``.
_CONTROL_DIRECTORY = str(Path(__file__).resolve().parent)
if _CONTROL_DIRECTORY not in sys.path:
    sys.path.insert(0, _CONTROL_DIRECTORY)


try:
    from tools.release_bundle import (
        DEFAULT_BRANCH,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        HTTPS_SCHEME,
        RELEASE_VERSION,
        REPOSITORY,
        ReleaseError,
        exact_sha256,
        parse_positive_integer,
        prepare_release_bundle,
        read_release_notes,
        require,
        verify_release_bundle,
    )
    from tools.release_promotion import (
        Candidate,
        CiCandidate,
        inspect_candidate,
        inspect_ci_candidate,
        upload_draft_assets,
        validate_dispatch_context,
    )
except ModuleNotFoundError:
    from release_bundle import (  # type: ignore[no-redef]
        DEFAULT_BRANCH,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        HTTPS_SCHEME,
        RELEASE_VERSION,
        REPOSITORY,
        ReleaseError,
        exact_sha256,
        parse_positive_integer,
        prepare_release_bundle,
        read_release_notes,
        require,
        verify_release_bundle,
    )
    from release_promotion import (  # type: ignore[no-redef]
        Candidate,
        CiCandidate,
        inspect_candidate,
        inspect_ci_candidate,
        upload_draft_assets,
        validate_dispatch_context,
    )


API_VERSION = "2026-03-10"
JSON_LIMIT = 4 * 1024 * 1024
ASSET_LIMIT = 64 * 1024 * 1024
SECRET_LIMIT = 16 * 1024
TIMEOUT_SECONDS = 30


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _strict_url(raw: str, hosts: set[str]) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise ReleaseError("GitHub URL is malformed") from error
    require(parsed.scheme == HTTPS_SCHEME, "GitHub URL must use HTTPS")
    require(parsed.hostname in hosts, "GitHub URL host is outside the exact allowlist")
    require(port in {None, 443}, "GitHub URL must use the default HTTPS port")
    require(parsed.username is None and parsed.password is None,
            "GitHub URL must not contain user information")
    require(not parsed.fragment, "GitHub URL must not contain a fragment")
    return parsed


def _strict_origin(raw: str, host: str) -> str:
    parsed = _strict_url(raw, {host})
    require(parsed.path in {"", "/"} and not parsed.query,
            "GitHub origin must not contain a path or query")
    return urllib.parse.urlunsplit((HTTPS_SCHEME, host, "", "", ""))


def _read_limited(stream: BinaryIO, limit: int, label: str) -> bytes:
    data = stream.read(limit + 1)
    require(len(data) <= limit, f"{label} exceeds the maximum accepted size")
    return data


def _decode_json(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseError("GitHub API response is not valid UTF-8 JSON") from error
    require(isinstance(value, dict), "GitHub API response must be an object")
    return value


class GitHubApi:
    """Minimal GitHub client that never follows an authenticated redirect."""

    def __init__(self, token: str, api_url: str) -> None:
        require(0 < len(token) <= 4096 and "\r" not in token and "\n" not in token,
                "GitHub token is malformed")
        self._token = token
        self._api_origin = _strict_origin(api_url, GITHUB_API_HOST)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(self, method: str, url: str, data: bytes | None = None) -> urllib.request.Request:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "trust-meter-release-control",
        }
        return urllib.request.Request(url, data=data, headers=headers, method=method)

    def _open_json(self, request: urllib.request.Request) -> dict:
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                require(response.status in {200, 201}, "unexpected GitHub API status")
                return _decode_json(_read_limited(response, JSON_LIMIT, "GitHub JSON"))
        except urllib.error.HTTPError as error:
            raise ReleaseError(f"GitHub API rejected request with status {error.code}") from error
        except urllib.error.URLError as error:
            raise ReleaseError("GitHub API request failed") from error

    def get(self, path: str) -> dict:
        """GET one bounded JSON object from the configured API origin."""
        require(path.startswith("/") and not path.startswith("//") and "#" not in path,
                "GitHub API path must be absolute and origin-relative")
        url = f"{self._api_origin}{path}"
        _strict_url(url, {GITHUB_API_HOST})
        return self._open_json(self._request("GET", url))

    def upload(self, upload_url: str, name: str, data: bytes) -> dict:
        """Create one named release asset without clobber semantics."""
        parsed = _strict_url(upload_url, {GITHUB_UPLOAD_HOST})
        require(not parsed.query, "release upload URL must not carry an existing query")
        query = urllib.parse.urlencode({"name": name})
        url = urllib.parse.urlunsplit(parsed._replace(query=query))
        request = self._request("POST", url, data)
        request.add_header("Content-Type", "application/octet-stream")
        request.add_header("Content-Length", str(len(data)))
        return self._open_json(request)

    def _download_redirect(self, location: str) -> bytes:
        parsed = _strict_url(location, {urllib.parse.urlsplit(location).hostname or ""})
        host = parsed.hostname or ""
        require(host.endswith(".githubusercontent.com"),
                "asset redirect host is outside GitHub content storage")
        request = urllib.request.Request(location, headers={
            "Accept": "application/octet-stream",
            "User-Agent": "trust-meter-release-control",
        })
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                require(response.status == 200, "asset redirect did not return content")
                return _read_limited(response, ASSET_LIMIT, "release asset")
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            raise ReleaseError("unauthenticated release asset download failed") from error

    def download_asset(self, asset: dict) -> bytes:
        """Download an API asset while stripping authorization at the redirect."""
        url = asset.get("url")
        require(isinstance(url, str), "release asset API URL is missing")
        _strict_url(url, {GITHUB_API_HOST})
        request = self._request("GET", url)
        request.add_header("Accept", "application/octet-stream")
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                require(response.status == 200, "release asset download returned wrong status")
                return _read_limited(response, ASSET_LIMIT, "release asset")
        except urllib.error.HTTPError as error:
            require(error.code == 302, "authenticated asset request must not redirect unexpectedly")
            location = error.headers.get("Location")
            require(isinstance(location, str), "asset redirect is missing a location")
            return self._download_redirect(location)
        except urllib.error.URLError as error:
            raise ReleaseError("release asset API request failed") from error


def _read_secrets(count: int) -> list[str]:
    raw = _read_limited(sys.stdin.buffer, SECRET_LIMIT, "secret input")
    require(raw.endswith(b"\n") and b"\r" not in raw,
            "secret input must use LF-terminated lines")
    lines = raw[:-1].split(b"\n")
    require(len(lines) == count and all(lines), "secret input line count mismatch")
    try:
        return [line.decode("utf-8") for line in lines]
    except UnicodeDecodeError as error:
        raise ReleaseError("secret input must be valid UTF-8") from error


def _context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--ref-name", required=True)
    parser.add_argument("--ref-type", required=True)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--workflow-sha", required=True)


def _candidate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ci-run-id", required=True)


def _binding_arguments(parser: argparse.ArgumentParser) -> None:
    _candidate_arguments(parser)
    parser.add_argument("--draft-release-id", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    _context_arguments(inspect)
    _binding_arguments(inspect)
    inspect.add_argument("--release-notes", type=Path, required=True)
    inspect.add_argument("--github-output", type=Path, required=True)
    rehearsal = commands.add_parser("inspect-rehearsal")
    _context_arguments(rehearsal)
    _candidate_arguments(rehearsal)
    rehearsal.add_argument("--github-output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--dist-dir", type=Path, required=True)
    prepare.add_argument("--project-root", type=Path, required=True)
    prepare.add_argument("--bundle-dir", type=Path, required=True)
    prepare.add_argument("--version", required=True)
    verify = commands.add_parser("verify-bundle")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    verify.add_argument("--version", required=True)
    upload = commands.add_parser("upload-draft")
    _context_arguments(upload)
    _binding_arguments(upload)
    for name in ("ci-run-attempt", "ci-artifact-id", "prepared-artifact-id",
                 "workflow-run-id"):
        upload.add_argument(f"--{name}", required=True)
    upload.add_argument("--ci-artifact-digest", required=True)
    upload.add_argument("--tag-object-sha", required=True)
    upload.add_argument("--release-notes-sha256", required=True)
    upload.add_argument("--prepared-artifact-digest", required=True)
    upload.add_argument("--bundle-dir", type=Path, required=True)
    upload.add_argument("--release-notes", type=Path, required=True)
    return parser


def _validate_context(args: argparse.Namespace) -> None:
    validate_dispatch_context(
        event_name=args.event_name, repository=args.repository, ref=args.ref,
        ref_name=args.ref_name, ref_type=args.ref_type,
        server_url=args.server_url, api_url=args.api_url,
        workflow_sha=args.workflow_sha, target_sha=args.target_sha,
    )


def _write_candidate(path: Path, candidate: CiCandidate) -> None:
    values = {
        "target_sha": candidate.target_sha,
        "ci_run_id": candidate.ci_run_id,
        "ci_run_attempt": candidate.ci_run_attempt,
        "ci_artifact_id": candidate.ci_artifact_id,
        "ci_artifact_digest": candidate.ci_artifact_digest,
    }
    if isinstance(candidate, Candidate):
        values.update({
            "draft_release_id": candidate.draft_release_id,
            "tag_object_sha": candidate.tag_object_sha,
            "tag_kind": candidate.tag_kind,
            "release_notes_sha256": candidate.release_notes_sha256,
        })
    require(path.is_file() and not path.is_symlink(), "GitHub output must be a regular file")
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def _run_inspect(args: argparse.Namespace) -> None:
    _validate_context(args)
    token = _read_secrets(1)[0]
    api = GitHubApi(token, args.api_url)
    candidate = inspect_candidate(
        api, target_sha=args.target_sha, version=args.version,
        ci_run_id=parse_positive_integer(args.ci_run_id, "CI run ID"),
        draft_release_id=parse_positive_integer(args.draft_release_id, "draft release ID"),
        release_notes=read_release_notes(args.release_notes),
    )
    _write_candidate(args.github_output, candidate)
    print("bound exact successful CI artifact, tag, and empty draft release")


def _run_rehearsal_inspect(args: argparse.Namespace) -> None:
    _validate_context(args)
    token = _read_secrets(1)[0]
    api = GitHubApi(token, args.api_url)
    candidate = inspect_ci_candidate(
        api, target_sha=args.target_sha, version=args.version,
        ci_run_id=parse_positive_integer(args.ci_run_id, "CI run ID"),
    )
    _write_candidate(args.github_output, candidate)
    print("bound exact successful CI artifact for pre-tag rehearsal")


def _run_upload(args: argparse.Namespace) -> None:
    _validate_context(args)
    token, approval = _read_secrets(2)
    api = GitHubApi(token, args.api_url)
    upload_draft_assets(
        api, bundle_dir=args.bundle_dir, target_sha=args.target_sha,
        version=args.version, ci_run_id=parse_positive_integer(args.ci_run_id, "CI run ID"),
        draft_release_id=parse_positive_integer(args.draft_release_id, "draft release ID"),
        ci_run_attempt=parse_positive_integer(args.ci_run_attempt, "CI run attempt"),
        ci_artifact_id=parse_positive_integer(args.ci_artifact_id, "CI artifact ID"),
        ci_artifact_digest=exact_sha256(args.ci_artifact_digest, "CI artifact digest"),
        tag_object_sha=args.tag_object_sha,
        prepared_artifact_id=parse_positive_integer(
            args.prepared_artifact_id, "prepared artifact ID"),
        prepared_artifact_digest=exact_sha256(
            args.prepared_artifact_digest, "prepared artifact digest"),
        workflow_run_id=parse_positive_integer(args.workflow_run_id, "workflow run ID"),
        approval=approval,
        release_notes=read_release_notes(args.release_notes),
        release_notes_sha256=exact_sha256(
            args.release_notes_sha256, "bound release notes digest",
        ),
    )
    print("READY_FOR_HUMAN_PUBLICATION: exact remote draft assets verified")


def _run(args: argparse.Namespace) -> None:
    if args.command == "inspect":
        _run_inspect(args)
    elif args.command == "inspect-rehearsal":
        _run_rehearsal_inspect(args)
    elif args.command == "prepare":
        prepare_release_bundle(args.dist_dir, args.project_root, args.bundle_dir, args.version)
        print("prepared exact release bundle")
    elif args.command == "verify-bundle":
        verify_release_bundle(args.bundle_dir, args.version)
        print("verified exact release bundle")
    else:
        _run_upload(args)


def main(argv: list[str] | None = None) -> int:
    """Run one isolated release-control command and fail closed."""
    args = _parser().parse_args(argv)
    try:
        _run(args)
    except (ReleaseError, OSError) as error:
        print(f"GitHub release control failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
