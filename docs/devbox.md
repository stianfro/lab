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

Then converge the tool setup from the workstation:

```bash
just devbox-converge
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

## Manual authentication

Do not commit agent tokens or SSH private keys to Git. Authenticate inside the devbox when needed:

```bash
gh auth login
codex login
claude
```

## Updates

Ubuntu package updates are managed by unattended-upgrades. The devbox installs
security and standard Ubuntu updates automatically, removes unused packages, and
allows automatic reboots at 04:00 when a reboot is required. This can interrupt
long-running processes, so keep important work in Git or another durable store.

## Recovery

If SSH disconnects, reconnect with `just devbox-tmux`. The tmux session keeps running while the VM is up.

If the VM reboots, running processes stop, but repositories, auth files, agent transcripts, and tool state remain on the Longhorn root disk.

If the root disk is lost, recreate the VM through Flux, rerun `just devbox-converge`, and restore work from Git. Longhorn backup coverage can be added later.
