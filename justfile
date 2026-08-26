env:
  direnv allow && direnv export bash > /dev/null

patch:
  just env
  for i in $(ls talos/patches/); do printf '%s\n' "$i" ; talosctl patch machineconfig --patch @talos/patches/$i --endpoints $CP_IPS --nodes $CP_IPS ; done

bootstrap:
  just env
  kubectl apply -f clusters/talos/flux-system/gotk-components.yaml
  kubectl wait --for=condition=Established crd/gitrepositories.source.toolkit.fluxcd.io crd/kustomizations.kustomize.toolkit.fluxcd.io --timeout=60s
  kubectl -n flux-system rollout status deployment/source-controller
  kubectl -n flux-system rollout status deployment/kustomize-controller
  kubectl -n flux-system rollout status deployment/helm-controller
  kubectl apply -f clusters/talos/flux-system/gotk-sync.yaml

reconcile:
  just env
  flux reconcile kustomization cluster -n flux-system --with-source

validate:
  kustomize build clusters/talos | yq e 'true' -

guest-vm-validate:
  #!/usr/bin/env bash
  set -euo pipefail
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  while IFS= read -r -d '' yaml_file; do
    yq eval '.' "$yaml_file" >/dev/null
  done < <(find apps/guest-vm -name '*.yaml' -print0 | sort -z)

  bash -n scripts/guest-vm-configure.sh

  cloud_init_template="$(
    yq eval-all -r \
      'select(.kind == "VaultStaticSecret" and .metadata.name == "guest-vm-cloud-init") | .spec.destination.transformation.templates.userdata.text' \
      apps/guest-vm/vaultstaticsecrets.yaml
  )"
  owner_public_key="$(
    printf '%s\n' "$cloud_init_template" \
      | yq -r '.users[] | select(.name == "stian") | .ssh_authorized_keys[]'
  )"
  left_brace='{'
  right_brace='}'
  guest_key_placeholder="${left_brace}${left_brace} .Secrets.guest_ssh_public_key ${right_brace}${right_brace}"
  cloud_init="${cloud_init_template//$guest_key_placeholder/$owner_public_key}"
  printf '%s\n' "$cloud_init" | yq eval '.' - >/dev/null

  while IFS= read -r public_key; do
    printf '%s\n' "$public_key" | ssh-keygen -lf - >/dev/null
  done < <(
    printf '%s\n' "$cloud_init" \
      | yq -r '.users[].ssh_authorized_keys[]'
  )

  kustomize build apps/guest-vm > "$tmpdir/rendered.yaml"
  yq eval 'true' "$tmpdir/rendered.yaml" >/dev/null

  yq eval -e '
    select(.kind == "CiliumNetworkPolicy" and .metadata.name == "guest-vm")
    | .spec.ingress[]
    | .fromEndpoints[]?
    | select(
        .matchLabels."k8s:io.kubernetes.pod.namespace" == "kubevirt"
        and .matchLabels."k8s:kubevirt.io" == "virt-api"
      )
  ' "$tmpdir/rendered.yaml" >/dev/null

  yq eval -e '
    select(.kind == "VirtualMachine" and .metadata.name == "guest-vm")
    | .spec.template.spec
    | select(
        .dnsPolicy == "None"
        and .dnsConfig.nameservers[0] == "1.1.1.1"
        and .dnsConfig.nameservers[1] == "1.0.0.1"
      )
  ' "$tmpdir/rendered.yaml" >/dev/null

  validation_namespace=kube-system
  yq eval 'select(.kind == "Namespace")' "$tmpdir/rendered.yaml" > "$tmpdir/namespace.yaml"
  VALIDATION_NAMESPACE="$validation_namespace" \
    yq eval 'select(.kind != "Namespace") | .metadata.namespace = strenv(VALIDATION_NAMESPACE)' \
    "$tmpdir/rendered.yaml" > "$tmpdir/namespaced.yaml"
  kubectl apply --server-side --dry-run=server --validate=strict \
    -f "$tmpdir/namespace.yaml" >/dev/null
  kubectl apply --server-side --dry-run=server --validate=strict \
    -f "$tmpdir/namespaced.yaml" >/dev/null

guest-vm-configure *args:
  scripts/guest-vm-configure.sh {{args}}

guest-vm-deploy:
  #!/usr/bin/env bash
  set -euo pipefail
  just reconcile
  flux reconcile kustomization guest-vm -n flux-system --with-source
  kubectl -n guest-vm wait \
    --for=condition=Healthy=True \
    vaultstaticsecret/guest-vm-vpn \
    vaultstaticsecret/guest-vm-wireguard \
    vaultstaticsecret/guest-vm-cloud-init \
    vaultstaticsecret/guest-vm-connection \
    --timeout=5m
  kubectl -n guest-vm rollout status deployment/guest-vm-gateway --timeout=10m
  kubectl -n guest-vm wait \
    --for=jsonpath='{.status.phase}'=Succeeded \
    datavolume/guest-vm-root \
    --timeout=20m
  vmi_deadline=$((SECONDS + 600))
  until kubectl -n guest-vm get vmi/guest-vm >/dev/null 2>&1; do
    if ((SECONDS >= vmi_deadline)); then
      printf 'Timed out while waiting for vmi/guest-vm to be created.\n' >&2
      exit 1
    fi
    sleep 5
  done
  kubectl -n guest-vm wait --for=condition=Ready vmi/guest-vm --timeout=10m
  just guest-vm-status

guest-vm-setup *args:
  just guest-vm-configure {{args}}
  just guest-vm-deploy

guest-vm-status:
  #!/usr/bin/env bash
  set -euo pipefail
  kubectl -n guest-vm get vm,vmi,dv,pvc,deployment,pod
  kubectl -n guest-vm exec deployment/guest-vm-gateway -c outer-vpn -- \
    /gluetun-entrypoint healthcheck
  kubectl -n guest-vm exec deployment/guest-vm-gateway -c wireguard -- \
    wg show wg0

guest-vm-owner-ssh *args:
  virtctl ssh stian@vm/guest-vm/guest-vm {{args}}

guest-vm-connection:
  #!/usr/bin/env bash
  set -euo pipefail
  secret=guest-vm-connection
  namespace=guest-vm
  read_value() {
    kubectl -n "$namespace" get secret "$secret" \
      -o "jsonpath={.data.${1}}" | base64 --decode
  }
  endpoint="$(read_value endpoint)"
  port="$(read_value forwarded_port)"
  public_key="$(read_value server_public_key)"
  printf 'Endpoint: %s:%s\n' "$endpoint" "$port"
  printf 'Server public key: %s\n' "$public_key"
  printf 'Server tunnel address: 10.203.77.1/32\n'
  printf 'Remote tunnel address: 10.203.77.2/32\n'
  printf '\nWireGuard client configuration:\n'
  cat <<EOF
  [Interface]
  PrivateKey = <set-on-remote-device>
  Address = 10.203.77.2/32

  [Peer]
  PublicKey = $public_key
  Endpoint = $endpoint:$port
  AllowedIPs = 10.203.77.1/32
  PersistentKeepalive = 25
  EOF

# Re-render the Talos Cilium bootstrap manifest from the Flux HelmRelease
# chart version and values. Helm-generated TLS Secrets are stripped: the
# repo is public and the Flux HelmRelease owns those secrets in the live
# cluster. Never kubectl apply the result; Flux owns the live objects.
render-cilium-bootstrap:
  #!/usr/bin/env bash
  set -euo pipefail
  version="$(yq '.spec.chart.spec.version' apps/cilium/helmrelease.yaml)"
  values="$(mktemp)"
  trap 'rm -f "$values"' EXIT
  yq '.spec.values' apps/cilium/helmrelease.yaml > "$values"
  helm repo add cilium https://helm.cilium.io >/dev/null 2>&1 || true
  helm repo update cilium >/dev/null
  helm template cilium cilium/cilium --version "$version" --namespace kube-system \
    --values "$values" | yq 'select(.kind != "Secret")' > talos/manifests/cilium.yaml
  yq -N 'select(.kind=="DaemonSet" or .kind=="Deployment" or (.kind=="ConfigMap" and .metadata.name=="cilium-config")) | .kind + "/" + .metadata.name' talos/manifests/cilium.yaml

controller-decommission-preflight pattern:
  scripts/controller-decommission-preflight.sh "{{pattern}}"

# Upgrade one Talos node. Use a talosctl client that matches the SERVER
# version (newer clients kill the long upgrade RPC against older apid),
# and pass the IP of a node that is NOT being upgraded as endpoint via
# TALOS_ENDPOINT (defaults to 192.168.1.100). See docs/talos-upgrade.md.
upgrade-node ip version:
  just env
  direnv exec . talosctl --endpoints ${TALOS_ENDPOINT:-192.168.1.100} --nodes {{ip}} upgrade --image factory.talos.dev/installer/cb120f5908d584b52477963c9d095efa80750f4e4fdc48190eb68730cb749448:{{version}}

# Upgrade Kubernetes across the cluster, one minor at a time. Read the
# bootstrap-manifest pruning warning in docs/talos-upgrade.md first.
upgrade-k8s to:
  just env
  direnv exec . talosctl --nodes 192.168.1.100 upgrade-k8s --to {{to}}

smoke-public-sites:
  scripts/smoke-public-sites.sh

devbox_host := "192.168.1.51"
devbox_hostname := "devbox"
devbox_user := "stian"
devbox_ssh_target := devbox_user + "@" + devbox_host
devbox_ssh_control_path := ".cache/ssh/devbox-%C"
devbox_browser_bridge_port := "48765"
devbox_browser_bridge_forward := "127.0.0.1:" + devbox_browser_bridge_port + ":127.0.0.1:" + devbox_browser_bridge_port
devbox_mac_relay_port := "48767"
devbox_mac_relay_forward := "127.0.0.1:" + devbox_mac_relay_port
devbox_opencode_web_port := "4096"

vnc-ocp-upgrade-lab:
  virtctl vnc ocp-upgrade-lab -n ocp-upgrade-lab --vnc-type=tiger --vnc-path="/Applications/TigerVNC Viewer 1.15.0.app/Contents/MacOS/TigerVNC Viewer"

devbox-ssh:
  mkdir -p .cache/ssh
  scripts/devbox-browser-bridge.py --target {{devbox_ssh_target}} --port {{devbox_browser_bridge_port}} --ssh-control-path {{devbox_ssh_control_path}} -- ssh -S {{devbox_ssh_control_path}} -o ControlMaster=auto -o ExitOnForwardFailure=no -R {{devbox_browser_bridge_forward}} -R {{devbox_mac_relay_forward}} {{devbox_ssh_target}}

devbox-tmux:
  mkdir -p .cache/ssh
  scripts/devbox-browser-bridge.py --target {{devbox_ssh_target}} --port {{devbox_browser_bridge_port}} --ssh-control-path {{devbox_ssh_control_path}} -- ssh -t -S {{devbox_ssh_control_path}} -o ControlMaster=auto -o ExitOnForwardFailure=no -R {{devbox_browser_bridge_forward}} -R {{devbox_mac_relay_forward}} {{devbox_ssh_target}} 'tmux new-session -A -s main'

devbox-herdr:
  mkdir -p .cache/ssh
  scripts/devbox-browser-bridge.py --target {{devbox_ssh_target}} --port {{devbox_browser_bridge_port}} --ssh-control-path {{devbox_ssh_control_path}} -- ssh -t -S {{devbox_ssh_control_path}} -o ControlMaster=auto -o ExitOnForwardFailure=no -R {{devbox_browser_bridge_forward}} -R {{devbox_mac_relay_forward}} {{devbox_ssh_target}} 'herdr'

devbox-relay:
  ssh -N -o ExitOnForwardFailure=yes -R {{devbox_mac_relay_forward}} {{devbox_ssh_target}}

devbox-sync-personal-config:
  DEVBOX_SSH_TARGET={{devbox_ssh_target}} scripts/devbox-sync-personal-config.sh

devbox-converge:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(hostname -s)" == "{{devbox_hostname}}" ]]; then
    just devbox-converge-local
  else
    mkdir -p .cache/ansible/tmp
    ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible ansible-playbook -i ansible/devbox/inventory.ini ansible/devbox/playbook.yaml
  fi

_devbox-local-inventory:
  mkdir -p .cache/ansible/tmp .cache/uv
  printf '%s\n' '[devboxes]' 'devbox ansible_connection=local ansible_python_interpreter=/usr/bin/python3' > .cache/ansible/local-inventory.ini

devbox-converge-local: _devbox-local-inventory
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible UV_CACHE_DIR=.cache/uv uvx --from ansible-core ansible-playbook -i .cache/ansible/local-inventory.ini ansible/devbox/playbook.yaml

devbox-converge-local-base: _devbox-local-inventory
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible UV_CACHE_DIR=.cache/uv uvx --from ansible-core ansible-playbook -i .cache/ansible/local-inventory.ini ansible/devbox/playbook.yaml --tags base

devbox-converge-local-tailscale: _devbox-local-inventory
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible UV_CACHE_DIR=.cache/uv uvx --from ansible-core ansible-playbook -i .cache/ansible/local-inventory.ini ansible/devbox/playbook.yaml --tags tailscale

devbox-validate:
  #!/usr/bin/env bash
  set -euo pipefail
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  # yq validation for group_vars YAML.
  yq eval -e '(.homebrew_taps | contains(["anomalyco/tap"])) and (.homebrew_packages | contains(["anomalyco/tap/opencode", "gh"])) and (.homebrew_binary_links | contains(["opencode", "gh"])) and (. | has("opencode2_version"))' ansible/devbox/group_vars/devboxes.yaml

  # yq validation for every YAML file under ansible/.
  while IFS= read -r -d '' yfile; do
    yq eval '.' "$yfile" >/dev/null
  done < <(find ansible/ \( -name '*.yaml' -o -name '*.yml' \) -print0 | sort -z)

  # jq validation for managed agent-browser config JSON.
  jq '.' ansible/devbox/roles/agent-browser/files/config.json >/dev/null

  # Python compile check for MCP checker without repository cache files.
  python3 -c 'import py_compile; py_compile.compile("scripts/devbox-agent-browser-mcp-check.py", cfile="'"$tmpdir"'/devbox-agent-browser-mcp-check.pyc", doraise=True)'

  # shellcheck for agent-browser wrapper and changed shell scripts.
  shellcheck \
    ansible/devbox/roles/agent-browser/files/agent-browser-wrapper \
    scripts/devbox-agent-browser-check.sh \
    scripts/devbox-sync-personal-config.sh

  # Generate and parse the personal Codex configuration without a remote sync.
  mkdir -p "$tmpdir/home/.codex"
  printf '%s\n' 'model = "gpt-5.6-sol"' > "$tmpdir/home/.codex/config.toml"
  HOME="$tmpdir/home" DEVBOX_SYNC_CODEX_OUTPUT="$tmpdir/codex.toml" \
    scripts/devbox-sync-personal-config.sh
  python3 - "$tmpdir/codex.toml" <<'PY'
  from pathlib import Path
  import sys
  import tomllib

  toml_path = Path(sys.argv[1])
  cfg = tomllib.loads(toml_path.read_text())
  ab = cfg.get("mcp_servers", {}).get("agent-browser", {})
  assert ab.get("command") == "/usr/local/bin/agent-browser", f"command mismatch: {ab.get('command')}"
  assert ab.get("args") == ["mcp", "--tools", "core"], f"args mismatch: {ab.get('args')}"
  print("Codex TOML validation passed")
  PY

  # Ansible syntax check.
  mkdir -p .cache/ansible/tmp .cache/uv
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible UV_CACHE_DIR=.cache/uv uvx --from ansible-core ansible-playbook -i ansible/devbox/inventory.ini ansible/devbox/playbook.yaml --syntax-check

devbox-opencode-web-info:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(hostname -s)" != "{{devbox_hostname}}" ]]; then
    printf '%s\n' 'This recipe must be run on devbox.' >&2
    exit 1
  fi
  credentials="$HOME/.config/opencode/web.env"
  printf 'URL: http://%s:%s\n' '{{devbox_hostname}}' '{{devbox_opencode_web_port}}'
  printf 'Status: %s\n' "$(systemctl is-active opencode-web.service || true)"
  printf 'Username: %s\n' "$(sed -n 's/^OPENCODE_SERVER_USERNAME=//p' "$credentials")"
  printf 'Password: %s\n' "$(sed -n 's/^OPENCODE_SERVER_PASSWORD=//p' "$credentials")"

devbox-check-tmux-config:
  diff -u /Users/stianfroystein/.config/tmux/tmux.conf ansible/devbox/files/tmux.conf

devbox-agent-browser-check:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(hostname -s)" != "{{devbox_hostname}}" ]]; then
    printf '%s\n' 'This recipe must be run on devbox.' >&2
    exit 1
  fi
  scripts/devbox-agent-browser-check.sh

devbox-agent-browser-dashboard:
  #!/usr/bin/env bash
  set -euo pipefail
  if [[ "$(hostname -s)" != "{{devbox_hostname}}" ]]; then
    printf '%s\n' 'This recipe must be run on devbox.' >&2
    exit 1
  fi
  lsof -ti :4848 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  /usr/local/bin/agent-browser dashboard start --port 4848
  if ! ss -ltn 'sport = :4848' | grep -q '127.0.0.1:4848'; then
    printf '%s\n' 'Dashboard did not bind to 127.0.0.1:4848.' >&2
    exit 1
  fi
  devbox-browser http://localhost:4848

devbox-agent-browser-dashboard-stop:
  #!/usr/bin/env bash
  set -euo pipefail
  lsof -ti :4848 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true

devbox-ansible-ping:
  mkdir -p .cache/ansible/tmp
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible ansible -i ansible/devbox/inventory.ini devboxes -m ping

frr-router-converge:
  mkdir -p .cache/ansible/tmp .cache/uv
  ANSIBLE_LOCAL_TEMP=.cache/ansible/tmp ANSIBLE_HOME=.cache/ansible UV_CACHE_DIR=.cache/uv uvx --from ansible-core ansible-playbook -i ansible/frr-router/inventory.ini ansible/frr-router/playbook.yaml

bench:
  python3 scripts/bench/run.py balanced

bench-quick:
  python3 scripts/bench/run.py quick

bench-thorough:
  python3 scripts/bench/run.py thorough

bench-cold:
  python3 scripts/bench/run.py cold

bench-doctor:
  python3 scripts/bench/run.py doctor

bench-compare left right:
  python3 scripts/bench/compare.py "{{left}}" "{{right}}"

bench-clean:
  rm -rf .cache/bench
