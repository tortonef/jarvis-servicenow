# Jarvis: an AI assistant for the IT Service Desk on ServiceNow

Jarvis reacts to every new ServiceNow incident (or to the **Ask Jarvis** button on the form), searches the **Knowledge Base** and **previously resolved incidents**, posts a **resolution suggestion** for the agent as a work note, and **triages** the ticket: category and assignment group. When a ticket is resolved, it turns the fix into a **draft KB article**, so the knowledge base grows with every solved problem. For known fixes it can also **act**: it proposes a remediation (unlocking a locked-out account), an agent approves it with one click, and Jarvis carries it out. **P1 incidents** are also pushed to Slack with Jarvis's first diagnosis.

It runs on a **free** LLM (Groq, GPT-OSS 120B) and a free ServiceNow **Personal Developer Instance**. The knowledge base is **documentation as code**: Markdown in [`knowledge/`](knowledge/), reviewed by pull request, indexed in PostgreSQL + pgvector and published to the ServiceNow KB.

![Jarvis work note on a ServiceNow incident](docs/images/work-note-closeup.png)

*A real ticket on a ServiceNow PDI: Jarvis suggests the probable cause and the steps, citing the KB article and the resolved ticket it drew the answer from.*

## How it works

```mermaid
flowchart LR
    U([End user]) -->|opens ticket| INC[(ServiceNow<br/>Incident)]
    A([Service Desk agent]) -->|Ask Jarvis /<br/>approve unlock| BTN[UI Actions]
    INC -->|async Business Rules<br/>on create / on resolve| CL[Script Include<br/>JarvisClient]
    BTN --> CL
    CL -->|HTTPS POST /suggest, /kb-draft,<br/>/remediate: sys_id + token| S
    subgraph Jarvis [Jarvis - Python]
        S[HTTP server] --> R[Hybrid retrieval<br/>pgvector + full text]
        R --> L[LLM<br/>Groq / GPT-OSS 120B]
        PG[(PostgreSQL<br/>chunks + vectors)] --> R
    end
    GH[(knowledge/ on GitHub<br/>Markdown, reviewed by PR)] -->|poll, ingest| PG
    GH -->|publish via Jarvis KB API| KB[(ServiceNow KB<br/>Helios Group IT)]
    HIST[(Resolved<br/>incidents)] -->|Table API| R
    L -->|work note + category + group<br/>via Table API| INC
    L -->|draft article on resolve| KB
    L -->|P1 only| SL([Slack channel])
```

```mermaid
sequenceDiagram
    participant SN as ServiceNow
    participant J as Jarvis
    participant LLM as Groq (GPT-OSS 120B)
    SN->>J: POST /suggest {sys_id} (Business Rule or Ask Jarvis)
    J-->>SN: 202 Accepted
    J->>SN: GET incident by sys_id
    SN-->>J: INC0010019 "Teams: nobody can hear me in meetings"
    J->>J: hybrid search in PostgreSQL (docs) + similar resolved incidents
    SN-->>J: KB0010023 Teams audio/video, INC0010009...
    J->>LLM: ticket + articles + past resolutions
    LLM-->>J: probable cause, steps, sources, confidence
    J->>LLM: classify (JSON, allowed categories and groups)
    LLM-->>J: category + assignment group
    J->>SN: PATCH work_notes + empty category/group
    Note over SN: The agent sees the suggestion on the ticket
```

## Live on ServiceNow

A user opens the ticket *"Teams: nobody can hear me in meetings"*. The Business Rule calls Jarvis and about 6 seconds later the agent finds Jarvis's work note in the activity stream:

<p align="center"><img src="docs/images/incident-work-note.png" width="700" alt="ServiceNow incident with the Jarvis work note"></p>

The suggestion comes from article **KB0010023** in the demo knowledge base and from resolved ticket **INC0010009**:

<p align="center"><img src="docs/images/kb-article.png" width="700" alt="Article KB0010023 in ServiceNow"></p>

### Ask Jarvis button

Agents can also ask Jarvis on any existing ticket. Here it works on one of the PDI's own demo incidents: no article in the demo KB fits, so Jarvis builds on a similar past ticket and a stock KB article, and honestly reports *medium* confidence.

<p align="center"><img src="docs/images/ask-jarvis.png" width="700" alt="Ask Jarvis button, confirmation message and resulting work note"></p>

### Auto-triage

Jarvis also picks the category and the assignment group. It fills them **only if nobody has set them yet** (category still *Inquiry*, no group), and always writes its choice in the note. Allowed values come from ServiceNow itself: the incident categories and the groups that already handle incidents.

<p align="center"><img src="docs/images/triage.png" width="700" alt="Category and assignment group set by Jarvis, with the triage line in the work note"></p>

### Learning loop: KB drafts from resolved tickets

When an incident is resolved, Jarvis reads the agent's resolution notes and the closest articles. If the fix is already documented, it says so and creates nothing. Otherwise it writes a **draft** article, linked to the incident, for a human to review and publish. The next time the same problem comes in, Jarvis finds the answer:

<p align="center"><img src="docs/images/learning-loop.png" width="600" alt="Learning loop: low-confidence answer, agent fix, KB draft, high-confidence answer on the next ticket"></p>

The draft Jarvis wrote from the agent's notes, linked back to the source incident:

<p align="center"><img src="docs/images/kb-draft.png" width="700" alt="Draft KB article written by Jarvis"></p>

### Auto-remediation with approval

When a ticket is about a locked-out account, Jarvis does more than explain the fix. The model flags the intent, and Jarvis checks the data: is the caller really locked out in ServiceNow? Only then does it propose the action. An agent approves with the **Unlock account (Jarvis)** button, which is shown only while the caller is locked and records the approval as a work note in the agent's name. Jarvis re-checks the approval and the lockout, unlocks the account and resolves the ticket, which in turn triggers the KB check:

<p align="center"><img src="docs/images/remediation.png" width="760" alt="Jarvis proposes an unlock, the agent approves, Jarvis unlocks and resolves"></p>

> The PDI has no Active Directory, so the demo unlocks the ServiceNow user (`sys_user.locked_out`). In production the same step would call Active Directory or Entra ID.

### Knowledge base as code

The documentation of **Helios Group**, a fictional company with its own domain, servers and teams, lives in [`knowledge/`](knowledge/): about 30 documents, articles for users and the Service Desk and runbooks for the maintenance team, Markdown with validated front matter. Changing the knowledge base is a pull request:

```mermaid
flowchart LR
    PR[Pull request<br/>new or edited doc] --> CI{CI: front matter check<br/>+ retrieval quality gate}
    CI -->|review + merge| MAIN[main]
    MAIN -->|Jarvis polls GitHub| ING[Ingest changed docs:<br/>chunks + embeddings<br/>in PostgreSQL]
    ING --> PUB[Publish / update / retire<br/>in the ServiceNow KB]
    ING --> ANS[Jarvis cites it<br/>in the next answer]
```

- **Search** is hybrid: meaning (local embeddings, [fastembed](https://github.com/qdrant/fastembed) `BAAI/bge-small-en-v1.5`, no API key) plus a small full-text bonus for exact commands and codes, in one PostgreSQL query. Each document is split into a title + symptoms chunk and one chunk per section.
- **Publishing**: ServiceNow refuses to edit published articles through the Table API, so the installer adds a small Scripted REST API (*Jarvis KB*) that creates, updates and retires articles server side. Articles are matched on the document id, so editing a doc updates the same KB number.
- **Only changes move**: documents are skipped by content hash; a deleted doc retires its article. A malformed doc stops the sync and Jarvis keeps serving the last good knowledge base.

Retrieval quality on 40 tickets written the way users and engineers write them (`python -m tests.eval_search`):

| Search | Right document first |
|---|:---:|
| Keyword (ServiceNow-style `LIKE` + ranking) | 80% |
| Semantic, whole documents | 78% |
| **Hybrid, chunked (what Jarvis uses)** | **98%** |

Most of the gain comes from chunking: one vector per section keeps a long runbook from diluting its meaning. The full-text part adds the exact-command cases (*"repadmin shows errors"*). The cases were written together with the documents, so treat 98% as optimistic; CI fails any change that drops hybrid below 85%.

### On-prem lab and MID Server

Jarvis can check real systems on-prem without any inbound connection to them. The lab is a **Samba Active Directory** for `helios.local` (domain controller `dc01`, users in `OU=Staff`, lockout after 5 bad passwords), built from Debian's own packages. A **ServiceNow MID Server**, built from ServiceNow's official container recipe, is the only component that talks to it, and it only connects outbound to the PDI.

```mermaid
sequenceDiagram
    participant SN as ServiceNow PDI
    participant J as Jarvis
    participant MID as MID Server (helios-mid)
    participant DC as dc01 (Samba AD)
    Note over SN: agent clicks "Check AD account (Jarvis)"
    SN->>J: POST /diagnose {sys_id}
    J->>SN: ECC queue output: JavascriptProbe JarvisLdap.lockoutStatus(account)
    MID->>SN: poll ECC queue (outbound)
    MID->>DC: LDAPS search as svc_jarvis (read only)
    DC-->>MID: lockoutTime, badPwdCount, policy
    MID->>SN: ECC queue input: result
    J->>SN: read result, post work note
```

- **No paid plugins**: the IntegrationHub SSH and PowerShell steps are not active on a PDI, so Jarvis sends a *JavascriptProbe* that calls a fixed function in a MID Server Script Include (`JarvisLdap`). Only named calls exist (`jarvis/mid.py`), and the account name is validated on the MID before it reaches the LDAP filter.
- **Least privilege**: the MID signs in as `mid.helios` (role `mid_server`, web service access only); LDAP uses `svc_jarvis`, an ordinary account with no admin rights. Its password lives only in the MID container and never passes through ServiceNow.
- **Speed**: about 3 seconds per check once the MID is warm (the very first probe after start took about a minute while the MID synchronized).

```
Account alex.rivera: LOCKED OUT since 12:13 UTC after 5 bad passwords (threshold 5);
unlocks automatically at 12:43 UTC.
To unlock now follow RB-AD-001; if it locks again, find the source with RB-AD-002.
```

To run the lab: download ServiceNow's `mid-linux-container-recipe` for your instance version into `lab/mid/recipe/` (it is not redistributed here), then:

```bash
docker build -t mid:brazil-patch2 lab/mid/recipe
```

```bash
docker compose --profile lab up -d --build
```

Set `MID_USER`, `MID_PASSWORD` and the `LAB_*` passwords in `.env` first, and validate the MID Server once in ServiceNow (**MID Server > Servers > helios-mid > Validate**).

### P1 alerts on Slack

When the ticket is a P1 (impact and urgency high), Jarvis posts to a Slack channel as soon as its suggestion is ready: title linked to the incident, probable cause, confidence and KB sources, so the on-call team starts from a diagnosis instead of a bare alert. Set `NOTIFY_WEBHOOK_URL` to a Slack [Incoming Webhook](https://api.slack.com/messaging/webhooks); leave it empty to disable.

<p align="center"><img src="docs/images/slack-p1.png" width="560" alt="Slack alert for a P1 incident with Jarvis's diagnosis"></p>

## Design choices

| Choice | Why |
|---|---|
| **ServiceNow stays the record for tickets** | Incidents, approvals and history live in ServiceNow; PostgreSQL holds only Jarvis's own data: the knowledge index, vector cache and audit trail. |
| **Docs as code, one-way to ServiceNow** | Git gives versioning, review by pull request and a quality gate for free; the ServiceNow KB is a read-only mirror, so the two never drift. |
| **Local embeddings** | Free and private: ticket text never leaves the machine for search. |
| **Push, with polling as fallback** | An async Business Rule and the *Ask Jarvis* button call Jarvis right away. Where ServiceNow cannot reach Jarvis, `jarvis.main` polls instead (no tunnel, nothing installed in ServiceNow). |
| **Untrusted caller** | The Jarvis endpoint requires a shared token, accepts only a 32-hex `sys_id` and re-reads the incident from ServiceNow; it never trusts ticket text sent in the request. |
| **A single LLM call (RAG)** | More predictable and faster than a tool-calling agent, and fits the free-tier limits. |
| **Dedicated KB with Instant Publish** | The PDI's "IT" KB has an approval flow; in *Helios Group IT* the approval is the pull request, and the stock KBs stay untouched. |
| **OpenAI-compatible API** | Groq, local Ollama, Gemini, OpenAI or Claude: just change `.env`. |
| **Triage never overrides people** | LLM output is checked against ServiceNow's own categories and groups; invented values are dropped, fields an agent already set are left alone, and a triage failure never blocks the resolution note. |
| **KB drafts need a human** | Jarvis only creates drafts; publishing stays a human decision. Model output is HTML-escaped before it goes into the article, and a `covered_by` answer is trusted only if it names an article Jarvis actually showed the model. |
| **Actions need a recorded human approval** | The model can only flag an intent; the proposal requires the data to agree, and `/remediate` acts only if it finds the agent's approval note and the account is still locked. A call without approval is refused even with a valid token. |
| **Alerts can't be hijacked by ticket text** | Ticket text is escaped before it reaches Slack, so a title like `<!channel>` cannot ping the whole channel. A Slack outage is logged and never costs the work note. |
| **On-prem only through the MID Server** | ServiceNow's own outbound-only bridge: no firewall opening into the lab, ServiceNow keeps the ECC queue as an audit trail, and Jarvis can only call named MID functions. |
| **Work note, not a comment** | The suggestion is visible to agents only, never to the end user. |

## Quickstart

1. **ServiceNow**: create a free Personal Developer Instance at [developer.servicenow.com](https://developer.servicenow.com).
2. **LLM**: create a free API key at [console.groq.com](https://console.groq.com/keys).
3. Install and configure:

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Fill in `.env` with the instance URL, admin credentials, Groq key, a random `JARVIS_TOKEN` and `DOCS_REPO` (the GitHub repo holding `knowledge/`), then load the demo incidents and the lockout demo user:

```bash
python -m seed.seed
```

The KB articles are not seeded: Jarvis publishes `knowledge/` to the ServiceNow KB *Helios Group IT* when it starts.

### Run with Docker (recommended)

Requires Docker. Set `POSTGRES_PASSWORD` in `.env`, then:

```bash
docker compose up -d --build
```

This starts three containers: **PostgreSQL + pgvector** (embedding cache and an audit trail of every suggestion), the **Jarvis server**, and a free [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/) (no account needed). At startup Jarvis reads the tunnel's public URL and installs the ServiceNow side with it: system properties, `JarvisClient` Script Include, *Ask Jarvis* and *Unlock account (Jarvis)* buttons, async Business Rules on create and on resolve, the *Helios Group IT* knowledge base and the *Jarvis KB* API. Then it syncs `knowledge/` from GitHub and checks for new commits every `DOCS_POLL_SECONDS`. Quick-tunnel URLs change on every restart; Jarvis re-registers each time, so there is nothing to do by hand.

The first start embeds the KB and the ticket history (about 30 seconds on the PDI); later starts load the vectors from PostgreSQL (about 3 seconds).

Create an incident or click **Ask Jarvis** on an existing one: the work note appears in a few seconds. Resolve an incident with resolution notes to get a KB draft. For auto-remediation, `seed` creates the demo user **Alex Rivera** in locked-out state (re-run it to lock him again): open an incident with Alex as caller saying the account is locked.

### Push mode without Docker

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

### Polling mode (no tunnel)

```bash
python -m jarvis.main
```

Jarvis checks for new incidents every 30 seconds. Use one mode at a time, or new tickets get two notes.

## Tests

```bash
python -m unittest -v
```

The database tests and the retrieval eval run against a real PostgreSQL when `TEST_DATABASE_URL` is set (with Docker, a separate database: `postgresql://jarvis:<POSTGRES_PASSWORD>@127.0.0.1:55432/jarvis_test`). CI runs on every push and pull request: front matter check, all tests on a pgvector service, the retrieval quality gate with the real model, and the Docker build.

Tests run offline (ServiceNow, the LLM and the embedding model are faked). They check that every document in `knowledge/` is valid, that the docs loader reads only `knowledge/` files from the GitHub tarball and never writes them to disk, that Markdown becomes escaped KB HTML, that ingestion skips unchanged docs and retires deleted ones, that the HTTP endpoint rejects a wrong token, a malformed `sys_id` and invalid JSON, that triage fills only empty fields and drops invented or malformed LLM output, that KB drafts are escaped, linked to the incident and skipped when the fix is already documented, and that an unlock is proposed only when model and data agree and executed only after a recorded approval. Slack alerts are tested for P1-only sending, escaping and failure handling (no real HTTP calls). The semantic index is tested for ranking, the relevance threshold and embedding caching; `python -m tests.eval_search` measures retrieval quality with the real model.

## Layout

```
jarvis/snow.py     ServiceNow REST client + search and ranking
jarvis/agent.py    prompts and LLM calls
jarvis/semantic.py semantic ranking with cached local embeddings
jarvis/mid.py      named MID Server calls through the ECC queue
jarvis/knowledge.py docs as code: validate, ingest, hybrid search, publish to the KB
knowledge/         the Helios Group knowledge base (articles + runbooks)
jarvis/notify.py   Slack alert for P1 incidents
jarvis/db.py       PostgreSQL: migrations, vector cache, suggestion audit
db/migrations/     SQL migrations, applied at startup
jarvis/server.py   push mode: HTTP endpoint called by ServiceNow
jarvis/main.py     polling mode + shared handle() logic
jarvis/config.py   .env loading
seed/              demo incidents and user, install_snow.py and JarvisLdap.js (MID Script Include)
lab/               on-prem lab: dc01 (Samba AD) and the MID Server image
tests/             tests + eval_search.py (keyword vs semantic vs hybrid, the CI quality gate)
```

## Roadmap

- [x] **Step 1**: resolution suggestion from the KB and ticket history
- [x] **Step 2**: "Ask Jarvis" button on the form and push via async Business Rule
- [x] **Step 3**: auto-categorization and assignment group
- [x] **Step 4**: draft KB article from resolved incidents whose fix is not documented yet
- [x] **Step 5**: auto-remediation with agent approval (account unlock)
- [x] **Step 6**: semantic search with local embeddings
- [x] **Step 7**: Slack alert for P1 tickets

**Next:** [Jarvis 2.0 architecture and roadmap](docs/architecture-plan.md) (Phase 0 done: Docker, PostgreSQL + pgvector, CI. Phase 1 done: knowledge base as code. Phase 2 done: on-prem lab and MID Server). Next up: a procedure catalog with risk levels running on an on-prem lab through the MID Server, and the end-user and maintenance support processes.
