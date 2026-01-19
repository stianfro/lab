env:
  direnv allow && direnv export bash > /dev/null

patch:
  just env
  for i in $(ls patches/); do printf '%s\n' "$i" ; talosctl patch machineconfig --patch @patches/$i --endpoints $CP_IPS --nodes $CP_IPS ; done

bootstrap:
  just env
  kubectl apply -k apps/argocd

bootstrap-apps:
  just env
  kubectl apply -f apps/appset.yaml

vnc-ocp-upgrade-lab:
  virtctl vnc ocp-upgrade-lab -n ocp-upgrade-lab --vnc-type=tiger --vnc-path="/Applications/TigerVNC Viewer 1.15.0.app/Contents/MacOS/TigerVNC Viewer"
