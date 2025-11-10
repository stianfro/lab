env:
  direnv allow && direnv export bash > /dev/null

patch:
  just env
  for i in $(ls patches/); do talosctl patch machineconfig --patch @patches/$i --endpoints $CP_IPS --nodes $CP_IPS ; done

