"""Diagnosis: Gemini first, deterministic rule-based fallback."""
import json
import os
from .models import Finding, Action, Diagnosis

ALLOWED = {"rollout_undo", "rollout_restart", "none"}


# ---------------------------------------------------------------- rules
def rule_based(findings: list[Finding], deployment: str) -> Diagnosis:
    kinds = {f.kind for f in findings}
    gh_failed = next((f for f in findings if f.kind == "WorkflowFailed"), None)
    gh_ok = next((f for f in findings if f.kind in ("WorkflowSucceeded", "WorkflowRunning")), None)
    alerts = [f for f in findings if f.kind in ("AlertFiring", "MetricThreshold")]
    pull = kinds & {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}
    crash = "CrashLoopBackOff" in kinds
    oom = "OOMKilled" in kinds
    degraded = "DeploymentDegraded" in kinds
    corr = []
    if alerts:
        corr.append(f"Grafana shows {len(alerts)} alert/metric signal(s) matching the pod problems.")
    if gh_ok:
        corr.append(f"Latest workflow run: {gh_ok.summary.lower()} (commit {gh_ok.details.get('sha')}), "
                    "so a recent release is the prime suspect.")

    if gh_failed and not (pull or crash or oom or degraded):
        return Diagnosis("CI/CD pipeline failed; cluster still healthy on previous revision.",
                         "high", f"Run {gh_failed.details.get('url')} failed; GKE is unaffected.",
                         [Action("none", deployment, "Fix the failing workflow step and re-run.", auto=False)],
                         "rules")
    if pull:
        return Diagnosis("Image cannot be pulled (bad tag, missing image or registry permissions).",
                         "high", " ".join(corr) or "No other signals.",
                         [Action("rollout_undo", deployment, "Roll back to the last working image.")], "rules")
    if crash:
        return Diagnosis("Container crashes on startup (bad config, bad release or missing dependency).",
                         "medium", " ".join(corr) or "No other signals.",
                         [Action("rollout_undo", deployment, "Roll back to the previous revision.")], "rules")
    if oom:
        return Diagnosis("Container exceeds its memory limit.", "high", " ".join(corr) or "No other signals.",
                         [Action("none", deployment, "Raise resources.limits.memory in k8s/deployment.yaml "
                                 "via a PR (not auto-fixed).", auto=False)], "rules")
    if degraded or alerts:
        return Diagnosis("Deployment degraded or alerts firing without a clear pod-level cause.", "low",
                         " ".join(corr) or "No other signals.",
                         [Action("rollout_restart", deployment, "Restart pods as a low-risk first step.")], "rules")
    return Diagnosis("All clear: no failing pods, no failed deploys, no firing alerts.", "high",
                     "GKE, GitHub Actions and Grafana agree.", [Action("none", deployment, "Nothing to do.", auto=False)],
                     "rules")


# --------------------------------------------------------------- gemini
PROMPT = """You are an SRE assistant. Below are findings from three sources: GKE (kubernetes),
GitHub Actions (CI/CD) and Grafana (alerts/metrics). Correlate them, find the most likely root cause
and propose remediation.

Rules:
- Reply with JSON only: {{"root_cause": str, "confidence": "low|medium|high", "correlation": str,
  "actions": [{{"action": "rollout_undo|rollout_restart|none", "reason": str, "auto": bool}}]}}
- Only these actions exist. Use rollout_undo for bad releases (image pull errors, crash loops right
  after a deploy). Use rollout_restart only for transient issues. For OOMKilled, config or capacity
  problems use action "none" with auto=false and explain the manual fix.
- Be concise (root_cause <= 2 sentences). Do not invent evidence.
- The target deployment is "{deployment}".

FINDINGS:
{findings}
"""


def gemini(findings: list[Finding], deployment: str) -> Diagnosis | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=PROMPT.format(deployment=deployment,
                                   findings=json.dumps([f.to_dict() for f in findings], indent=1)[:12000]),
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
        )
        data = json.loads(resp.text)
        actions = []
        for a in data.get("actions", []):
            name = a.get("action", "none")
            if name not in ALLOWED:          # guardrail: never run anything off-list
                continue
            actions.append(Action(name, deployment, a.get("reason", ""), bool(a.get("auto", True))))
        return Diagnosis(data["root_cause"], data.get("confidence", "low"),
                         data.get("correlation", ""), actions or [Action("none", deployment, "No action", False)],
                         "gemini")
    except Exception as e:
        print(f"[gemini unavailable, using rules] {str(e)[:150]}")
        return None


def diagnose(findings: list[Finding], deployment: str, use_llm: bool = True) -> Diagnosis:
    if use_llm:
        d = gemini(findings, deployment)
        if d:
            return d
    return rule_based(findings, deployment)
