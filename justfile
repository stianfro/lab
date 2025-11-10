env:
  direnv allow && direnv export bash > /dev/null

patch:
  just env
  for i in $(ls patches/); do printf '%s\n' "$i" ; talosctl patch machineconfig --patch @patches/$i --endpoints $CP_IPS --nodes $CP_IPS ; done

