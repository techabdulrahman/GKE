"""GitHub Actions collector: latest runs of the deploy workflow + failed step logs."""
import os
import requests
from .models import Finding

API = "https://api.github.com"


def _h():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if os.getenv("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return h


def collect(repo: str, workflow: str) -> list[Finding]:
    out: list[Finding] = []
    r = requests.get(f"{API}/repos/{repo}/actions/workflows/{workflow}/runs",
                     params={"per_page": 5}, headers=_h(), timeout=20)
    if r.status_code != 200:
        return [Finding("github", "GitHubUnreachable", "warning",
                        f"GitHub API returned {r.status_code}", {"body": r.text[:200]})]
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return [Finding("github", "NoRuns", "info", f"No runs found for {workflow}")]

    latest = runs[0]
    info = {"run_id": latest["id"], "sha": latest["head_sha"][:7], "branch": latest["head_branch"],
            "actor": (latest.get("actor") or {}).get("login"), "url": latest["html_url"],
            "created_at": latest["created_at"], "status": latest["status"],
            "recent": [f'{x["head_sha"][:7]}:{x["conclusion"] or x["status"]}' for x in runs]}

    if latest["status"] != "completed":
        out.append(Finding("github", "WorkflowRunning", "info",
                           f"Deploy run #{latest['run_number']} in progress", info))
    elif latest["conclusion"] == "success":
        out.append(Finding("github", "WorkflowSucceeded", "info",
                           f"Latest deploy run #{latest['run_number']} succeeded", info))
    else:
        info["conclusion"] = latest["conclusion"]
        info["failed_steps"] = _failed_steps(repo, latest["id"])
        out.append(Finding("github", "WorkflowFailed", "critical",
                           f"Latest deploy run #{latest['run_number']} {latest['conclusion']}", info))
    return out


def _failed_steps(repo, run_id):
    res = []
    r = requests.get(f"{API}/repos/{repo}/actions/runs/{run_id}/jobs", headers=_h(), timeout=20)
    if r.status_code != 200:
        return res
    for job in r.json().get("jobs", []):
        bad = [s["name"] for s in job.get("steps", []) if s.get("conclusion") == "failure"]
        if not bad:
            continue
        entry = {"job": job["name"], "steps": bad}
        lg = requests.get(f"{API}/repos/{repo}/actions/jobs/{job['id']}/logs",
                          headers=_h(), timeout=30)
        if lg.status_code == 200:
            entry["log_tail"] = "\n".join(lg.text.splitlines()[-25:])
        res.append(entry)
    return res
