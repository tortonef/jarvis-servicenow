# Jarvis 2.0: target architecture and roadmap

The demo in this repo proves the ideas on a ServiceNow PDI with seeded data. This document plans the next stage: a realistic setup for a fictional company, **Helios Group**, with a real knowledge base, a database, procedures that run on on-prem systems, and two orchestrated support processes. It stays free to run: ServiceNow PDI, Groq free tier, open-source components, a home lab in Docker.

## 1. Goals

1. **Knowledge first.** Every answer and every action comes from versioned, reviewed documentation, not from the model's memory.
2. **Two processes, one brain.** End-user support (Service Desk, L1) and maintenance support (operations team, L2) share the same knowledge and procedure catalog.
3. **Run procedures from ServiceNow.** Simple, well-defined procedures (unlock an account, check a disk, restart a service) run from the ticket, with approval levels and a full audit trail.
4. **Measurable.** Retrieval quality, suggestion usefulness and time saved are measured, not claimed.

Non-goals: replacing ServiceNow workflows, free-form AI actions (the model never writes or runs scripts), production SLAs.

## 2. Key decisions

| Decision | Choice | Why |
|---|---|---|
| System of record for tickets, approvals, SLAs | **ServiceNow** | Process state, approvals and audit belong where agents work. Jarvis never keeps its own ticket state. |
| Source of truth for documentation | **Docs as code: Markdown in a Git repo** (GitHub) | Free, versioned, reviewed by pull request (the review *is* the KB approval flow), renders on GitHub, and each runbook can declare its executable procedure. |
| Where agents and users read the docs | **ServiceNow KB**, synced one-way from Git | Agents and the portal see articles natively; nobody edits them in ServiceNow, so no drift. |
| Jarvis database | **PostgreSQL + pgvector** | One free database for document chunks and embeddings, the procedure catalog, executions audit, feedback and evaluation runs. Hybrid search (full text + vectors) in SQL. |
| LLM | **Groq** (`openai/gpt-oss-120b`), behind the OpenAI-compatible client | Free tier; provider can still be swapped via `.env`. |
| Embeddings | **Local** (fastembed, `bge-small-en-v1.5`) | Groq has no embedding API; local is free and keeps text private. |
| Running procedures on-prem | **ServiceNow MID Server** first, **Jarvis Runner** as fallback | MID is the ServiceNow-native, outbound-only bridge to on-prem. Its PowerShell/SSH capabilities depend on plugins available on the PDI, so Phase 2 starts with a spike; if blocked, a small outbound-only Jarvis Runner agent does the same job. |
| What the model may decide | **Pick a procedure ID and fill parameters** | Parameters are validated against a schema; the script itself is fixed and reviewed in Git. |
| On-prem lab | **Samba AD DC + Linux and Windows-like targets in Docker** | Realistic AD and server operations at zero cost. |
| Hosting Jarvis | **docker compose** on one machine + **Cloudflare named tunnel** | Free, stable public hostname (quick tunnels change URL on every restart). |

## 3. Architecture

```mermaid
flowchart TB
    subgraph Users
        EU([End user])
        AG([Service Desk agent])
        OPS([Maintenance engineer])
    end

    subgraph SN [ServiceNow PDI]
        PORTAL[Service Portal +<br/>Virtual Agent]
        INC[(Incidents / Problems /<br/>Changes / Requests)]
        FLOW[Flow Designer:<br/>approvals, SLAs, states]
        KBV[(Knowledge Base<br/>read-only mirror)]
        MID[MID Server]
    end

    subgraph GIT [GitHub]
        DOCS[docs repo:<br/>articles + runbooks<br/>+ procedure scripts]
        CI[CI: lint, test,<br/>ingest, sync]
    end

    subgraph JV [Jarvis - docker compose]
        API[Jarvis API<br/>FastAPI]
        RET[Hybrid retrieval]
        POL[Policy engine:<br/>risk levels, params]
        WRK[Worker: ingestion,<br/>KB gap detection]
        PG[(PostgreSQL<br/>+ pgvector)]
    end

    LLM[Groq LLM]

    subgraph LAB [On-prem lab - Docker]
        AD[Samba AD DC]
        SRV[Linux / app servers]
    end

    EU --> PORTAL --> INC
    AG --> INC
    OPS --> INC
    INC -- business rules / flows --> API
    API --> RET --> PG
    API --> POL --> PG
    API <--> LLM
    API -- notes, fields, tasks --> INC
    FLOW -- approved procedure --> MID
    MID -- PowerShell / SSH --> AD
    MID -- SSH --> SRV
    DOCS --> CI
    CI -- chunks + embeddings --> PG
    CI -- publish --> KBV
    WRK -- KB gap: pull request --> DOCS
```

**Responsibilities in one line each**
- **ServiceNow**: tickets, people, approvals, SLAs, audit, and the UI everyone uses.
- **Git docs repo**: what we know (articles) and what we can do (runbooks with procedures).
- **Jarvis API**: understands tickets, retrieves knowledge, proposes answers and procedures, writes back to ServiceNow.
- **PostgreSQL**: Jarvis's memory: chunks and vectors, procedure catalog, executions, feedback, evaluations.
- **MID Server / Runner**: the only component that touches on-prem systems, outbound connections only.

## 4. Documentation model

One repository, three kinds of documents, all Markdown with YAML front matter:

```
docs-repo/
  articles/            how-to and troubleshooting for end users and agents
  runbooks/            operational procedures for the maintenance team
  procedures/          the executable part: scripts + parameter schemas
```

Example runbook front matter:

```yaml
id: RB-AD-001
title: Unlock a locked-out Active Directory account
audience: [service-desk]
systems: [active-directory]
symptoms: ["account locked", "too many sign-in attempts", "can't log in after password change"]
procedure: unlock_ad_account        # links to procedures/unlock_ad_account/
risk: L1                            # see section 6
owner: identity-team
review_by: 2027-06-01
```

- **Pull request = review.** Merging to `main` publishes: CI lints the front matter, runs the procedure tests, chunks and embeds the text into PostgreSQL and updates the mirrored ServiceNow KB article.
- **Learning loop moves to Git.** When Jarvis finds a resolved ticket that no document covers, it opens a pull request with a draft article instead of a ServiceNow draft. The team reviews it like code.
- **Freshness.** `review_by` dates feed a weekly report of stale documents.
- **Initial content.** About 30 documents for Helios Group: 15 user articles (VPN, MFA, Outlook, printers…), 10 runbooks (AD, disk space, services, certificates, backups), 5 to 8 executable procedures.

## 5. Database schema (PostgreSQL + pgvector)

```mermaid
erDiagram
    document ||--o{ chunk : "split into"
    document ||--o| procedure : "may declare"
    procedure ||--o{ execution : "runs as"
    suggestion ||--o{ feedback : "rated by"
    eval_run ||--o{ eval_result : contains

    document {
        text id PK "RB-AD-001"
        text kind "article | runbook"
        text title
        text audience
        text commit_sha
        date review_by
    }
    chunk {
        bigint id PK
        text document_id FK
        text content
        tsvector fts
        vector embedding
    }
    procedure {
        text id PK "unlock_ad_account"
        text target "mid:powershell | mid:ssh"
        jsonb param_schema
        text risk "L0 | L1 | L2"
        bool enabled
    }
    execution {
        bigint id PK
        text procedure_id FK
        text ticket
        jsonb params
        text approved_by
        text status
        text output
        timestamptz started_at
    }
    suggestion {
        bigint id PK
        text ticket
        text kind "answer | triage | procedure"
        text model
        jsonb sources
    }
    feedback {
        bigint id PK
        bigint suggestion_id FK
        text agent
        int score
        text comment
    }
    eval_run {
        bigint id PK
        text git_sha
        timestamptz at
    }
    eval_result {
        bigint id PK
        bigint eval_run_id FK
        text case_id
        bool hit
        float score
    }
```

- **Hybrid retrieval**: full-text rank (`tsvector`) and vector similarity (`pgvector`) combined in one query, so exact error codes (`809`, `0x80070005`) and paraphrases both match.
- ServiceNow stays the record for tickets: Jarvis stores only ticket numbers, never copies of ticket data beyond what an audit row needs.

## 6. Procedures and risk levels

The model never writes code. It may only propose a **procedure ID with parameters**; Jarvis validates them against the JSON schema and the policy, and ServiceNow handles approval.

| Level | Meaning | Examples | Who approves |
|---|---|---|---|
| **L0** | Read-only diagnostics | Account lockout status, disk usage, service status, certificate expiry | Nobody: runs automatically and feeds the result to the suggestion ("diagnose, then suggest") |
| **L1** | Safe, reversible change to one user or one service | Unlock account, reset password with a temporary one, clear temp files, restart a non-critical service | The agent on the ticket, one click |
| **L2** | Change with impact on others | Restart a production service, extend a volume, renew a certificate | A Change request with approval in ServiceNow (Flow Designer) |

Guardrails: per-procedure allowlist of targets (for example only the `OU=Staff` organizational unit, only listed servers), least-privilege service accounts in the lab AD, dry-run mode, a timeout and output size limit, and every run written to `execution` and as a ServiceNow work note.

```mermaid
sequenceDiagram
    participant SN as ServiceNow
    participant J as Jarvis
    participant DB as PostgreSQL
    participant MID as MID Server
    participant AD as Lab AD
    SN->>J: new incident "can't log in"
    J->>DB: hybrid search → RB-AD-001 (procedure unlock_ad_account, L1)
    J->>MID: L0 diagnostic: get_lockout_status(user)
    MID->>AD: Get-ADUser -Properties LockedOut
    AD-->>MID: LockedOut = True, source DC01
    MID-->>J: result
    J->>SN: work note: diagnosis + proposed L1 procedure
    Note over SN: agent clicks Approve
    SN->>MID: Flow Designer runs unlock_ad_account (approved)
    MID->>AD: Unlock-ADAccount
    MID-->>SN: output → work note, resolve
    SN->>J: resolved → audit row, KB gap check
```

## 7. The two support processes

### End-user support (Service Desk, L1)

1. The user asks on the **Service Portal / Virtual Agent**. Jarvis answers from user-facing articles first; if the user confirms it helped, no ticket is created (deflection is measured).
2. Otherwise an incident is created; Jarvis triages it (category, group, priority hints), runs L0 diagnostics, and posts the suggestion with sources.
3. If a procedure fits, the agent approves it (L1) from the ticket; Jarvis runs it and resolves the ticket.
4. On resolve, Jarvis checks for documentation gaps and opens a pull request when one exists.
5. P1 incidents go to Slack with the diagnosis.

### Maintenance support (operations team, L2)

1. **Problems**: when several incidents look alike (vector clustering), Jarvis proposes a Problem record with the linked incidents and the likely cause.
2. **Requests to run a runbook**: a catalog item "Run maintenance procedure" lists the enabled procedures; L2 ones create a Change and wait for approval.
3. **Assisted changes**: on a Change, Jarvis attaches the relevant runbook steps, pre-checks (L0) and the rollback section from the docs.
4. **Health reports**: a weekly report of stale documents, procedures that failed, and the top ticket topics with no document.

## 8. Quality, observability, security

- **Evaluation set**: about 60 "golden" tickets with the expected document and procedure, run in CI on every docs or code change (extends today's `tests/eval_search.py`). A pull request that drops retrieval quality fails.
- **Feedback**: each Jarvis work note ends with *Helpful / Not helpful* (two UI actions that write to `feedback`).
- **Dashboards**: Grafana (free) on PostgreSQL: suggestion usefulness, deflection rate, procedure success rate, time to resolve with and without Jarvis.
- **Security**: tokens in `.env` and ServiceNow credential records (never plain properties), a PII redaction step before text goes to Groq (emails, phone numbers, IDs), least-privilege accounts per procedure, the `execution` audit table plus ServiceNow history.
- **Groq free tier**: rate limits are the main constraint; Jarvis queues LLM calls and caches answers per ticket so retries don't spend quota.

## 9. Roadmap

| Phase | Scope | Demo moment | Effort |
|---|---|---|---|
| **0. Foundations** ✅ | docker compose, PostgreSQL + pgvector, SQL migrations, persistent embedding cache, suggestion audit, CI with database tests, quick tunnel that registers itself in ServiceNow | `docker compose up` and the demo works; restart in 3 s instead of 30 s | done |
| **1. Knowledge platform** ✅ | `knowledge/` with about 30 Helios Group documents and validated front matter, GitHub polling, ingestion + hybrid search in pgvector, one-way publish to the ServiceNow KB through a Scripted REST API, retrieval quality gate in CI | Merge a pull request → the article appears in ServiceNow and Jarvis cites it | done |
| **2. On-prem lab + bridge** ✅ | Samba AD DC (`dc01`, `helios.local`) in Docker, MID Server from ServiceNow's official container recipe, ECC queue JavascriptProbe to a MID Script Include, read-only AD lockout check | A button in ServiceNow reads a real AD account's lockout status | done |
| **3. Procedure catalog** ✅ | `procedures/catalog.yaml` with 5 procedures (3 L0, 2 L1), rules for proposing and verifying, L0 auto-diagnostics in every suggestion, generic L1 approval button, `execution` audit table, lab servers app01/app02 with an SSH forced command, AD delegation | "Can't log in" → diagnosis from AD → one-click unlock in the real lab AD | done |
| **4. Processes** | Portal / Virtual Agent deflection, "Run maintenance procedure" catalog item, L2 via Change, Problem proposals | Full L1 and L2 journeys end to end | ~2-3 weeks |
| **5. Quality loop** | Feedback buttons, Grafana dashboards, KB-gap pull requests, stale-doc report | Dashboard showing what Jarvis saved this week | ~1 week |

### Phase 0 notes

- **No FastAPI yet.** The standard-library server already validates and routes the three endpoints; FastAPI comes in when the procedure catalog needs a real API.
- **Quick tunnel instead of a named tunnel.** A named Cloudflare tunnel needs a domain on Cloudflare. Instead the `tunnel` container runs a quick tunnel and Jarvis reads its URL from cloudflared's metrics endpoint at startup and re-registers in ServiceNow. Same result for a demo, no account. Switch to a named tunnel (or ngrok's free static domain) when a stable public URL matters.
- **Port 55432.** PostgreSQL is published on `127.0.0.1:55432` because 5432 is often taken by a local Postgres.

### Phase 1 notes

- **Docs live in this repository** (`knowledge/`), not a separate one: same pull request flow, one CI. Split it out when another team owns the docs.
- **Jarvis polls GitHub** instead of CI pushing to the database: GitHub Actions cannot reach a database on a laptop. Public repo, unauthenticated API, one call per poll.
- **Publishing needs a Scripted REST API** (*Jarvis KB*): the Table API answers 403 when editing a published article, and new articles are forced to draft on insert, so the script publishes with a separate write.
- **KB drafts from resolved tickets still go to ServiceNow** (step 4 of the demo). Moving them to pull requests is part of Phase 5.

### Phase 2 notes

- **The MID Server path works on a PDI without IntegrationHub.** The SSH and PowerShell action steps are not active, but a *JavascriptProbe* sent through the ECC queue runs a MID Server Script Include, which can start a local process (`ldapsearch`) on the MID host. No Jarvis Runner needed.
- **Validation through the API**: setting `validated=true` on the `ecc_agent` record was enough on this PDI.
- **Linux targets moved to Phase 3**, where the procedures that use them (disk cleanup, service restart) are built.
- **Lab shortcuts**, marked in the code: the DC's self-signed certificate is not verified, and `ldapsearch -w` puts the bind password in the MID container's process list.

### Phase 3 notes

- **The catalog is code, not docs.** It lives in `procedures/` and ships with Jarvis; runbooks are linked to it through `docs`, not the other way round, so publishing a document can never enable an action.
- **Rules decide, not the model.** The earlier demo let the model flag "unlock" and checked the data; now proposals and verifications are `propose_if` / `verify` rules on L0 results, and the model only writes the explanation.
- **Approval state lives in two places on purpose**: the pending proposal in PostgreSQL (what to run, with which parameters) and the approval note in ServiceNow (who approved, by ServiceNow's clock). Both must agree.
- **L2 (Change-approved) procedures move to Phase 4**, with the Change process.

## 10. Open questions

1. ~~MID Server capabilities on the PDI~~: answered in Phase 2, JavascriptProbe + MID Script Include.
2. **Virtual Agent on the PDI**: available and scriptable enough for the deflection flow, or use a simple portal widget instead.
3. **Lab host**: Docker Desktop on this PC (simplest) or an always-on small VM (needed if the demo must run while this PC is off).
4. **Fictional company scope**: how many users, departments and servers Helios Group needs to make the demo credible without becoming busywork.
