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

SSH password login is disabled. Use SSH public key authentication. New root disks use the `longhorn-devbox-local` storage class with one replica because current lab storage capacity does not fit a larger three-replica devbox volume. Existing root disks created before that class may still report `longhorn-devbox`.

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

Copy personal shell, Neovim, and agent prompt files from the workstation:

```bash
just devbox-sync-personal-config
```

## Daily use

Attach to the persistent tmux session:

```bash
just devbox-tmux
```

Attach to the persistent Herdr session:

```bash
just devbox-herdr
```

Open a plain SSH shell:

```bash
just devbox-ssh
```

Open devbox HTML artifacts from the Mac:

```text
http://devbox/<path>
http://192.168.1.51/usage.html
```

Add `192.168.1.51 devbox` to the Mac hosts file for the short hostname. The
`devbox-html-server` systemd service serves files from `~/public_html` on direct
paths. For example, `~/public_html/reports/status.html` is available at
`http://devbox/reports/status.html`. The `/usage.html` route refreshes
`~/.claude/usage/usage.html` through `claude-usage html --no-open` before
returning the page.

Agents can use the `devbox-html` helper:

```bash
out="$(devbox-html path reports/status.html)"
devbox-html url reports/status.html
devbox-html open reports/status.html
```

Do not put secrets, tokens, private logs, auth files, kubeconfigs, SSH keys, or
sensitive transcripts under `~/public_html`. The VM template and LoadBalancer
publish port 80, but a running VM only picks up new KubeVirt interface ports
after its next normal restart.

Both SSH recipes start a local browser bridge on the workstation. OAuth
authorization code flows on the devbox use `/usr/local/bin/devbox-browser`
through `BROWSER` and the `xdg-open` wrapper. The opener sends browser URLs back
through the SSH reverse forward, the workstation opens them in the local browser,
and any localhost callback port from the URL itself or the `redirect_uri` is
temporarily forwarded back to the devbox. The callback forward is added to the
existing SSH connection with SSH ControlMaster, so it keeps working after the Mac
VPN starts as long as the original devbox SSH session is still alive.

If you connect without the `just` recipes, the opener prints the URL, saves it
to `~/.cache/devbox-browser/last-url`, and tries to copy it with OSC 52. For
flows that redirect to localhost, it also prints the matching `ssh -L` command
to run on the Mac before opening the URL.

The SSH recipes also expose a SOCKS proxy on the devbox at
`socks5h://127.0.0.1:48767`. The proxy is backed by the Mac SSH client, so it
can reach endpoints that are only routed by the Mac VPN. It is opt-in to avoid
sending normal devbox traffic through the Mac.

Run one command through the Mac relay:

```bash
macrelay curl https://vpn-only.example.com
```

In a fish session, turn the relay proxy environment on and off:

```fish
macrelay-on
curl https://vpn-only.example.com
macrelay-off
```

For POSIX shells, use `macrelay_on` and `macrelay_off`, or run
`eval "$(devbox-mac-relay env)"`. If you already have a devbox shell open
without the relay, keep just the relay up from the Mac:

```bash
just devbox-relay
```

This covers tools that honor `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY`. Tools
that ignore proxy environment variables need an app-specific proxy setting or a
dedicated SSH port forward.

Check that the repo tmux config still matches the current workstation config:

```bash
just devbox-check-tmux-config
```

Herdr is managed by Ansible as an optional tmux alternative. The devbox config
sets the Herdr prefix to `ctrl+space`, matching the tmux prefix, and installs
the Claude and Codex integrations so Herdr can track agent session identity.
Use `ctrl+space` then `q` to detach. Reattach with `just devbox-herdr`.

Check Herdr after converging:

```bash
herdr --version
herdr integration status
cat ~/.config/herdr/config.toml
```

Sync workstation fish, Neovim, Codex, and Claude prompt files after local changes:

```bash
just devbox-sync-personal-config
```

The sync recipe copies allowlisted files over SSH. It includes the workstation
AstroNvim config from `~/.config/nvim`, but excludes the config Git metadata and
local Neovim logs. It does not store personal agent config, cloud config, auth
state, SSH files, kubeconfigs, sessions, or generated memories in Git.

Ansible also manages home-level agent context files. `/home/stian/AGENTS.md`
points Codex to `/home/stian/CLAUDE.md`, which tells both agents that the
devbox is a headless Ubuntu server for terminal-first server operations. The
sync recipe also installs the repo-owned `devbox-html` and `herdr` skills for
Claude and Codex.

## Homebrew packages

Some devbox packages are installed with Homebrew for Linux when the Ubuntu
package is missing or too old. The package lists are in
`ansible/devbox/group_vars/devboxes.yaml` under `homebrew_packages` and
`homebrew_casks`. Taps such as `intility/tap` are listed under
`homebrew_taps`. Ansible links selected binaries, including `az`, `indev`,
`k9s`, and Homebrew's `nvim`, into `/usr/local/bin`. Homebrew's Neovim is used
because the workstation AstroNvim config requires Neovim 0.10 or newer.

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

If you are using Herdr, reconnect with `just devbox-herdr`. The Herdr server
keeps panes running while the VM is up.

If the VM reboots, running processes stop, but repositories, auth files, agent transcripts, and tool state remain on the Longhorn root disk.

If the root disk is lost, recreate the VM through Flux, rerun `just devbox-converge`, and restore work from Git. Longhorn backup coverage can be added later.

## Agentic coding benchmarks

Use the repo benchmark suite to compare this devbox with the Mac for local coding loops, disk behavior, Git, search, YAML validation, and concurrent command work:

```bash
just bench-doctor
just bench
```

See `docs/agentic-coding-benchmarks.md` for macOS setup, profiles, result files, and comparison commands.

## Storage performance

The current devbox root disk is a one-replica Longhorn volume. It was originally created with disabled data locality, which allowed the VM to run on one node while the Longhorn replica lived on another node. That path adds network IO to every disk operation.

For the existing root volume, Longhorn rejected switching directly to `strict-local` while the volume was attached. The live volume was temporarily switched to `best-effort`, which created a local replica on the VM node without stopping the VM. After switching the volume back to `disabled`, Longhorn kept the single replica local to `talos-p13-7d3`.

The local-replica benchmark result is `.cache/bench/results/20260705T105410Z-devbox-balanced`. Compared with the earlier 8 vCPU / 32 GiB result, sequential read improved from 259 MiB/s to 626 MiB/s, sequential write from 145 MiB/s to 262 MiB/s, random mixed read from 6.7 MiB/s to 10.0 MiB/s, random mixed write from 2.9 MiB/s to 4.3 MiB/s, and fsync-heavy small writes from 1.4 MiB/s to 2.0 MiB/s.

For future rebuilds, the VM template uses the `longhorn-devbox-local` storage class. It keeps one strict-local replica on the same node as the VM for lower latency. This trades away cross-node failover for better devbox IO, which is acceptable for this personal, reproducible VM because code should be pushed to Git and the machine can be rebuilt with Ansible.

If the devbox is rebuilt from scratch for IO testing:

1. Confirm no uncommitted or unpushed work exists inside the devbox.
2. Stop or delete the old VM and root PVC from outside the devbox.
3. Confirm `apps/devbox/vm.yaml` uses `storageClassName: longhorn-devbox-local` for the root disk.
4. Reconcile Flux, wait for the VM, run `just devbox-converge`, then re-authenticate manual tools.
5. Run `just bench` and compare with the saved benchmark results.

NVMe PCI passthrough was investigated but is not suitable with the current hardware layout. Each node has one 1 TB NVMe device, and that device is the Talos install disk and Longhorn backing disk. Passing it through to the VM would break the host. NVMe passthrough would require a second dedicated NVMe device or a dedicated bare-metal devbox.
