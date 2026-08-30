# Release process

Stateback source and the Python distribution are licensed under the MIT
License. Every source archive includes the repository `LICENSE` file. Both OCI
images declare `org.opencontainers.image.licenses=MIT` and carry the same text
at `/licenses/LICENSE`.

Release publication is tag-driven. PyPI and GHCR are guarded by the protected
GitHub environment named `release`; Pages uses GitHub's required
`github-pages` environment and should have equivalent reviewer protection. The
tag must equal `v` plus the versions in `pyproject.toml`,
`stateback.__version__`, and `frontend/package.json`.

The release workflow rebuilds quality, contract, integration, frontend,
benchmark, dependency/security, package, image, and provenance evidence for the
tagged revision. PyPI uses Trusted Publishing/OIDC. GHCR uses the scoped GitHub
token. No pull-request workflow receives publication permissions.

Python archives are reproducible when built twice from the same locked tree
with the same `SOURCE_DATE_EPOCH`: their SHA-256 digests must match. Frontend
and strict MkDocs output are each built twice and compared by relative-path
SHA-256 manifests. Container equivalence means two `linux/amd64` builds from
the same locked context, pinned bases, release version, source revision, and
`SOURCE_DATE_EPOCH` are independently built without cache, exported with layer
timestamps rewritten to that epoch, and have identical OCI manifest digests
before registry provenance is attached. The protected publication job loads
and pushes that scanned OCI content image, then attaches explicit digest-bound
GitHub provenance and SBOM attestations.

The `0.1.0` OCI publication target is `linux/amd64`. In the protected image
job, each image is built once, scanned locally, assigned a CycloneDX SBOM, and
only that exact local image is pushed. The registry digest from that push is
then used for provenance and SBOM attestations. A separately rebuilt or
unscanned platform is never substituted for the gated image.

The workflow scans the source/configuration and both built images for secrets,
misconfiguration, and high or critical vulnerabilities; audits locked Python
and npm dependencies; attaches package provenance; and requests OCI provenance
and SBOMs. A non-gating report emits every high/critical result; a separate
fix-available scan blocks publication. Unfixed base-distribution advisories
therefore remain visible and require explicit review plus a pinned-base refresh
when a fixed image becomes available.

Human-controlled setup remains required for the PyPI trusted publisher, GHCR
and Pages visibility, protected environment reviewers, tag/repository policy,
and the final tag push. Local readiness does not perform or imply publication.
After PyPI, image, and Pages jobs succeed, a least-privilege final job creates
the tag's GitHub Release and attaches the exact wheel, source archive, and
SHA-256 checksum file.
