# AI SRE Agent: GKE + GitHub Actions + Grafana

An agent that **observes** three systems, **correlates** the evidence with Gemini (rule-based fallback),
and **remediates** safely.

```
 GKE (pods, events, logs) ─┐
 GitHub Actions (runs)  ───┼─► Gemini / rules ─► allow-listed action ─► kubectl rollout undo|restart
 Grafana (alerts, PromQL) ─┘        (JSON)         (dry-run by default)
```

## Setup (Cloud Shell)
```bash
cd ~/gcpkubernetes/ai-sre-agent            # drop this folder into your repo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env && set -a && source .env && set +a
gcloud container clusters get-credentials ai-k8s-cluster --region asia-south1
```
Tokens needed:
- **GEMINI_API_KEY**: optional; without it the agent uses the rule engine.
- **GITHUB_TOKEN**: fine-grained PAT, repo `techabdulrahman/gcpkubernetes`, permission *Actions: Read*.
- **GRAFANA_TOKEN**: Grafana → Administration → Service accounts → Viewer role → add token.
  Optional `GRAFANA_PROM_UID` enables the PromQL checks (restarts, pods not ready; needs kube-state-metrics).

## Run
```bash
python -m agent.main                 # dry-run, prints what it would do
python -m agent.main --apply         # execute remediation
python -m agent.main --no-llm        # rules only
python -m agent.main --watch 60      # continuous loop
```
Each run writes `report.json`.

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
