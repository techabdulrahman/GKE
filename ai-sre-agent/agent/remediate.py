"""Guard-railed remediation. Dry-run unless apply=True."""
import subprocess
from .models import Action


def run(action: Action, namespace: str, allowed_deployments: set[str], apply: bool) -> str:
    if action.action == "none" or not action.auto:
        return "advice only, nothing executed"
    if action.target not in allowed_deployments:
        return f"BLOCKED: {action.target} not in allow-list"
    cmd = ["kubectl", "-n", namespace, "rollout",
           "undo" if action.action == "rollout_undo" else "restart", f"deployment/{action.target}"]
    if not apply:
        return "DRY-RUN: would run `" + " ".join(cmd) + "` (use --apply)"
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    status = subprocess.run(["kubectl", "-n", namespace, "rollout", "status",
                             f"deployment/{action.target}", "--timeout=120s"],
                            capture_output=True, text=True, timeout=150)
    return f"EXECUTED: {p.stdout.strip() or p.stderr.strip()} | {status.stdout.strip() or status.stderr.strip()}"
