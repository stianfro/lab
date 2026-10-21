# Isometric Tokyo preview runtime

Flux owns this app. Runtime packaging stays in this repository, separate from the
product's geographic data and browser build. The app does not require secrets,
credentials, writable persistent storage, or an external backend.

## Two-stage releases

Do not roll a new standalone bundle directly over an existing release. Requests
can reach different replicas during a rollout. New HTML would otherwise request
assets that an old replica does not have, and old browser tabs would lose assets
after the rollout.

Each transition therefore produces two sealed, immutable build contexts:

1. `compatibility` keeps the current HTML and selected manifest. It adds all next
   release assets at their versioned paths and retains earlier asset history.
2. `activation` selects the next HTML and manifest. It has the same union of
   immutable assets, including the previous release and earlier history.

Publish and fully roll out compatibility first. Run the activation gate only
when all replicas have it. Then publish the activation image and change the
Deployment. During both rollouts, every asset referenced by a served entry point
remains available. No shared infrastructure changes or cache purge are needed.

### Prepare and validate

Start with two product-verifier-approved web bundles. `CURRENT_VERIFIER` and
`NEXT_VERIFIER` are the appropriate revisions of the product's
`scripts/package_preview.py`. Set `PYTHON` to an interpreter with their
dependencies if needed. Context and transition output paths must be fresh paths
outside source repositories. Generated assets and archives never belong in Git.

```sh
# First migration from a runtime without retained history only:
just isometric-tokyo-runtime-stage-initial CURRENT CURRENT_VERIFIER NEXT NEXT_VERIFIER OUTPUT

# Every later transition must carry the last activated context forward:
just isometric-tokyo-runtime-stage CURRENT CURRENT_VERIFIER NEXT NEXT_VERIFIER CURRENT_CONTEXT OUTPUT

just isometric-tokyo-runtime-lint
just isometric-tokyo-validate
just isometric-tokyo-runtime-fixtures FRESH_FIXTURE_DIRECTORY
just isometric-tokyo-runtime-validate OUTPUT/compatibility
just isometric-tokyo-runtime-validate OUTPUT/activation
```

Preparation verifies source and copied bundles. It rejects unsafe paths,
symlinks, changed sources, conflicting bytes at an immutable path, and attempts
to overwrite a different existing context. It records exact file inventories,
configuration hashes and deterministic context identities. Repeating the same
inputs is safe. `transition.json` binds both contexts and verifies that every
immutable path is available with identical bytes in both.

Retained files are limited to built `assets/`, versioned `preview/releases/`
(`shinjuku-preview-<24hex>` and `shinjuku-map-<24hex>`), and
`retained-notices/WEB_ID/` containing the corresponding code/dependency licences
and original web inventory. Mutable entry points, current manifests, and root
licence files never use retained fallback. The public, inventoried
`shinjuku-map-<24hex>/pyramid/.chunk-pyramid` format marker is the only allowed
hidden file; all other hidden paths remain denied. A context is capped at 1 GiB, 100,000
files and eight non-selected releases. Exceeding a limit fails without deleting
history. Archival or expiry needs an explicit policy decision before continuing.
Keep the activated context and both source bundles outside Git for subsequent
releases and rollback. Do not discard history by using the initial recipe again.

### Publish compatibility, then activate

The deployment image targets AMD64. Its target stage only copies files, so no
cross-architecture execution is needed. Native validation runs the same server
configuration and checks every current and retained file through HTTP.
Publishing exports a single-platform Docker archive and uses host-side `crane`.
Images carry the sealed context identity as a label.

```sh
just isometric-tokyo-runtime-build OUTPUT/compatibility COMPATIBILITY_IMAGE
just isometric-tokyo-runtime-publish OUTPUT/compatibility COMPATIBILITY_IMAGE
```

Update only `deployment.yaml`: set the returned digest-pinned image and pod
annotation `isometric.tokyo/runtime-context` to the compatibility context ID.
Keep `isometric.tokyo/web-release` at the current selected web release. Run
validation, commit, publish, and let Flux finish the rollout. Do not queue the
activation commit immediately behind it: Flux can skip an intermediate revision.

With the normal authenticated cluster environment, run:

```sh
just isometric-tokyo-runtime-activation-gate OUTPUT COMPATIBILITY_IMAGE_WITH_DIGEST URL
```

The read-only gate checks the registry's context label, Deployment generation,
all ready replicas, exact pod images and context annotations, absence of old or
terminating pods, service endpoints, and full current plus retained HTTP asset
hashes. It checks the rollout again afterward and rejects a changed snapshot.
It never changes cluster state. A successful gate is not permission to make
unrelated cluster changes. If the rollout changes after the gate, rerun it.

Only after that gate passes:

```sh
just isometric-tokyo-runtime-build OUTPUT/activation ACTIVATION_IMAGE
just isometric-tokyo-runtime-publish OUTPUT/activation ACTIVATION_IMAGE
```

Set the activation image digest, context annotation and new selected web-release
annotation in `deployment.yaml`. Validate, commit, publish, wait for readiness,
and verify the full active inventory:

```sh
just isometric-tokyo-runtime-probe OUTPUT/activation URL
```

Rollback to this transition's compatibility image is safe because it retains
both versions. Do not roll back to a pre-compatibility image after the new entry
point has been served. For an older rollback, prepare a new transition with all
current retained history rather than removing asset availability.

`isometric-tokyo-runtime-prepare` remains available for isolated first-release
contexts and tests. It is not a safe replacement for staged updates.

## Runtime behavior

- Non-root process, read-only root filesystem and a bounded temporary volume.
- Two replicas, health probes, resource limits and a disruption budget.
- Only Gateway-namespace ingress is allowed. Application egress is denied.
- `/healthz` returns a small uncached response.
- HTML and JSON require revalidation. Built assets have immutable cache headers.
- Image tiles have bounded caching. Missing files are not cached.
- All responses forbid intermediary transformations. Automatic script injection
  is not accepted by the unchanged strict CSP.
- `/favicon.ico` returns 204 for the browser's implicit icon request.
- Missing tiles and unknown paths return errors, never the browser entry point.
- Access logs are disabled. Error logs go to stderr without request bodies.

The HTTP probe checks all current and retained asset byte lengths and SHA-256
hashes, release identity, health, security/cache headers, and missing-file
behavior. It does not operate a browser or claim geographic approval of AI imagery.
When an older cached image or built asset still has its original cache headers,
the probe checks the canonical URL's bytes first, then checks a runtime-keyed
URL for the current response policy. HTML and JSON never use this fallback.
The report counts these extra policy checks separately.
