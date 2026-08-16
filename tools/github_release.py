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
        GATED_RELEASE_MODES,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        HTTPS_SCHEME,
        RELEASE_NOTES_NAME,
        ReleaseError,
        exact_sha256,
        parse_positive_integer,
        prepare_release_bundle,
        read_release_notes,
        require,
        sha256,
        verify_release_bundle,
    )
    from tools.release_promotion import (
        Candidate,
        CiCandidate,
        inspect_ci_candidate,
        inspect_draft_candidate,
        inspect_prepared_artifact,
        upload_draft_assets,
        validate_dispatch_context,
    )
except ModuleNotFoundError:
    from release_bundle import (  # type: ignore[no-redef]
        GATED_RELEASE_MODES,
        GITHUB_API_HOST,
        GITHUB_UPLOAD_HOST,
        HTTPS_SCHEME,
        RELEASE_NOTES_NAME,
        ReleaseError,
        exact_sha256,
        parse_positive_integer,
        prepare_release_bundle,
        read_release_notes,
        require,
        sha256,
        verify_release_bundle,
    )
    from release_promotion import (  # type: ignore[no-redef]
        Candidate,
        CiCandidate,
        inspect_ci_candidate,
        inspect_draft_candidate,
        inspect_prepared_artifact,
        upload_draft_assets,
        validate_dispatch_context,
    )


API_VERSION = "2026-03-10"
JSON_LIMIT = 4 * 1024 * 1024
ASSET_LIMIT = 64 * 1024 * 1024
SECRET_LIMIT = 16 * 1024
ERROR_BODY_LIMIT = 8 * 1024
ERROR_MESSAGE_LIMIT = 256
ERROR_PERMISSION_LIMIT = 512
ERROR_PATH_LIMIT = 2048
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

def _bounded_field(raw: object, limit: int, fallback: str,
                   redactions: tuple[str, ...] = ()) -> str:
    if not isinstance(raw, str) or not raw:
        return fallback
    redacted = raw
    for secret in redactions:
        variants = (secret, " ".join(secret.split()))
        for variant in variants:
            if variant:
                redacted = redacted.replace(variant, "<redacted>")
    normalized = "".join(
        character if character.isprintable() else "?"
        for character in " ".join(redacted.split())
    )
    return normalized[:limit] if normalized else fallback

def _request_path(request: urllib.request.Request) -> str:
    parsed = _strict_url(request.full_url, {GITHUB_API_HOST, GITHUB_UPLOAD_HOST})
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    require(path.startswith("/") and len(path) <= ERROR_PATH_LIMIT,
            "GitHub request path is not safe to report")
    return path

def _error_message(error: urllib.error.HTTPError,
                   redactions: tuple[str, ...] = ()) -> str:
    if error.fp is None:
        return "<unavailable>"
    try:
        raw = error.read(ERROR_BODY_LIMIT + 1)
    except OSError:
        return "<unavailable>"
    if len(raw) > ERROR_BODY_LIMIT:
        return "<oversized>"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "<unavailable>"
    if not isinstance(payload, dict):
        return "<unavailable>"
    return _bounded_field(
        payload.get("message"), ERROR_MESSAGE_LIMIT, "<unavailable>", redactions,
    )

def _http_failure(
    error: urllib.error.HTTPError, request: urllib.request.Request, token: str,
) -> ReleaseError:
    method = request.get_method()
    path = _request_path(request)
    message = _error_message(error, (token,))
    accepted = _bounded_field(
        error.headers.get("X-Accepted-GitHub-Permissions") if error.headers else None,
        ERROR_PERMISSION_LIMIT, "<missing>", (token,),
    )
    return ReleaseError(
        "GitHub API request failed: "
        f"method={method} path={path} status={error.code} "
        f"message={message!r} accepted_permissions={accepted!r}"
    )


class GitHubApi:
    """Minimal GitHub client that never follows an authenticated redirect."""

    def __init__(self, token: str, api_url: str) -> None:
        require(0 < len(token) <= 4096 and "\r" not in token and "\n" not in token,
                "GitHub token is malformed")
        self._token = token
        self._api_origin = _strict_origin(api_url, GITHUB_API_HOST)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(
        self, method: str, url: str, data: bytes | None = None,
    ) -> urllib.request.Request:
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
            raise _http_failure(error, request, self._token) from error
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
            if error.code != 302:
                raise _http_failure(error, request, self._token) from error
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
    parser.add_argument("--control-sha", required=True)


def _candidate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subject-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--ci-run-id", required=True)


def _prepared_arguments(parser: argparse.ArgumentParser, *, include_size: bool) -> None:
    parser.add_argument("--prepared-artifact-id", required=True)
    parser.add_argument("--prepared-artifact-digest", required=True)
    if include_size:
        parser.add_argument("--prepared-artifact-size", required=True)
    parser.add_argument("--prepared-workflow-run-id", required=True)


def _draft_arguments(parser: argparse.ArgumentParser) -> None:
    _candidate_arguments(parser)
    parser.add_argument("--ci-run-attempt", required=True)
    parser.add_argument("--ci-artifact-id", required=True)
    parser.add_argument("--ci-artifact-digest", required=True)
    parser.add_argument("--draft-release-id", required=True)
    _prepared_arguments(parser, include_size=True)
    parser.add_argument("--release-notes-sha256", required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--release-notes", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_ci = commands.add_parser("inspect-ci")
    _context_arguments(inspect_ci)
    _candidate_arguments(inspect_ci)
    inspect_ci.add_argument("--github-output", type=Path, required=True)
    inspect_prepared = commands.add_parser("inspect-prepared")
    _context_arguments(inspect_prepared)
    inspect_prepared.add_argument("--subject-sha", required=True)
    _prepared_arguments(inspect_prepared, include_size=False)
    inspect_prepared.add_argument("--github-output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--dist-dir", type=Path, required=True)
    prepare.add_argument("--project-root", type=Path, required=True)
    prepare.add_argument("--bundle-dir", type=Path, required=True)
    prepare.add_argument("--version", required=True)
    prepare.add_argument("--github-output", type=Path, required=True)
    verify = commands.add_parser("verify-bundle")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    verify.add_argument("--version", required=True)
    inspect_draft = commands.add_parser("inspect-draft")
    _context_arguments(inspect_draft)
    _draft_arguments(inspect_draft)
    inspect_draft.add_argument("--mode", choices=GATED_RELEASE_MODES, required=True)
    inspect_draft.add_argument("--github-output", type=Path, required=True)
    upload = commands.add_parser("upload-draft")
    _context_arguments(upload)
    _draft_arguments(upload)
    upload.add_argument("--tag-object-sha", required=True)
    upload.add_argument("--tag-kind", choices=("lightweight", "annotated"), required=True)
    return parser


def _validate_context(args: argparse.Namespace) -> None:
    validate_dispatch_context(
        event_name=args.event_name, repository=args.repository, ref=args.ref,
        ref_name=args.ref_name, ref_type=args.ref_type,
        server_url=args.server_url, api_url=args.api_url,
        control_sha=args.control_sha, subject_sha=args.subject_sha,
    )


def _write_values(path: Path, values: dict[str, object]) -> None:
    require(path.is_file() and not path.is_symlink(), "GitHub output must be a regular file")
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def _write_candidate(path: Path, candidate: CiCandidate) -> None:
    values: dict[str, object] = {
        "subject_sha": candidate.subject_sha,
        "ci_run_id": candidate.ci_run_id,
        "ci_run_attempt": candidate.ci_run_attempt,
        "ci_artifact_id": candidate.ci_artifact_id,
        "ci_artifact_digest": candidate.ci_artifact_digest,
    }
    if isinstance(candidate, Candidate):
        values.update({
            "draft_release_id": candidate.draft_release_id,
            "prepared_artifact_id": candidate.prepared_artifact_id,
            "prepared_artifact_digest": candidate.prepared_artifact_digest,
            "prepared_artifact_size": candidate.prepared_artifact_size,
            "release_notes_sha256": candidate.release_notes_sha256,
        })
        if candidate.tag_object_sha is not None and candidate.tag_kind is not None:
            values["tag_object_sha"] = candidate.tag_object_sha
            values["tag_kind"] = candidate.tag_kind
    _write_values(path, values)


def _run_inspect_ci(args: argparse.Namespace) -> None:
    _validate_context(args)
    token = _read_secrets(1)[0]
    candidate = inspect_ci_candidate(
        GitHubApi(token, args.api_url), subject_sha=args.subject_sha,
        version=args.version, ci_run_id=parse_positive_integer(args.ci_run_id, "CI run ID"),
    )
    _write_candidate(args.github_output, candidate)
    print("bound exact live master and successful CI artifact without draft or tag reads")


def _run_inspect_prepared(args: argparse.Namespace) -> None:
    _validate_context(args)
    token = _read_secrets(1)[0]
    size = inspect_prepared_artifact(
        GitHubApi(token, args.api_url),
        artifact_id=parse_positive_integer(args.prepared_artifact_id, "prepared artifact ID"),
        digest=exact_sha256(args.prepared_artifact_digest, "prepared artifact digest"),
        workflow_run_id=parse_positive_integer(
            args.prepared_workflow_run_id, "prepared workflow run ID"),
        subject_sha=args.subject_sha,
    )
    _write_values(args.github_output, {"prepared_artifact_size": size})
    print("bound exact prepared artifact size, digest, run, branch, and subject SHA")


def _run_prepare(args: argparse.Namespace) -> None:
    prepare_release_bundle(args.dist_dir, args.project_root, args.bundle_dir, args.version)
    notes = read_release_notes(args.bundle_dir / "control" / RELEASE_NOTES_NAME)
    _write_values(args.github_output, {
        "release_notes_sha256": sha256(notes.encode("utf-8")),
    })
    print("prepared exact release bundle")


def _bound_draft_arguments(args: argparse.Namespace) -> dict[str, object]:
    return {
        "bundle_dir": args.bundle_dir,
        "subject_sha": args.subject_sha,
        "version": args.version,
        "ci_run_id": parse_positive_integer(args.ci_run_id, "CI run ID"),
        "ci_run_attempt": parse_positive_integer(args.ci_run_attempt, "CI run attempt"),
        "ci_artifact_id": parse_positive_integer(args.ci_artifact_id, "CI artifact ID"),
        "ci_artifact_digest": exact_sha256(args.ci_artifact_digest, "CI artifact digest"),
        "draft_release_id": parse_positive_integer(args.draft_release_id, "draft release ID"),
        "prepared_artifact_id": parse_positive_integer(
            args.prepared_artifact_id, "prepared artifact ID"),
        "prepared_artifact_digest": exact_sha256(
            args.prepared_artifact_digest, "prepared artifact digest"),
        "prepared_artifact_size": parse_positive_integer(
            args.prepared_artifact_size, "prepared artifact size"),
        "prepared_workflow_run_id": parse_positive_integer(
            args.prepared_workflow_run_id, "prepared workflow run ID"),
        "release_notes": read_release_notes(args.release_notes),
        "release_notes_sha256": exact_sha256(
            args.release_notes_sha256, "bound release notes digest"),
    }


def _run_inspect_draft(args: argparse.Namespace) -> None:
    _validate_context(args)
    token = _read_secrets(1)[0]
    candidate = inspect_draft_candidate(
        GitHubApi(token, args.api_url), mode=args.mode, **_bound_draft_arguments(args),
    )
    _write_candidate(args.github_output, candidate)
    print(f"{args.mode}: rebound exact protected draft boundary without mutation")


def _run_upload(args: argparse.Namespace) -> None:
    _validate_context(args)
    token, approval = _read_secrets(2)
    upload_draft_assets(
        GitHubApi(token, args.api_url), approval=approval,
        tag_object_sha=args.tag_object_sha, tag_kind=args.tag_kind,
        **_bound_draft_arguments(args),
    )
    print("READY_FOR_HUMAN_PUBLICATION: exact remote draft assets verified")


def _run(args: argparse.Namespace) -> None:
    if args.command == "inspect-ci":
        _run_inspect_ci(args)
    elif args.command == "inspect-prepared":
        _run_inspect_prepared(args)
    elif args.command == "prepare":
        _run_prepare(args)
    elif args.command == "verify-bundle":
        verify_release_bundle(args.bundle_dir, args.version)
        print("verified exact release bundle")
    elif args.command == "inspect-draft":
        _run_inspect_draft(args)
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
