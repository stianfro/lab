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

vnc-ocp-upgrade-lab:
  virtctl vnc ocp-upgrade-lab -n ocp-upgrade-lab --vnc-type=tiger --vnc-path="/Applications/TigerVNC Viewer 1.15.0.app/Contents/MacOS/TigerVNC Viewer"

devbox-ssh:
  ssh {{devbox_ssh_target}}

devbox-tmux:
  ssh {{devbox_ssh_target}} 'tmux new-session -A -s main'

devbox-sync-personal-config:
  DEVBOX_SSH_TARGET={{devbox_ssh_target}} scripts/devbox-sync-personal-config.sh

backup-personal-config:
  scripts/personal-config-backup.sh

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

devbox-check-tmux-config:
  diff -u /Users/stianfroystein/.config/tmux/tmux.conf ansible/devbox/files/tmux.conf

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
