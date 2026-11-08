[← Back to the README](../README.md)

# Development

## What docker compose starts

`docker compose up` starts four containers: **PostgreSQL + pgvector** (knowledge index, embedding cache and audit trail), the **Jarvis server**, **Grafana** and a free [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) (no account needed). At startup Jarvis reads the tunnel's public URL and installs the ServiceNow side with it: system properties, `JarvisClient` Script Include, *Ask Jarvis*, *Check AD account (Jarvis)* and *Approve Jarvis procedure* buttons, async Business Rules on incidents and Changes, the *Helios Group IT* knowledge base, the *Jarvis KB* API and the self-service portal page. Then it syncs `knowledge/` from GitHub and checks for new commits every `DOCS_POLL_SECONDS`. Quick-tunnel URLs change when cloudflared restarts; Jarvis checks on every loop and re-registers. A quick tunnel can also expire (cloudflared logs *Tunnel not found*): run `docker compose restart tunnel` and Jarvis follows within one loop. For a stable URL, use a named Cloudflare tunnel on your own domain.

The first start embeds the KB and the ticket history (about 30 seconds on the PDI); later starts load the vectors from PostgreSQL (about 3 seconds).

Create an incident or click **Ask Jarvis** on an existing one: the work note appears in a few seconds. Resolve an incident with resolution notes to get a KB pull request (or a ServiceNow draft without `GITHUB_TOKEN`). For the procedures, lock the demo user **Alex Rivera** in the lab AD (`sh lab/lock-user.sh alex.rivera`) and open an incident with Alex as caller, or stop the portal on a server (`sh lab/break-portal.sh app01`) and open an incident about it.

## Push mode without Docker

```bash
python -m jarvis.server
```

```bash
cloudflared tunnel --url http://127.0.0.1:8787
```

```bash
python -m seed.install_snow https://<your-tunnel>.trycloudflare.com
```

Without `DATABASE_URL` Jarvis keeps vectors in memory, skips the audit trail and answers from whatever is already in the ServiceNow KB (no docs sync). `python -m jarvis.knowledge sync` publishes `knowledge/` once.

## Polling mode (no tunnel)

```bash
python -m jarvis.main
```

Jarvis checks for new incidents every 30 seconds. Use one mode at a time, or new tickets get two notes.

## Tests

```bash
python -m unittest -v
```

The database tests and the retrieval eval run against a real PostgreSQL when `TEST_DATABASE_URL` is set (with Docker, a separate database: `postgresql://jarvis:<POSTGRES_PASSWORD>@127.0.0.1:55432/jarvis_test`). CI runs on every push and pull request: front matter check, all tests on a pgvector service, the retrieval quality gate with the real model, and the Docker build.

Tests run offline (ServiceNow, the LLM and the embedding model are faked). They check that every document in `knowledge/` is valid, that the docs loader reads only `knowledge/` files from the GitHub tarball and never writes them to disk, that Markdown becomes escaped KB HTML, that ingestion skips unchanged docs and retires deleted ones, that the HTTP endpoint rejects a wrong token, a malformed `sys_id` and invalid JSON, that triage fills only empty fields and drops invented or malformed LLM output, that KB drafts are escaped, linked to the incident and skipped when the fix is already documented, that the procedure catalog is valid, that parameters never come from free text, that L1 procedures are proposed only when their rule holds, and that approval without a proposal, a tampered parameter, a no-longer-needed action or a failed verification never resolves a ticket. Slack alerts are tested for P1-only sending, escaping and failure handling (no real HTTP calls). The semantic index is tested for ranking, the relevance threshold and embedding caching; `python -m tests.eval_search` measures retrieval quality with the real model.

## Layout

```
jarvis/snow.py     ServiceNow REST client + search and ranking
jarvis/agent.py    prompts and LLM calls
jarvis/semantic.py semantic ranking with cached local embeddings
jarvis/mid.py      named MID Server calls through the ECC queue
jarvis/procedures.py procedure catalog: validation, parameters, proposal and verification rules
jarvis/selfservice.py portal answers from end-user articles, deflection tracking
jarvis/problems.py Problem proposals from clusters of similar incidents
jarvis/report.py   weekly health report
jarvis/docs_pr.py  knowledge gaps as pull requests on the docs repo
procedures/        catalog.yaml: what Jarvis may run, at which risk level
jarvis/knowledge.py docs as code: validate, ingest, hybrid search, publish to the KB
knowledge/         the Helios Group knowledge base (articles + runbooks)
jarvis/notify.py   Slack alert for P1 incidents
jarvis/db.py       PostgreSQL: migrations, vector cache, suggestion audit
db/migrations/     SQL migrations, applied at startup
jarvis/server.py   push mode: HTTP endpoint called by ServiceNow
jarvis/main.py     polling mode + shared handle() logic
jarvis/config.py   .env loading
seed/              demo incidents and user, install_snow.py, mid/ (MID Script Includes), portal/ (Ask Jarvis widget)
grafana/           provisioned datasource (read-only role) and quality dashboard
lab/               on-prem lab: dc01 (Samba AD), app01/app02, the MID Server image, lock-user.sh
tests/             tests + eval_search.py (keyword vs semantic vs hybrid, the CI quality gate)
```
