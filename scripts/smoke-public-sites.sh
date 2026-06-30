#!/usr/bin/env bash
set -euo pipefail

kubectl_text=${KUBECTL:-kubectl}
read -r -a kubectl_cmd <<< "$kubectl_text"

k() {
  "${kubectl_cmd[@]}" "$@"
}

service=${EG_PUBLIC_SERVICE:-http://envoy-envoy-gateway-system-eg-public-7b646a69.envoy-gateway-system.svc.cluster.local:80}
image=${CURL_IMAGE:-curlimages/curl:8.11.1}
pod=${SMOKE_POD_NAME:-lab-public-smoke-$(date +%s)}
if [[ $# -eq 0 ]]; then
  hosts=(froystein.jp blog.froystein.jp www.froystein.jp)
else
  hosts=("$@")
fi

cleanup() {
  k -n default delete pod "$pod" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

cat <<YAML | k apply -f - >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: $pod
  namespace: default
  labels:
    app.kubernetes.io/name: lab-public-smoke
spec:
  restartPolicy: Never
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: smoke
      image: $image
      command: ["sleep", "300"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        runAsNonRoot: true
        runAsUser: 65532
YAML

k -n default wait --for=condition=Ready "pod/$pod" --timeout=90s >/dev/null

echo "Smoke testing public hosts through $service"
for host in "${hosts[@]}"; do
  printf '== %s ==\n' "$host"
  k -n default exec "$pod" -- curl -fsSI -H "Host: $host" "$service" | sed -n '1,8p'
  echo
done
