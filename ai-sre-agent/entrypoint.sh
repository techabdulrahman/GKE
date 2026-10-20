#!/bin/sh
set -eu

if [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
    umask 077
    cat > /tmp/kubeconfig <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    server: https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT_HTTPS:-443}
  name: in-cluster
contexts:
- context:
    cluster: in-cluster
    user: in-cluster
  name: in-cluster
current-context: in-cluster
users:
- name: in-cluster
  user:
    tokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token
EOF
    export KUBECONFIG=/tmp/kubeconfig
fi

exec "$@"
