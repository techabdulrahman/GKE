# AI SRE Agent: GKE + GitHub Actions + Grafana

An agent that **observes** three systems, **correlates** the evidence with Gemini (rule-based fallback),
and **remediates** safely.

```
 GKE (pods, events, logs) ─┐
 GitHub Actions (runs)  ───┼─► Gemini / rules ─► allow-listed action ─► kubectl rollout undo|restart
 Grafana (alerts, PromQL) ─┘        (JSON)         (dry-run by default)
```

## Run locally
```bash
cd ai-sre-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env && set -a && source .env && set +a
gcloud container clusters get-credentials ai-k8s-cluster --region asia-south1 --project abdulproject-510307
```
Tokens needed:
- **GEMINI_API_KEY**: optional; without it the agent uses the rule engine.
- **GITHUB_TOKEN**: fine-grained PAT, repo `techabdulrahman/GKE`, permission *Actions: Read*.
- **GRAFANA_TOKEN**: Grafana → Administration → Service accounts → Viewer role → add token.
  Optional `GRAFANA_PROM_UID` enables the PromQL checks (restarts, pods not ready; needs kube-state-metrics).

## Run
```bash
python -m agent.main                 # dry-run, prints what it would do.
python -m agent.main --apply         # execute remediation
python -m agent.main --no-llm        # rules only
python -m agent.main --watch 60      # continuous loop
```
Each run writes `report.json`.

## Deploy to GKE with GitHub Actions

The workflow in `.github/workflows/google.yml` builds and pushes an image tagged with the commit SHA,
then applies the agent's CronJob, RBAC, ConfigMap, and ServiceAccount manifests. It does not modify
the demo Deployment or Service. The CronJob runs every five minutes with remediation in dry-run mode;
incident reports are also emitted as JSON to stdout for collection by GKE Cloud Logging.

Configure GitHub Actions repository variables:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`: full Workload Identity Provider resource name.
- `GCP_SERVICE_ACCOUNT`: email of the dedicated deploy service account.

Configure Workload Identity Federation for this repository and grant the deploy identity only the
permissions required to push to the Artifact Registry repository and deploy to the existing GKE
cluster. The cluster's node identity must be able to pull from that repository. The agent's
namespace-scoped Kubernetes Role only covers evidence collection and the `ai-k8s-demo` Deployment.

Before enabling the workflow, ensure the GKE cluster has the `ai-troubleshooter` namespace and
`ai-k8s-demo` Deployment. Optional runtime credentials belong in a Kubernetes Secret named
`ai-sre-agent-secrets` in that namespace; create only the keys you use (`GITHUB_TOKEN`,
`GEMINI_API_KEY`, `GRAFANA_URL`, `GRAFANA_TOKEN`, `GRAFANA_PROM_UID`). Do not commit secret values.
Without Gemini credentials the agent uses rules; without Grafana configuration it skips Grafana.

## 2-minute demo
```bash
python -m agent.main                 # 1. healthy: "all clear"
./scripts/break_it.sh                # 2. bad release -> ImagePullBackOff
python -m agent.main                 # 3. observe + diagnose + dry-run rollback
python -m agent.main --apply         # 4. agent rolls back, pods Ready again
```
Screen-record steps 3 and 4 next to the Grafana dashboard for the LinkedIn post.

## Guardrails (worth mentioning in the post)
- Dry-run by default; `--apply` is explicit.
- LLM can only choose from `rollout_undo | rollout_restart | none`; anything else is dropped.
- Only the configured deployment in the configured namespace can be touched.
- OOMKilled / config problems are advice-only (fix goes through a PR).
- A failing collector never stops the run.

## Where next
Runbook RAG (`search_runbooks` tool + pgvector), wrap collectors as an MCP server, run as a Kubernetes CronJob,
open a GitHub issue with the diagnosis instead of only printing it.
