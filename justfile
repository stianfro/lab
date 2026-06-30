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

vnc-ocp-upgrade-lab:
  virtctl vnc ocp-upgrade-lab -n ocp-upgrade-lab --vnc-type=tiger --vnc-path="/Applications/TigerVNC Viewer 1.15.0.app/Contents/MacOS/TigerVNC Viewer"
