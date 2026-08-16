# Release candidate history

## v0.2.1 pre-publication rehearsal

Before publication, production workflow run `31928180974` attempted a
`draft-rehearsal` against draft `371236195`. The candidate tag was absent, and
the unpublished draft retained zero attached assets.

The bundled release-control command stopped before its first authenticated
release-control GitHub REST GET and before any tag, draft metadata or state, or
release-asset mutation. Executing the downloaded control with bytecode writes
enabled created a `__pycache__` entry inside its own exact control directory, so
the bundle verifier rejected that self-contaminated directory. The run therefore
did not prove private-draft visibility. It did not create a tag, upload a release
asset, or change or publish the draft.

## v0.2.0

`v0.2.0` is a quarantined, abandoned, unpublished candidate. It is not a
public Trust Meter release and must not be cited as publication evidence.

At the abandonment decision, its private draft was unpublished and had zero
attached assets. Promotion stopped before mutation when the read-only prepare
job received an HTTP 403 while attempting to read private draft state. The
candidate tag and draft are retained for audit history; they are not to be
deleted, reused, published, or populated with release assets.

This historical candidate does not qualify Evidence Workbench execution, does
not justify an Evidence Workbench pin, and does not establish production
multi-tool orchestration.
