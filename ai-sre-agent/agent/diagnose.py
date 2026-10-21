"""Diagnosis: Gemini first, with deterministic safety rules."""
import json
import os
from .models import Finding, Action, Diagnosis

ALLOWED = {"rollout_undo", "rollout_restart", "none"}


def rule_based(findings: list[Finding], deployment: str) -> Diagnosis:
    kinds = {f.kind for f in findings}

    # Never claim the target is healthy when it cannot be found.
    missing = next((f for f in findings if f.kind == "DeploymentMissing"), None)
    if missing:
        return Diagnosis(
            f"Critical: target Deployment '{deployment}' is missing. "
            "Verify the configured cluster, namespace, and application deployment.",
            "high",
            missing.summary,
            [Action("none", deployment,
                    "Verify and deploy the intended workload; do not restart a missing Deployment.",
                    auto=False)],
            "rules",
        )

    # Any explicit critical finding must take precedence over "All clear".
    critical = [f for f in findings if str(f.severity).lower() == "critical"]
    if critical:
        details = " ".join(f"{f.source}: {f.summary}" for f in critical)
        return Diagnosis(
            "Critical incident detected: " + "; ".join(f.kind for f in critical) + ".",
            "high",
            details,
            [Action("none", deployment,
                    "Investigate the critical findings before remediation.",
                    auto=False)],
            "rules",
        )

    gh_failed = next((f for f in findings if f.kind == "WorkflowFailed"), None)
    gh_ok = next((f for f in findings
                  if f.kind in ("WorkflowSucceeded", "WorkflowRunning")), None)
    alerts = [f for f in findings
              if f.kind in ("AlertFiring", "MetricThreshold")]
    pull = kinds & {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}
    crash = "CrashLoopBackOff" in kinds
    oom = "OOMKilled" in kinds
    degraded = "DeploymentDegraded" in kinds

    corr = []
    if alerts:
        corr.append(
            f"Grafana shows {len(alerts)} alert/metric signal(s) matching pod problems."
        )
    if gh_ok:
        corr.append(
            f"Latest workflow run: {gh_ok.summary} "
            f"(commit {gh_ok.details.get('sha')})."
        )

    if gh_failed and not (pull or crash or oom or degraded):
        return Diagnosis(
            "CI/CD pipeline failed; check whether the previous application revision remains healthy.",
            "medium",
            f"Failed workflow: {gh_failed.details.get('url', gh_failed.summary)}",
            [Action("none", deployment,
                    "Fix the failing workflow step and rerun it.", auto=False)],
            "rules",
        )

    if pull:
        return Diagnosis(
            "Image cannot be pulled; check the image tag, registry access, and image existence.",
            "high",
            " ".join(corr) or "No corroborating signals collected.",
            [Action("rollout_undo", deployment,
                    "Consider rollback after verifying the last known-good revision.")],
            "rules",
        )

    if crash:
        return Diagnosis(
            "Container is repeatedly crashing; inspect startup logs, configuration, and recent releases.",
            "medium",
            " ".join(corr) or "No corroborating signals collected.",
            [Action("rollout_undo", deployment,
                    "Consider rollback if the crash began after a bad release.")],
            "rules",
        )

    if oom:
        return Diagnosis(
            "Container was OOMKilled; investigate memory usage and configured limits.",
            "high",
            " ".join(corr) or "No corroborating signals collected.",
            [Action("none", deployment,
                    "Review memory metrics and limits before making a change.", auto=False)],
            "rules",
        )

    if degraded or alerts:
        return Diagnosis(
            "Deployment degradation or alert signals detected; investigate before selecting a fix.",
            "medium",
            " ".join(corr) or "No corroborating signals collected.",
            [Action("none", deployment,
                    "Investigate the evidence before remediation.", auto=False)],
            "rules",
        )

    # Do not claim full health when Grafana or another source is unavailable.
    unavailable = [f for f in findings if f.kind in {
        "GrafanaNotConfigured", "GrafanaUnavailable",
        "GitHubNotConfigured", "GitHubUnavailable",
    }]
    if unavailable:
        sources = ", ".join(sorted({f.source for f in unavailable}))
        return Diagnosis(
            "Health cannot be fully confirmed because one or more evidence sources are unavailable.",
            "low",
            f"Unavailable evidence: {sources}. No critical workload issue was established by the available findings.",
            [Action("none", deployment,
                    "Restore missing evidence sources and investigate the target workload.", auto=False)],
            "rules",
        )

    # An empty or incomplete evidence set is not proof of health.
    if not findings:
        return Diagnosis(
            "Insufficient evidence to determine workload health.",
            "low",
            "No findings were collected.",
            [Action("none", deployment, "Check collector configuration and workload access.", auto=False)],
            "rules",
        )

    return Diagnosis(
        "No known failure was detected in the collected evidence; this does not prove all systems are healthy.",
        "medium",
        " ".join(corr) or "No corroborating signals collected; verify evidence coverage.",
        [Action("none", deployment, "No remediation proposed.", auto=False)],
        "rules",
    )


PROMPT = """You are an SRE assistant. Below are findings from GKE, GitHub Actions and Grafana.
Correlate the evidence and propose cautious remediation.

Rules:
- Reply with JSON only: {{"root_cause": str, "confidence": "low|medium|high", "correlation": str,
  "actions": [{{"action": "rollout_undo|rollout_restart|none", "reason": str, "auto": bool}}]}}
- Never claim all clear if a critical finding exists or the target Deployment is missing.
- Never claim a source agrees if it is unavailable or was skipped.
- Use only evidence provided. Do not invent evidence.
- Keep remediation conservative. Use auto=false for uncertain or manual actions.
- Be concise (root_cause <= 2 sentences).
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
            contents=PROMPT.format(
                deployment=deployment,
                findings=json.dumps([f.to_dict() for f in findings], indent=1)[:12000],
            ),
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.1
            ),
        )
        data = json.loads(resp.text)
        actions = []
        for action in data.get("actions", []):
            name = action.get("action", "none")
            if name not in ALLOWED:
                continue
            actions.append(Action(
                name, deployment, action.get("reason", ""),
                bool(action.get("auto", False))
            ))
        return Diagnosis(
            data["root_cause"],
            data.get("confidence", "low"),
            data.get("correlation", ""),
            actions or [Action("none", deployment, "No safe action proposed.", False)],
            "gemini",
        )
    except Exception as e:
        print(f"[gemini unavailable, using rules] {str(e)[:150]}")
        return None


def diagnose(findings: list[Finding], deployment: str, use_llm: bool = True) -> Diagnosis:
    # Safety gate: deterministic rules always handle critical/missing/unavailable evidence.
    safety_kinds = {
        "DeploymentMissing", "GrafanaNotConfigured", "GrafanaUnavailable",
        "GitHubNotConfigured", "GitHubUnavailable",
    }
    has_critical = any(str(f.severity).lower() == "critical" for f in findings)
    if has_critical or any(f.kind in safety_kinds for f in findings):
        return rule_based(findings, deployment)

    if use_llm:
        result = gemini(findings, deployment)
        if result:
            return result
    return rule_based(findings, deployment)
