# FC accountant document portal

Plain Japanese HTML with server-side sessions, individual passwords and a random URL segment. Public gateway host is accounting.froystein.jp; only /accountant is routed to this app. No Google or ChatGPT login required. Passwords are scrypt hashes in the manually managed `fc-accountant/portal-auth` Secret; never commit that Secret or its link. No documents, manifests with financial data, or credentials belong in Git or the image.

The read-only app uses a Longhorn PVC containing `manifest.json`, `files/`, and `all.zip`. It serves a dated snapshot, not a live accounting ledger. Unknown dates, potential duplicates, cutoff questions and missing evidence must stay visible. FC4 files must not enter the FC3 packet. Never send the accountant a link automatically.

## Operations

Always pass `--kubeconfig /home/stian/src/github.com/stianfro/lab/kubeconfig` on devbox. The default kubecontext may point to an unrelated employer cluster.

Build the app directory and push to `registry.talos.froystein.jp/fc-accountant`, pin its digest in the deployment. Run `node --test app/test.mjs`. Validate `kubectl kustomize apps/fc-accountant` and server dry-run. Register the app explicitly in `clusters/talos/apps.yaml`.

Provision the `portal-auth` Secret out of band with key `auth.json`: `{origin: "https://accounting.froystein.jp", link: <32 random bytes in base64url>, users: [{username, salt, hash, disabled?}]}`. Each password hash is 64-byte scrypt (N=16384, r=8, p=1), salt a fresh random string. Use a private temporary file, create the Secret from file, then remove that temporary hash file. Password delivery is separate from the link and should be person-specific.

To update documents, stage and validate a complete snapshot, scale portal to zero, mount its PVC using `tasks/fc-accountant-load.yaml`, preserve the previous snapshot in the source archive, replace the snapshot, remove the loader and restore one replica. Restart the application after every manifest or auth change. Avoid partial writes to a running snapshot. PVC pruning is disabled to protect originals when app manifests are removed.

To revoke one person, set that user's `disabled` to true (or replace their salted hash) in the Secret and restart the deployment; all existing sessions expire on restart. Rotate `link` and restart to revoke the private URL. To take the site offline, delete its HTTPRoute or suspend the app's Flux Kustomization and scale it to zero. Do not delete its PVC.

Security: Secure/HttpOnly/SameSite=Strict eight-hour in-memory sessions; same-origin POST checks; shared 15 attempts per 15 minutes per gateway connection source; no-store responses; no external scripts/assets/analytics; noindex; same-origin referrers; strict CSP; attachment-only handling of active formats; read-only non-root container; no service-account token and no network egress. Link secrecy is an additional barrier, not a replacement for authentication. TLS terminates at the existing Cloudflare edge, following the lab's existing tunnel architecture.

Back up the original source packet and access Secret using the lab's protected backup process. Longhorn replication is not an independent backup. Plaintext passwords are not stored in the repository or application.
