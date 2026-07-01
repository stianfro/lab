# Personal Agentic Devbox Design

Date: 2026-07-01

## Goal

Create a personal, persistent Linux development machine inside the Talos lab for terminal-first agentic coding work. The devbox should support long-running Codex and Claude Code tasks, normal Git workflows, tmux persistence, and local development tools while staying reachable only from the local network.

## Non-goals

- Do not use remote VS Code development environments.
- Do not expose the devbox through Cloudflare Tunnel, Gateway API, or a public DNS name.
- Do not run the primary environment as a Kubernetes pod for v1.
- Do not store agent auth files, GitHub tokens, SSH private keys, or kubeconfigs in Git.
- Do not move this automation into a dotfiles repo for v1.

## Architecture

Use a KubeVirt virtual machine backed by Longhorn storage and managed through Flux.

```text
Mac workstation
  |
  | ssh devbox
  v
MetalLB LAN IP, port 22 only
  |
  v
KubeVirt Ubuntu LTS VM
  |
  +-- tmux main session
  +-- Codex CLI
  +-- Claude Code
  +-- Git and GitHub CLI
  +-- Neovim, fish, just, yq, kubectl, flux, helm, talosctl
  +-- Docker Engine and Docker Compose
  +-- persistent Longhorn root disk
```

The normal user flow is SSH from the Mac and attach to a tmux session. Agent-specific resume features are secondary recovery tools, not the main session persistence layer.

## Kubernetes resources

Add a new app directory:

```text
apps/devbox/
  kustomization.yaml
  namespace.yaml
  vm.yaml
  service.yaml
```

Add one Flux `Kustomization` in `clusters/talos/apps.yaml` that depends on KubeVirt, CDI, Longhorn, and MetalLB configuration.

Resources:

- `Namespace`: `devbox`
- `VirtualMachine`: `devbox`
- Root disk from an Ubuntu LTS cloud image through CDI
- Longhorn-backed persistent root disk
- `Service`: `LoadBalancer`, port 22 only
- MetalLB fixed LAN IP, default proposal `192.168.1.51`

The VM uses KubeVirt pod networking with masquerade, matching the existing VM pattern in this repository.

## Access model

The devbox is LAN-only.

- Expose SSH on a fixed MetalLB IP from the existing pool `192.168.1.20-192.168.1.99`.
- Do not create an HTTPRoute, Gateway, public listener, or Cloudflare Tunnel route.
- Disable SSH password login.
- Use SSH public key authentication only.
- The expected workstation command is `ssh devbox`, backed by the user's local SSH config.

## Operating system

Use Ubuntu LTS for v1.

Rationale:

- Broad compatibility with Codex CLI, Claude Code, GitHub CLI, Docker, and common language runtimes.
- Familiar package management.
- Lower setup risk than NixOS for this first version.
- Better third-party install support than Fedora for this specific tool mix.

Implementation should verify the current official Ubuntu LTS cloud image URL before pinning it in the KubeVirt `DataVolume` source.

## Bootstrapping and configuration management

Use cloud-init plus Ansible plus `just`.

Cloud-init stays small and handles only first-boot requirements:

- Create the main user.
- Install and enable OpenSSH server.
- Add SSH public keys.
- Disable password SSH access.
- Install Python, sudo, curl, CA certificates, and other minimal Ansible prerequisites.

Ansible manages the reusable devbox state after the VM is reachable over SSH.

Proposed layout:

```text
ansible/devbox/
  inventory.ini
  playbook.yaml
  group_vars/
    devbox.yaml
  files/
    tmux.conf
  roles/
    base/
    shell/
    tmux/
    agents/
    kubernetes-tools/
    containers/
```

Run Ansible from the workstation through `just`. Do not make Flux run Ansible, because this is a personal mutable dev environment rather than cluster reconciliation state.

## just entry points

Add devbox tasks to the repository `justfile`:

```text
devbox-ssh
devbox-tmux
devbox-converge
devbox-check-tmux-config
devbox-ansible-ping
```

Expected behavior:

- `just devbox-ssh`: open a normal SSH shell.
- `just devbox-tmux`: run `ssh devbox 'tmux new-session -A -s main'`.
- `just devbox-converge`: run the Ansible playbook.
- `just devbox-check-tmux-config`: compare the repo tmux config with the current workstation config.
- `just devbox-ansible-ping`: verify Ansible connectivity.

## tmux requirements

The source of truth for tmux is the current workstation config:

```text
/Users/stianfroystein/.config/tmux/tmux.conf
```

Do not use the older dotfiles copy.

For v1, copy that file into:

```text
ansible/devbox/files/tmux.conf
```

Ansible renders that exact file to:

```text
~/.config/tmux/tmux.conf
```

The config currently references macOS Homebrew fish:

```text
/opt/homebrew/bin/fish
```

To preserve the file content exactly, Ansible creates a Linux compatibility path:

```text
/opt/homebrew/bin/fish -> /usr/bin/fish
```

Ansible also installs TPM under:

```text
~/.config/tmux/plugins/tpm
```

and installs or updates the configured tmux plugins.

## Tooling managed by Ansible

Install and configure the first-pass tool set:

- Shell and session: fish, tmux, TPM plugins, Neovim
- Agent tools: Codex CLI, Claude Code
- Git tools: git, GitHub CLI, OpenSSH client
- Kubernetes tools: kubectl, flux, helm, kustomize, talosctl
- YAML and JSON: yq, jq
- Search and workflow: ripgrep, fd, fzf, direnv, just
- Runtimes: Node.js LTS, Python, Go, Rust
- Containers: Docker Engine and Docker Compose plugin
- Build basics: build-essential, unzip, ca-certificates, gnupg

Prefer pinned or versioned install paths where practical, but keep v1 simple enough to maintain.

## Agent auth and sessions

For v1, authenticate manually inside the VM:

```bash
gh auth login
codex login
claude
```

Do not commit or automate secrets yet.

Relevant behavior considered during design:

- Codex CLI supports headless and device-code login, local session resume, and remote app-server mode.
- Claude Code supports session resume and background sessions. Its terminal-first use still fits best through SSH plus tmux for this design.

## VM sizing

Initial proposal:

- CPU: 4 cores
- Memory: 12 GiB or 16 GiB
- Disk: 200 GiB Longhorn root disk
- Network: fixed MetalLB LAN IP, default proposal `192.168.1.51`

These values can be adjusted after first use.

## Operations and recovery

Normal daily flow:

```bash
just devbox-tmux
```

Recovery behavior:

- If SSH disconnects, tmux keeps running.
- If Codex or Claude Code exits, use their local resume commands where useful.
- If the VM reboots, tmux processes stop, but repos, auth files, transcripts, and tool state remain on the Longhorn disk.
- If the disk is lost, rebuild the VM from Flux and rerun Ansible. Restore working code from Git. Longhorn backup coverage can be added later.

## Validation

Before calling the implementation complete, run:

- `just validate`
- YAML validation through `yq`
- `ansible-playbook --syntax-check`
- `ansible-lint`, if added as a project dependency
- Kubernetes dry-run checks where practical
- SSH smoke test after deployment, if the VM is running

## Open questions for implementation

- Pick the exact MetalLB IP, defaulting to `192.168.1.51` unless reserved elsewhere.
- Pick 12 GiB or 16 GiB memory.
- Verify and pin the Ubuntu LTS cloud image URL.
- Decide whether to install Node.js through Ubuntu packages, NodeSource, or another pinned method.
- Decide exact installation method for Codex CLI and Claude Code based on current official instructions at implementation time.
