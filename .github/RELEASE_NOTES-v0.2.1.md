# Trust Meter v0.2.1

These notes describe the `0.2.1` release candidate before publication. The
version in source control is not publication evidence; publication is proven
only by the exact tag, target commit, GitHub Release state, and verified attached
assets.

## Highlights

- Adds the closed `trust-meter.measure/v1` JSON interface with explicit
  `--no-config` or exact `--config FILE` input binding.
- Fixes the built-in metric order, weights, collector profile, configuration
  digest, and rounded threshold comparison used by that machine interface.
- Packages the canonical measurement schema in the wheel and promotes the same
  repository-root bytes as a standalone release attachment.
- Qualifies source tests on Python 3.11 through 3.14 across Ubuntu 24.04 and
  Windows 2025, then verifies one canonical wheel and sdist plus installed-wheel
  acceptance.
- Separates public CI/artifact preparation from private draft inspection. The
  prepare job remains read-only; every private-draft gate runs in the protected
  `github-release` environment with no repository checkout.

## Exact attached files

The controlled workflow accepts exactly these four manually attached assets:

- `trust_meter-0.2.1-py3-none-any.whl`
- `trust_meter-0.2.1.tar.gz`
- `trust-meter-measure-v1.schema.json`
- `SHA256SUMS.txt`

The canonical sdist is `trust_meter-0.2.1.tar.gz`. GitHub-generated source-code
zip and tar archives are separate convenience downloads and are not the verified
sdist. The schema `$id` is the immutable future asset URL for tag `v0.2.1`; the
candidate checks that exact URL string and byte parity without requiring it to
resolve before publication. After publication, a human must anonymously fetch
and hash the attached schema and the other attached assets.

## Authority and orchestration boundaries

Trust Meter remains an advisory structural measurement. Machine output keeps
`authority_effect` fixed to `none`; a score is not an authorization decision or
an aggregate security verdict.

This release does not qualify or contain Python interpreter startup for Evidence
Workbench, does not grant Evidence Workbench execution admission, and does not
provide production multi-tool orchestration. Those are separate fail-closed
integration and runtime-qualification milestones.

PyPI is not a publication channel for this release. The release workflow does
not build during promotion, publish to PyPI, create a tag, create a Release,
publish a Release, or change draft title/body/state.

## Controlled handoff

`rehearsal` binds a successful post-merge `master` CI run and prepares the exact
bundle without reading a tag or private draft. `draft-rehearsal` then uses the
protected environment to prove that its write-scoped job token can read an exact
empty draft before the one-shot tag exists. `dry-run` repeats the read-only draft
gate and additionally binds the exact tag. Only `upload-draft` receives the
release-scoped approval kill switch; it performs create-only attachment uploads,
downloads them again, and leaves the Release as a draft.

The tagged copy of this file is the canonical notes record. A GitHub Release
body is a checked navigation copy and may remain editable even when release
assets are immutable. The workflow's final read cannot eliminate the interval
before a human clicks Publish. Immediately before publication, a human must
recheck repository governance, the tag and target commit, title, exact notes
body, draft state, attached asset names/IDs/digests, and anonymous downloads.
