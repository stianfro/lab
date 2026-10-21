# Isometric Tokyo preview runtime

Flux owns this app. Runtime packaging stays in this repository, separate from the
product's geographic data and browser build. The app does not require secrets,
credentials, writable persistent storage, or an external backend.

## Prepare a release

Start with a verified immutable web bundle from the product repository. Set
`PYTHON` to an interpreter with the product verifier's dependencies if needed.
The context path must be outside all source repositories. Generated assets and
image archives never belong in Git.

```sh
just isometric-tokyo-runtime-prepare BUNDLE PRODUCT_VERIFIER CONTEXT
just isometric-tokyo-runtime-lint
just isometric-tokyo-validate
just isometric-tokyo-runtime-validate CONTEXT
just isometric-tokyo-runtime-build CONTEXT IMAGE
just isometric-tokyo-runtime-publish CONTEXT IMAGE
```

`PRODUCT_VERIFIER` is the product's `scripts/package_preview.py`. Preparation
verifies both the original bundle and copied files. It stores release identity
and runtime configuration hashes in the external context. Validation runs a
native-architecture container with the same server configuration and checks
every served file against the package inventory.

The deployment image targets AMD64. Its target stage only copies files, so no
cross-architecture execution is needed. Publishing exports a single-platform
Docker archive and uses host-side `crane`, avoiding Docker VM network routing.
Record the returned image digest in `deployment.yaml`, then validate and commit
before allowing Flux to reconcile. Use a new release tag for each bundle.

## Runtime behavior

- Non-root process, read-only root filesystem and a bounded temporary volume.
- Two replicas, health probes, resource limits and a disruption budget.
- Only Gateway-namespace ingress is allowed. Application egress is denied.
- `/healthz` returns a small uncached response.
- HTML and JSON require revalidation. Built assets have immutable cache headers.
- Image tiles have bounded caching. Missing files are not cached.
- All responses forbid intermediary transformations. The browser entry point
  remains unchanged and automatic script injection is not accepted by the CSP.
- `/favicon.ico` returns 204 for the browser's implicit icon request.
- Missing tiles and unknown paths return errors, never the browser entry point.
- Access logs are disabled. Error logs go to stderr without request bodies.

After rollout, verify the exact prepared bundle through the public service:

```sh
just isometric-tokyo-runtime-probe CONTEXT URL
```

The probe checks all asset byte lengths and SHA-256 hashes, release identity,
health, security/cache headers, and missing-file behavior. It does not operate a
browser or claim geographic approval of AI imagery.

When an older cached image or built asset still has its original cache headers,
the probe checks the canonical URL's bytes first, then checks a runtime-keyed
URL for the current response policy. HTML and JSON never use this fallback.
The report counts these extra policy checks separately. No shared cache purge
is needed for an unchanged bundle.
