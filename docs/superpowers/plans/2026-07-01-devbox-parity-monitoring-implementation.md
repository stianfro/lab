# Devbox Parity And Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the devbox closer to the workstation shell and agent setup while adding Prometheus Node Exporter monitoring.

**Architecture:** Keep personal fish, Codex, and Claude files out of Git. Git stores only sync scripts, package installation, and Kubernetes monitoring resources. The sync script copies allowlisted local files to the devbox over SSH, while Ansible installs Linux tool equivalents and Node Exporter.

**Tech Stack:** Ubuntu 24.04, Ansible, KubeVirt, Prometheus Operator `ServiceMonitor`, `just`, `rsync`, SSH.

---

### Task 1: Personal config sync helper

**Files:**
- Create: `scripts/devbox-sync-personal-config.sh`
- Modify: `justfile`
- Modify: `docs/devbox.md`

- [ ] Add a shell script that copies allowlisted fish, Codex, and Claude prompt files from the workstation to `devbox`.
- [ ] Exclude generated state and sensitive directories: fish variables, shell history, Codex sessions, Claude sessions, cloud configs, SSH files, kubeconfigs, and auth state.
- [ ] Generate devbox-safe Codex and Claude settings from local settings by copying only safe prompt and preference keys.
- [ ] Add `just devbox-sync-personal-config`.
- [ ] Document that personal config is copied by the recipe and never stored in Git.

### Task 2: Tool parity and Node Exporter packages

**Files:**
- Modify: `ansible/devbox/group_vars/devboxes.yaml`
- Modify: `ansible/devbox/roles/base/tasks/main.yaml`
- Modify: `ansible/devbox/roles/kubernetes-tools/tasks/main.yaml`
- Modify: `ansible/devbox/roles/agents/tasks/main.yaml`
- Modify: `docs/devbox.md`

- [ ] Add common workstation shell packages available through Ubuntu apt.
- [ ] Add binary release installs for tools not packaged well enough in Ubuntu.
- [ ] Add user-level `pipx` installs for `commitizen` and `mitmproxy`.
- [ ] Install and enable `prometheus-node-exporter` on the VM.
- [ ] Add compatibility symlinks for command names that differ on Ubuntu, such as `bat`.

### Task 3: Kubernetes scrape wiring

**Files:**
- Modify: `apps/devbox/vm.yaml`
- Modify: `apps/devbox/kustomization.yaml`
- Create: `apps/devbox/node-exporter-service.yaml`
- Create: `apps/devbox/servicemonitor.yaml`
- Modify: `clusters/talos/apps.yaml`

- [ ] Add KubeVirt masquerade port `9100` for Node Exporter.
- [ ] Add a cluster-internal Service for `devbox-node-exporter`.
- [ ] Add a `ServiceMonitor` in the `devbox` namespace.
- [ ] Make the Flux devbox Kustomization depend on `monitoring` so the `ServiceMonitor` CRD exists.

### Task 4: Verification and release

**Files:**
- No new files.

- [ ] Validate YAML with `yq`.
- [ ] Run `just validate`.
- [ ] Run Ansible syntax check.
- [ ] Run `just devbox-converge` against the live devbox.
- [ ] Apply or reconcile devbox manifests.
- [ ] Verify Node Exporter locally on the VM.
- [ ] Verify the Kubernetes Service and ServiceMonitor exist.
- [ ] Commit with a Conventional Commit message.
- [ ] Push `main`.
