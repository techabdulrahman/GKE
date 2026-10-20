#!/usr/bin/env bash
# Demo: simulate a bad release (image tag that does not exist) -> ImagePullBackOff
NS=${K8S_NAMESPACE:-ai-troubleshooter}; D=${K8S_DEPLOYMENT:-ai-k8s-demo}
kubectl -n "$NS" set image deploy/"$D" "$D"=nginxinc/nginx-unprivileged:does-not-exist
kubectl -n "$NS" get pods
