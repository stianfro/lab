# Personal Devbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a LAN-only Ubuntu LTS KubeVirt devbox with SSH, tmux, Codex CLI, Claude Code, and the required developer tools.

**Architecture:** Flux manages a `devbox` KubeVirt VM and a port 22 MetalLB service. Cloud-init creates a minimal SSH-ready Ubuntu host, then Ansible converges the personal toolchain over SSH. The workstation uses `just` tasks for SSH, tmux attach, validation, and Ansible runs.

**Tech Stack:** KubeVirt, CDI, Longhorn, MetalLB, Flux, Ubuntu 24.04 LTS cloud image, cloud-init, Ansible, tmux, fish, Docker Engine, Codex CLI, Claude Code.

---

## File map

- Create `apps/devbox/storageclass.yaml`: devbox Longhorn storage class with one replica.
- Create `apps/devbox/namespace.yaml`: namespace for the VM.
- Create `apps/devbox/vm.yaml`: KubeVirt VM, DataVolume, cloud-init, SSH user.
- Create `apps/devbox/service.yaml`: LAN-only MetalLB SSH service.
- Create `apps/devbox/kustomization.yaml`: app-local Kustomize entry point.
- Modify `clusters/talos/apps.yaml`: Flux `Kustomization` for `apps/devbox`.
- Create `ansible.cfg`: repo-local Ansible defaults that keep temp files under `.cache/`.
- Create `ansible/devbox/inventory.ini`: Ansible inventory for `devbox`.
- Create `ansible/devbox/playbook.yaml`: top-level Ansible playbook.
- Create `ansible/devbox/group_vars/devboxes.yaml`: user, host, tool versions, and paths.
- Create `ansible/devbox/files/tmux.conf`: exact workstation tmux config copy.
- Create `ansible/devbox/roles/base/tasks/main.yaml`: package and base directory setup.
- Create `ansible/devbox/roles/shell/tasks/main.yaml`: fish shell and compatibility symlink.
- Create `ansible/devbox/roles/tmux/tasks/main.yaml`: tmux config and TPM plugin setup.
- Create `ansible/devbox/roles/agents/tasks/main.yaml`: Codex CLI and Claude Code installers.
- Create `ansible/devbox/roles/kubernetes-tools/tasks/main.yaml`: kubectl, flux, helm, kustomize, talosctl.
- Create `ansible/devbox/roles/containers/tasks/main.yaml`: Docker Engine and Compose plugin.
- Modify `justfile`: add devbox tasks.
- Create `docs/devbox.md`: usage and recovery guide.

## Task 1: Add KubeVirt devbox app

**Files:**
- Create: `apps/devbox/storageclass.yaml`
- Create: `apps/devbox/namespace.yaml`
- Create: `apps/devbox/vm.yaml`
- Create: `apps/devbox/service.yaml`
- Create: `apps/devbox/kustomization.yaml`

- [ ] **Step 1: Write `apps/devbox/storageclass.yaml`**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-devbox
provisioner: driver.longhorn.io
allowVolumeExpansion: true
reclaimPolicy: Delete
volumeBindingMode: Immediate
parameters:
  numberOfReplicas: "1"
  staleReplicaTimeout: "30"
  fromBackup: ""
  fsType: ext4
  dataLocality: disabled
  unmapMarkSnapChainRemoved: ignored
  disableRevisionCounter: "true"
  dataEngine: v1
  backupTargetName: default
```

- [ ] **Step 2: Write `apps/devbox/namespace.yaml`**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: devbox
```

- [ ] **Step 3: Write `apps/devbox/vm.yaml`**

Use Ubuntu 24.04 LTS Noble cloud image from Canonical:

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: devbox
  namespace: devbox
spec:
  runStrategy: Always
  template:
    metadata:
      labels:
        kubevirt.io/vm: devbox
    spec:
      domain:
        cpu:
          cores: 4
        resources:
          requests:
            memory: 16Gi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
              bootOrder: 1
            - name: cloudinitdisk
              disk:
                bus: virtio
          interfaces:
            - name: podnet
              masquerade: {}
              ports:
                - name: ssh
                  port: 22
                  protocol: TCP
      networks:
        - name: podnet
          pod: {}
      volumes:
        - name: rootdisk
          persistentVolumeClaim:
            claimName: devbox-root
        - name: cloudinitdisk
          cloudInitNoCloud:
            userData: |-
              #cloud-config
              package_update: true
              package_upgrade: false
              users:
                - default
                - name: stian
                  gecos: Stian Froystein
                  groups: sudo
                  sudo: ['ALL=(ALL) NOPASSWD:ALL']
                  shell: /bin/bash
                  lock_passwd: true
                  ssh_authorized_keys:
                    - ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCjlNh4UPrDac9Yb8R5FOoyB3qo0UNYLS4oGYRY5Cg0gwth0tA0nxvOrirAMj0+RhJ0/O6rg+quh24PYt/Pes6gGUopOyYLvA+i4bHNOAgt91kkqBIjtNFESugcBqVSE565NvKDE+cD8+PLkf4bUMXaMceb1PnGtBwz+URvo9bDVAj/pokkMg11fskIaSikc9nFqYcCs4fXnF3+kOlNL2hdlXKCcD3H5osxgaXoN/O98lsGZZ2BeMcisGwYeGDIxgEFHSUgWrke5JuOod8WkKHF4j67FS6gbiwF7KVAGT2NtVlNbiJ1wu0E4cX05j4j9xo6Uu4HY5roJr+4B7x6f217Je+KwY0EULHCwtKlseNfyQwoDciOC+sDVYXbGsUq4Iya9awpReboeq9Sw6XRu6bq8I9pNBd5kmfezMLRjKCur1B92I92M7MQ0JwX196SKj0HpTa6drXQoln/z0dJatdOZ/WP2Wr7iYWDrjSYHRtgBlQC3kE8Q4lFag5V352fl0U=
              packages:
                - ca-certificates
                - curl
                - gnupg
                - openssh-server
                - python3
                - sudo
              ssh_pwauth: false
              disable_root: true
              write_files:
                - path: /etc/ssh/sshd_config.d/99-devbox-hardening.conf
                  permissions: '0644'
                  owner: root:root
                  content: |
                    PasswordAuthentication no
                    PermitRootLogin no
                    PubkeyAuthentication yes
              runcmd:
                - systemctl enable --now ssh
                - systemctl restart ssh
  dataVolumeTemplates:
    - metadata:
        name: devbox-root
      spec:
        storage:
          resources:
            requests:
              storage: 140Gi
          storageClassName: longhorn-devbox
        source:
          http:
            url: https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
```

- [ ] **Step 4: Write `apps/devbox/service.yaml`**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: devbox-ssh
  namespace: devbox
  annotations:
    metallb.io/loadBalancerIPs: 192.168.1.51
spec:
  type: LoadBalancer
  selector:
    vm.kubevirt.io/name: devbox
  ports:
    - name: ssh
      port: 22
      targetPort: 22
      protocol: TCP
```

- [ ] **Step 5: Write `apps/devbox/kustomization.yaml`**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - storageclass.yaml
  - namespace.yaml
  - vm.yaml
  - service.yaml
```

- [ ] **Step 6: Validate the app YAML**

Run: `kustomize build apps/devbox | yq e 'true' -`

Expected: command exits 0 and prints `true`.

## Task 2: Register the devbox with Flux

**Files:**
- Modify: `clusters/talos/apps.yaml`

- [ ] **Step 1: Add Flux `Kustomization` after `ocp-upgrade-lab`**

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: devbox
  namespace: flux-system
spec:
  dependsOn:
    - name: kubevirt-config
    - name: cdi-config
    - name: metallb-config
  interval: 10m
  path: ./apps/devbox
  prune: true
  sourceRef:
    kind: GitRepository
    name: lab
  timeout: 20m
  # The VM may be booting or intentionally stopped; do not gate cluster readiness on VM health.
  wait: false
```

- [ ] **Step 2: Validate full cluster render**

Run: `just validate`

Expected: command exits 0 and prints `true`.

## Task 3: Add Ansible devbox control files

**Files:**
- Create: `ansible/devbox/inventory.ini`
- Create: `ansible/devbox/playbook.yaml`
- Create: `ansible/devbox/group_vars/devbox.yaml`

- [ ] **Step 1: Write `ansible/devbox/inventory.ini`**

```ini
[devboxes]
devbox ansible_host=192.168.1.51 ansible_user=stian ansible_python_interpreter=/usr/bin/python3
```

- [ ] **Step 2: Write `ansible/devbox/playbook.yaml`**

```yaml
---
- name: Configure personal devbox
  hosts: devboxes
  become: true
  gather_facts: true
  roles:
    - base
    - shell
    - tmux
    - containers
    - kubernetes-tools
    - agents
```

- [ ] **Step 3: Write `ansible/devbox/group_vars/devboxes.yaml`**

```yaml
---
devbox_user: stian
devbox_home: /home/stian
codex_install_url: https://chatgpt.com/codex/install.sh
claude_install_url: https://claude.ai/install.sh
kubectl_version: v1.34.1
flux_version: 2.7.0
helm_version: v3.19.0
kustomize_version: v5.7.1
talosctl_version: v1.12.4
go_version: "1.25.4"
node_major: 24
yq_version: v4.47.2
rustup_init_url: https://sh.rustup.rs
```

## Task 4: Add base, shell, and tmux roles

**Files:**
- Create: `ansible/devbox/files/tmux.conf`
- Create: `ansible/devbox/roles/base/tasks/main.yaml`
- Create: `ansible/devbox/roles/shell/tasks/main.yaml`
- Create: `ansible/devbox/roles/tmux/tasks/main.yaml`

- [ ] **Step 1: Copy exact workstation tmux config**

Run: `mkdir -p ansible/devbox/files && cp /Users/stianfroystein/.config/tmux/tmux.conf ansible/devbox/files/tmux.conf`

Expected: `diff -u /Users/stianfroystein/.config/tmux/tmux.conf ansible/devbox/files/tmux.conf` exits 0.

- [ ] **Step 2: Write `base` role**

```yaml
---
- name: Install base apt packages
  ansible.builtin.apt:
    name:
      - build-essential
      - ca-certificates
      - curl
      - direnv
      - fd-find
      - fish
      - fzf
      - git
      - gnupg
      - jq
      - just
      - neovim
      - openssh-client
      - pipx
      - python3
      - python3-apt
      - python3-pip
      - ripgrep
      - sudo
      - tmux
      - unzip
      - wget
    state: present
    update_cache: true

- name: Create user code directory
  ansible.builtin.file:
    path: "{{ devbox_home }}/src"
    state: directory
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0755"

- name: Link fd to Ubuntu fdfind binary
  ansible.builtin.file:
    src: /usr/bin/fdfind
    dest: /usr/local/bin/fd
    state: link
    force: true

- name: Install mikefarah yq
  ansible.builtin.get_url:
    url: "https://github.com/mikefarah/yq/releases/download/{{ yq_version }}/yq_linux_amd64"
    dest: /usr/local/bin/yq
    mode: "0755"
```

- [ ] **Step 3: Write `shell` role**

```yaml
---
- name: Ensure compatibility directory for workstation tmux shell path exists
  ansible.builtin.file:
    path: /opt/homebrew/bin
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Link workstation fish path to Linux fish
  ansible.builtin.file:
    src: /usr/bin/fish
    dest: /opt/homebrew/bin/fish
    state: link
    force: true

- name: Set login shell to fish
  ansible.builtin.user:
    name: "{{ devbox_user }}"
    shell: /usr/bin/fish

- name: Create fish config directory
  ansible.builtin.file:
    path: "{{ devbox_home }}/.config/fish"
    state: directory
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0755"

- name: Configure fish path
  ansible.builtin.copy:
    dest: "{{ devbox_home }}/.config/fish/config.fish"
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0644"
    content: |
      fish_add_path --move --path $HOME/.local/bin
      fish_add_path --move --path $HOME/.cargo/bin
      fish_add_path --move --path /usr/local/go/bin
```

- [ ] **Step 4: Write `tmux` role**

```yaml
---
- name: Create tmux config directory
  ansible.builtin.file:
    path: "{{ devbox_home }}/.config/tmux"
    state: directory
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0755"

- name: Install exact tmux config
  ansible.builtin.copy:
    src: tmux.conf
    dest: "{{ devbox_home }}/.config/tmux/tmux.conf"
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0644"

- name: Create tmux plugins directory
  ansible.builtin.file:
    path: "{{ devbox_home }}/.config/tmux/plugins"
    state: directory
    owner: "{{ devbox_user }}"
    group: "{{ devbox_user }}"
    mode: "0755"

- name: Install TPM
  ansible.builtin.git:
    repo: https://github.com/tmux-plugins/tpm.git
    dest: "{{ devbox_home }}/.config/tmux/plugins/tpm"
    version: master
    update: true
  become_user: "{{ devbox_user }}"

- name: Install configured tmux plugins
  ansible.builtin.command:
    cmd: "{{ devbox_home }}/.config/tmux/plugins/tpm/bin/install_plugins"
  become_user: "{{ devbox_user }}"
  environment:
    HOME: "{{ devbox_home }}"
  changed_when: false
```

## Task 5: Add containers, Kubernetes tools, and agent roles

**Files:**
- Create: `ansible/devbox/roles/containers/tasks/main.yaml`
- Create: `ansible/devbox/roles/kubernetes-tools/tasks/main.yaml`
- Create: `ansible/devbox/roles/agents/tasks/main.yaml`

- [ ] **Step 1: Write `containers` role**

Install Docker from Ubuntu packages for v1:

```yaml
---
- name: Install container packages
  ansible.builtin.apt:
    name:
      - docker.io
      - docker-compose-v2
    state: present
    update_cache: true

- name: Enable Docker service
  ansible.builtin.systemd:
    name: docker
    enabled: true
    state: started

- name: Add devbox user to docker group
  ansible.builtin.user:
    name: "{{ devbox_user }}"
    groups: docker
    append: true
```

- [ ] **Step 2: Write `kubernetes-tools` role**

```yaml
---
- name: Install kubectl
  ansible.builtin.get_url:
    url: "https://dl.k8s.io/release/{{ kubectl_version }}/bin/linux/amd64/kubectl"
    dest: /usr/local/bin/kubectl
    mode: "0755"

- name: Install flux archive
  ansible.builtin.unarchive:
    src: "https://github.com/fluxcd/flux2/releases/download/v{{ flux_version }}/flux_{{ flux_version }}_linux_amd64.tar.gz"
    dest: /usr/local/bin
    remote_src: true
    include:
      - flux
    mode: "0755"

- name: Install helm archive
  ansible.builtin.unarchive:
    src: "https://get.helm.sh/helm-{{ helm_version }}-linux-amd64.tar.gz"
    dest: /tmp
    remote_src: true
    creates: "/tmp/linux-amd64/helm"

- name: Move helm binary
  ansible.builtin.copy:
    src: /tmp/linux-amd64/helm
    dest: /usr/local/bin/helm
    remote_src: true
    mode: "0755"

- name: Install kustomize archive
  ansible.builtin.unarchive:
    src: "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/{{ kustomize_version }}/kustomize_{{ kustomize_version }}_linux_amd64.tar.gz"
    dest: /usr/local/bin
    remote_src: true
    include:
      - kustomize
    mode: "0755"

- name: Install talosctl
  ansible.builtin.get_url:
    url: "https://github.com/siderolabs/talos/releases/download/{{ talosctl_version }}/talosctl-linux-amd64"
    dest: /usr/local/bin/talosctl
    mode: "0755"
```

- [ ] **Step 3: Write `agents` role**

```yaml
---
- name: Add NodeSource Node.js LTS repository
  ansible.builtin.shell: "curl -fsSL https://deb.nodesource.com/setup_{{ node_major }}.x | bash -"
  args:
    creates: /etc/apt/sources.list.d/nodesource.list

- name: Install Node.js LTS
  ansible.builtin.apt:
    name: nodejs
    state: present
    update_cache: true

- name: Install Go archive
  ansible.builtin.unarchive:
    src: "https://go.dev/dl/go{{ go_version }}.linux-amd64.tar.gz"
    dest: /usr/local
    remote_src: true
    creates: "/usr/local/go/bin/go"

- name: Link go binary
  ansible.builtin.file:
    src: /usr/local/go/bin/go
    dest: /usr/local/bin/go
    state: link
    force: true

- name: Link gofmt binary
  ansible.builtin.file:
    src: /usr/local/go/bin/gofmt
    dest: /usr/local/bin/gofmt
    state: link
    force: true

- name: Install rustup for devbox user
  ansible.builtin.shell: "curl --proto '=https' --tlsv1.2 -sSf {{ rustup_init_url }} | sh -s -- -y"
  args:
    creates: "{{ devbox_home }}/.cargo/bin/rustc"
  become_user: "{{ devbox_user }}"
  environment:
    HOME: "{{ devbox_home }}"

- name: Install Codex CLI
  ansible.builtin.shell: "curl -fsSL {{ codex_install_url }} | CODEX_NON_INTERACTIVE=1 sh"
  args:
    creates: "{{ devbox_home }}/.local/bin/codex"
  become_user: "{{ devbox_user }}"
  environment:
    HOME: "{{ devbox_home }}"

- name: Install Claude Code
  ansible.builtin.shell: "curl -fsSL {{ claude_install_url }} | bash"
  args:
    creates: "{{ devbox_home }}/.local/bin/claude"
  become_user: "{{ devbox_user }}"
  environment:
    HOME: "{{ devbox_home }}"

- name: Link Codex CLI into system path
  ansible.builtin.file:
    src: "{{ devbox_home }}/.local/bin/codex"
    dest: /usr/local/bin/codex
    state: link
    force: true

- name: Link Claude Code into system path
  ansible.builtin.file:
    src: "{{ devbox_home }}/.local/bin/claude"
    dest: /usr/local/bin/claude
    state: link
    force: true

- name: Link rustc into system path
  ansible.builtin.file:
    src: "{{ devbox_home }}/.cargo/bin/rustc"
    dest: /usr/local/bin/rustc
    state: link
    force: true

- name: Link cargo into system path
  ansible.builtin.file:
    src: "{{ devbox_home }}/.cargo/bin/cargo"
    dest: /usr/local/bin/cargo
    state: link
    force: true

- name: Install GitHub CLI from Ubuntu packages
  ansible.builtin.apt:
    name: gh
    state: present
    update_cache: true
```

## Task 6: Add just tasks and docs

**Files:**
- Modify: `justfile`
- Create: `docs/devbox.md`

- [ ] **Step 1: Add just tasks**

Append these recipes to `justfile`:

```just

devbox-ssh:
  ssh devbox

devbox-tmux:
  ssh devbox 'tmux new-session -A -s main'

devbox-converge:
  ansible-playbook -i ansible/devbox/inventory.ini ansible/devbox/playbook.yaml

devbox-check-tmux-config:
  diff -u /Users/stianfroystein/.config/tmux/tmux.conf ansible/devbox/files/tmux.conf

devbox-ansible-ping:
  ansible -i ansible/devbox/inventory.ini devboxes -m ping
```

- [ ] **Step 2: Write `docs/devbox.md`**

Document:

- Purpose and LAN-only access model.
- SSH config example for host `devbox` at `192.168.1.51`.
- First boot flow: reconcile Flux, wait for SSH, run `just devbox-converge`.
- Daily flow: `just devbox-tmux`.
- Manual auth commands: `gh auth login`, `codex login`, `claude`.
- Recovery notes for SSH disconnects, VM reboots, and disk loss.

## Task 7: Validate locally

**Files:**
- All created and modified files.

- [ ] **Step 1: Validate app YAML with yq**

Run: `find apps/devbox ansible/devbox -name '*.yaml' -print0 | xargs -0 -n1 yq e 'true'`

Expected: one `true` per YAML file.

- [ ] **Step 2: Validate app render**

Run: `kustomize build apps/devbox | yq e 'true' -`

Expected: command exits 0 and prints `true`.

- [ ] **Step 3: Validate full cluster render**

Run: `just validate`

Expected: command exits 0 and prints `true`.

- [ ] **Step 4: Validate Ansible syntax**

Run: `ansible-playbook -i ansible/devbox/inventory.ini ansible/devbox/playbook.yaml --syntax-check`

Expected: command exits 0 and prints `playbook: ansible/devbox/playbook.yaml`.

## Task 8: Deploy, converge, and verify runtime

**Files:**
- Runtime cluster state.

- [ ] **Step 1: Apply and reconcile Flux**

Run these commands from the worktree:

```bash
just reconcile
flux reconcile kustomization devbox -n flux-system --with-source
```

Expected: Flux accepts the new `devbox` kustomization.

- [ ] **Step 2: Wait for VM and SSH service**

Run:

```bash
kubectl -n devbox get vm,vmi,svc,pod
kubectl -n devbox wait --for=condition=Ready vmi/devbox --timeout=20m
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new stian@192.168.1.51 'cloud-init status --wait && echo ssh-ready'
```

Expected: VMI is ready and SSH prints `ssh-ready`.

- [ ] **Step 3: Converge Ansible**

Run: `ansible-playbook -i ansible/devbox/inventory.ini ansible/devbox/playbook.yaml`

Expected: playbook exits 0.

- [ ] **Step 4: Verify required tools over SSH**

Run:

```bash
ssh stian@192.168.1.51 'set -e; for bin in fish tmux git gh nvim just yq jq fd kubectl flux helm kustomize talosctl docker codex claude node npm go rustc; do command -v "$bin"; done; docker --version; tmux -V; codex --version; claude --version'
```

Expected: every binary path prints, then version commands print versions.

- [ ] **Step 5: Verify tmux attach path**

Run: `ssh stian@192.168.1.51 'tmux new-session -d -s main || true; tmux has-session -t main'`

Expected: command exits 0.

## Task 9: Commit implementation

**Files:**
- All implementation files.

- [ ] **Step 1: Check worktree status**

Run: `git status --short`

Expected: only intended files are modified or untracked.

- [ ] **Step 2: Stage and commit**

Run:

```bash
git add .gitignore ansible.cfg apps/devbox clusters/talos/apps.yaml ansible/devbox docs/devbox.md justfile docs/superpowers/plans/2026-07-01-devbox-implementation.md
git commit -m "feat(devbox): add persistent agentic devbox"
```

Expected: commit succeeds with a Conventional Commit message.
