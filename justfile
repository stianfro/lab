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

controller-decommission-preflight pattern:
  scripts/controller-decommission-preflight.sh "{{pattern}}"

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

devbox-validate:
  #!/usr/bin/env bash
  set -euo pipefail
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT

  # yq validation for group_vars YAML.
  yq eval -e '(.homebrew_taps | contains(["anomalyco/tap"])) and (.homebrew_packages | contains(["anomalyco/tap/opencode"])) and (.homebrew_binary_links | contains(["opencode"]))' ansible/devbox/group_vars/devboxes.yaml

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
