"""AI SRE agent: observe (GKE + GitHub Actions + Grafana) -> diagnose (Gemini/rules) -> remediate."""
import argparse
import json
import os
import time
from datetime import datetime, timezone

from . import collectors_gke, collectors_github, collectors_grafana, diagnose, remediate

ICON = {"critical": "[CRIT]", "warning": "[WARN]", "info": "[ info]"}


def once(a) -> dict:
    findings = []
    for name, fn in (("gke", lambda: collectors_gke.collect(a.namespace, a.deployment)),
                     ("github", lambda: collectors_github.collect(a.repo, a.workflow)),
                     ("grafana", lambda: collectors_grafana.collect(a.namespace))):
        try:
            findings += fn()
        except Exception as e:                      # one broken source must not stop the agent
            from .models import Finding
            findings.append(Finding(name, "CollectorError", "warning", f"{name} collector failed: {str(e)[:150]}"))

    print(f"\n=== AI SRE run @ {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z ===")
    print("\n1) OBSERVE")
    for f in findings:
        print(f"  {ICON[f.severity]} {f.source:<8} {f.summary}")

    unhealthy = any(f.severity in ("critical", "warning") for f in findings)
    d = diagnose.diagnose(findings, a.deployment, use_llm=not a.no_llm)

    print(f"\n2) DIAGNOSE  (engine: {d.engine}, confidence: {d.confidence})")
    print(f"  root cause : {d.root_cause}")
    print(f"  correlation: {d.correlation}")

    print("\n3) REMEDIATE" + ("" if a.apply else "  (dry-run)"))
    results = []
    for act in (d.actions if unhealthy else []):
        res = remediate.run(act, a.namespace, {a.deployment}, a.apply)
        results.append({**act.to_dict(), "result": res})
        print(f"  {act.action:<16} -> {res}\n    why: {act.reason}")
    if not unhealthy:
        print("  nothing to do, system healthy")

    report = {"time": datetime.now(timezone.utc).isoformat(), "findings": [f.to_dict() for f in findings],
              "diagnosis": d.to_dict(), "remediation": results}
    with open(a.report, "w") as fh:
        json.dump(report, fh, indent=2)
    return report


def main():
    p = argparse.ArgumentParser(description="AI SRE agent for GKE + GitHub Actions + Grafana")
    p.add_argument("--namespace", default=os.getenv("K8S_NAMESPACE", "ai-troubleshooter"))
    p.add_argument("--deployment", default=os.getenv("K8S_DEPLOYMENT", "ai-k8s-demo"))
    p.add_argument("--repo", default=os.getenv("GITHUB_REPO", "techabdulrahman/gcpkubernetes"))
    p.add_argument("--workflow", default=os.getenv("GITHUB_WORKFLOW", "deploy.yml"))
    p.add_argument("--apply", action="store_true", help="actually execute remediation (default: dry-run)")
    p.add_argument("--no-llm", action="store_true", help="rule-based diagnosis only")
    p.add_argument("--watch", type=int, default=0, metavar="SEC", help="loop every SEC seconds")
    p.add_argument("--report", default="report.json")
    a = p.parse_args()
    while True:
        once(a)
        if not a.watch:
            break
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
