# Personal Devbox

The devbox is a personal Ubuntu LTS VM for terminal-first coding agent work. It runs in KubeVirt, stores state on a 140 GiB Longhorn root disk, and is exposed only on the local network through a MetalLB SSH service.

## Access

The devbox SSH service uses `192.168.1.51` on port 22. The `just devbox-*`
recipes use `stian@192.168.1.51` directly, so no local SSH alias is required.

Optionally add this to the workstation SSH config:

```sshconfig
Host devbox
  HostName 192.168.1.51
  User stian
  IdentityFile ~/.ssh/id_rsa
```

SSH password login is disabled. Use SSH public key authentication. The root disk uses the `longhorn-devbox` storage class with one replica because current lab storage capacity does not fit a larger three-replica devbox volume.

## First boot

After the manifests are merged and reconciled, wait for the VM to become ready:

```bash
kubectl -n devbox get vm,vmi,svc,pod
kubectl -n devbox wait --for=condition=Ready vmi/devbox --timeout=20m
ssh stian@192.168.1.51 'cloud-init status --wait && echo ssh-ready'
```

Then converge the tool setup:

```bash
just devbox-converge
```

This recipe detects whether it is running on the devbox. On host `devbox`, it
uses a local Ansible connection. From another machine, it uses the SSH inventory
for `192.168.1.51`.

For base OS settings only, such as package update policy, run this from the
devbox:

```bash
just devbox-converge-local-base
```

Copy personal shell and agent prompt files from the workstation:

```bash
just devbox-sync-personal-config
```

## Daily use

Attach to the persistent tmux session:

```bash
just devbox-tmux
```

Open a plain SSH shell:

```bash
just devbox-ssh
```

Check that the repo tmux config still matches the current workstation config:

```bash
just devbox-check-tmux-config
```

Sync workstation fish, Codex, and Claude prompt files after local changes:

```bash
just devbox-sync-personal-config
```

The sync recipe copies allowlisted files over SSH. It does not store personal
agent config, cloud config, auth state, SSH files, kubeconfigs, sessions, or
generated memories in Git.

Ansible also manages home-level agent context files. `/home/stian/AGENTS.md`
points Codex to `/home/stian/CLAUDE.md`, which tells both agents that the
devbox is a headless Ubuntu server for terminal-first server operations.

## Homebrew packages

Some devbox packages are installed with Homebrew for Linux when the Ubuntu
package is missing or too old. The package list is in
`ansible/devbox/group_vars/devboxes.yaml` under `homebrew_packages`. The first
managed formula is `derailed/k9s/k9s`, and Ansible links `k9s` into
`/usr/local/bin`.

Converge the devbox after changing the list:

```bash
just devbox-converge
```

## Manual authentication

Do not commit agent tokens or SSH private keys to Git. Authenticate inside the devbox when needed:

```bash
gh auth login
codex login
claude
```

## Monitoring

The devbox runs `prometheus-node-exporter` on port 9100. Kubernetes exposes it
through the cluster-internal `devbox-node-exporter` Service and Prometheus
scrapes it through a `ServiceMonitor`. Port 9100 is not exposed through
MetalLB.

## Updates

Ubuntu package updates are managed by unattended-upgrades. The devbox checks for
packages from 02:00 Japan time, installs security and standard Ubuntu updates
from 03:00 Japan time, and removes unused packages. Both timers have up to 30
minutes of random delay. Automatic reboots are disabled. Reboot manually after
kernel or system library updates when convenient.

## Recovery

If SSH disconnects, reconnect with `just devbox-tmux`. The tmux session keeps running while the VM is up.

If the VM reboots, running processes stop, but repositories, auth files, agent transcripts, and tool state remain on the Longhorn root disk.

If the root disk is lost, recreate the VM through Flux, rerun `just devbox-converge`, and restore work from Git. Longhorn backup coverage can be added later.

## Agentic coding benchmarks

Use the repo benchmark suite to compare this devbox with the Mac for local coding loops, disk behavior, Git, search, YAML validation, and concurrent command work:

```bash
just bench-doctor
just bench
```

See `docs/agentic-coding-benchmarks.md` for macOS setup, profiles, result files, and comparison commands.
