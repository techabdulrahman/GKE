"""Grafana collector: health, firing alerts, optional PromQL checks via datasource proxy."""
import os
import requests
from .models import Finding


def _h():
    h = {"Accept": "application/json"}
    if os.getenv("GRAFANA_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GRAFANA_TOKEN']}"
    return h


PROMQL_CHECKS = [
    ("container restarts (15m)",
     'sum(increase(kube_pod_container_status_restarts_total{namespace="%s"}[15m]))',
     lambda v: v >= 3),
    ("pods not ready",
     'sum(kube_pod_status_ready{namespace="%s",condition="false"})',
     lambda v: v >= 1),
]


def collect(namespace: str) -> list[Finding]:
    base = os.getenv("GRAFANA_URL", "").rstrip("/")
    if not base:
        return [Finding("grafana", "GrafanaNotConfigured", "info", "GRAFANA_URL not set, skipped")]
    out: list[Finding] = []

    try:
        hr = requests.get(f"{base}/api/health", timeout=10)
        if hr.status_code != 200:
            out.append(Finding("grafana", "GrafanaUnhealthy", "warning", f"/api/health {hr.status_code}"))
    except Exception as e:
        return [Finding("grafana", "GrafanaUnreachable", "warning", str(e)[:200])]

    ar = requests.get(f"{base}/api/alertmanager/grafana/api/v2/alerts",
                      params={"active": "true", "silenced": "false", "inhibited": "false"},
                      headers=_h(), timeout=20)
    if ar.status_code == 200:
        for a in ar.json():
            lb, an = a.get("labels", {}), a.get("annotations", {})
            sev = "critical" if lb.get("severity") in ("critical", "page") else "warning"
            out.append(Finding("grafana", "AlertFiring", sev,
                               f"Alert firing: {lb.get('alertname', '?')}",
                               {"labels": lb, "summary": an.get("summary") or an.get("description", ""),
                                "starts_at": a.get("startsAt")}))
    else:
        out.append(Finding("grafana", "GrafanaAuth", "warning",
                           f"Alerts API returned {ar.status_code} (check GRAFANA_TOKEN)"))

    uid = os.getenv("GRAFANA_PROM_UID")
    if uid:
        for name, q, bad in PROMQL_CHECKS:
            try:
                r = requests.get(f"{base}/api/datasources/proxy/uid/{uid}/api/v1/query",
                                 params={"query": q % namespace}, headers=_h(), timeout=20)
                res = r.json()["data"]["result"]
                val = float(res[0]["value"][1]) if res else 0.0
                if bad(val):
                    out.append(Finding("grafana", "MetricThreshold", "warning",
                                       f"{name} = {val:g}", {"query": q % namespace}))
            except Exception as e:
                out.append(Finding("grafana", "MetricQueryFailed", "info", f"{name}: {str(e)[:120]}"))
    return out
