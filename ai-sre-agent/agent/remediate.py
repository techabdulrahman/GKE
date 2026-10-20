"""Guard-railed remediation. Dry-run unless apply=True."""
import subprocess
from .models import Action


def run(action: Action, namespace: str, allowed_deployments: set[str], apply: bool) -> str:
    if action.action == "none" or not action.auto:
        return "advice only, nothing executed"
    if action.action not in {"rollout_undo", "rollout_restart"}:
        return f"BLOCKED: unsupported action {action.action}"
    if action.target not in allowed_deployments:
        return f"BLOCKED: {action.target} not in allow-list"
    cmd = ["kubectl", "-n", namespace, "rollout",
           action.action.removeprefix("rollout_"), f"deployment/{action.target}"]
    if not apply:
        return "DRY-RUN: would run `" + " ".join(cmd) + "` (use --apply)"
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if p.returncode:
        return f"FAILED remediation (exit {p.returncode}): {p.stderr.strip() or p.stdout.strip()}"
    status = subprocess.run(["kubectl", "-n", namespace, "rollout", "status",
                             f"deployment/{action.target}", "--timeout=120s"],
                            capture_output=True, text=True, timeout=150)
    if status.returncode:
        return f"FAILED verification (exit {status.returncode}): {status.stderr.strip() or status.stdout.strip()}"
    return f"VERIFIED recovered: {status.stdout.strip()}"
