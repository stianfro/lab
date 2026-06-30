#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <controller-name-or-regex>" >&2
  echo "example: $0 kargo" >&2
  exit 2
fi

pattern=$1
kubectl_text=${KUBECTL:-kubectl}
read -r -a kubectl_cmd <<< "$kubectl_text"

k() {
  "${kubectl_cmd[@]}" "$@"
}

print_matches() {
  local title=$1
  shift
  echo "== $title =="
  if ! "$@" | grep -Ei "$pattern"; then
    echo "(none)"
  fi
  echo
}

finalizer_query='.items[] | select((.metadata.finalizers // []) | join(",") | test("(?i)" + strenv(PATTERN))) | ((.metadata.namespace // "<cluster>") + "/" + .metadata.name + " finalizers=" + ((.metadata.finalizers // []) | join(",")))'
owner_query='.items[] | select((.metadata.ownerReferences // []) | to_json | test("(?i)" + strenv(PATTERN))) | ((.metadata.namespace // "<cluster>") + "/" + .metadata.name + " owners=" + ((.metadata.ownerReferences // []) | to_json))'

print_resource_scan() {
  local title=$1
  local scope=$2
  local query=$3
  local tmp
  tmp=$(mktemp)

  echo "== $title =="
  if [[ "$scope" == "namespaced" ]]; then
    while IFS= read -r resource; do
      [[ -n "$resource" ]] || continue
      PATTERN=$pattern k get "$resource" -A -o json 2>/dev/null | PATTERN=$pattern yq -r "$query" 2>/dev/null | sed "s#^#$resource #" >> "$tmp" || true
    done < <(k api-resources --verbs=list --namespaced -o name)
  else
    while IFS= read -r resource; do
      [[ -n "$resource" ]] || continue
      [[ "$resource" == "namespaces" ]] && continue
      PATTERN=$pattern k get "$resource" -o json 2>/dev/null | PATTERN=$pattern yq -r "$query" 2>/dev/null | sed "s#^#$resource #" >> "$tmp" || true
    done < <(k api-resources --verbs=list --namespaced=false -o name)
  fi

  if [[ -s "$tmp" ]]; then
    cat "$tmp"
  else
    echo "(none)"
  fi
  rm -f "$tmp"
  echo
}

print_namespace_scan() {
  local title=$1
  local query=$2

  echo "== $title =="
  if ! PATTERN=$pattern k get ns -o json 2>/dev/null | PATTERN=$pattern yq -r "$query" 2>/dev/null; then
    echo "(scan failed)"
  fi
  if ! PATTERN=$pattern k get ns -o json 2>/dev/null | PATTERN=$pattern yq -r "$query" 2>/dev/null | grep -q .; then
    echo "(none)"
  fi
  echo
}

cat <<MSG
Controller decommission preflight for pattern: $pattern

Use this before removing a controller namespace, webhook, or CRD.
CRDs should be deleted last, after custom resources and finalizers are accounted for.

MSG

print_matches "CRDs matching pattern" k get crd
print_matches "API resources matching pattern" k api-resources
print_matches "webhooks matching pattern" k get validatingwebhookconfiguration,mutatingwebhookconfiguration
print_matches "namespaces with matching names" k get ns

print_namespace_scan "namespaces with matching finalizers" "$finalizer_query"
print_resource_scan "cluster-scoped resources with matching finalizers" cluster "$finalizer_query"
print_resource_scan "namespaced resources with matching finalizers" namespaced "$finalizer_query"
print_resource_scan "cluster-scoped resources with matching owner references" cluster "$owner_query"
print_resource_scan "namespaced resources with matching owner references" namespaced "$owner_query"
