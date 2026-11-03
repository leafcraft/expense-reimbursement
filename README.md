# expense-reimbursement — Expense-Reimbursement Pod

Four digital employees + four human roles that run an employee travel-expense
claim end to end — **receipts → confidence-scored extraction → policy pre-check →
form → employee confirm → approval (Box e-sign) → finance → payout & live
status** — with a human on every gate and the systems (Outlook / Box / SAP) as
tools inside the agents, never members.

**Read `PRD.md`** for the full agent-by-agent spec. This is a **pod-standard
reference** (SDK 2.4.131): a team of self-reliant agents, not a pipeline.

## Why it works in an organization

Today every travel claim makes an employee collect the proofs, key the amounts,
fill the form, chase approvals, and follow up with Finance — 25–30 minutes of
manual work per claim, fragmented across an inbox, a folder, and a form. This pod
runs that chain end to end, working alongside the people who already own the
decisions. It wins "zero data-entry errors" the only honest way: **Odo never
guesses** — a field it cannot read with confidence becomes a question to the
employee, not a number in a form. **Fern cross-checks** before anyone sees the
form and returns to Odo on a mismatch (once — a second mismatch goes to the
Finance-Ops Lead) rather than balancing the books itself. **Odo's floor
re-checks the expense policy** — a hotel night over the cap or a receipt
already claimed on an earlier claim goes to the Finance-Ops Lead, whatever the
model said. **Sol re-checks that the approver actually approved** before it
issues anything, and **deletes a half-issued pack** if its floor trips.
**Silence never advances a claim** — if nobody answers within the reply window,
the Inbox card closes and the ticket records that no reply came; nothing is
approved or paid, and nobody is chased automatically. Every decision, send, and approval lands in
a hash-chained WORM ledger. ROI: ≥75% less employee time per claim, real
approval control, and a live "where is my claim?" answer.

## The team (9 members)

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `remi_coordinator_agent` | Claim Coordinator | Owns the case end to end; opens it, keeps live status, is the employee's one contact | LLM; orchestrates Odo→Fern→Sol; routes exceptions to the Finance-Ops Lead; **never reads a receipt or approves** |
| `odo_extraction_agent` | Proofs & Extraction Analyst | Collects every proof, reads each with a confidence score, classifies, runs the policy pre-check | LLM + **super_agent** (autonomous multi-proof) + **playbook** (extraction craft) + proof tools; `@chain` **confidence floor** (fail closed) |
| `fern_builder_agent` | Claim Builder | Fills the reimbursement form from Odo's verified data, cross-checks, gets the employee's one-look confirmation | LLM + **playbook**; `@chain` **cross-check floor**; renders the draft form to `./out` |
| `sol_finance_agent` | Approvals & Finance Liaison | Routes Box approval (e-sign), submits the approved pack to Finance, tracks payout, records the ledger | Programmatic **finisher**; approve-token re-check → invariants → render pack → **delete-on-block** → WORM ledger |
| `finance_ops_lead_human` | Accountable owner (Human) | Reviews exceptions, owns policy calls, decides every gate | Human gate — everything that leaves the pod |
| `employee_human` | Claimant (Human) | Submits receipts, answers Odo's questions, confirms the form | Human gate |
| `approver_human` | Manager (Human) | Approves or rejects in the Box workflow | Human gate |
| `finance_officer_human` | Finance (Human) | Processes the approved, ledgered pack to payment | Human gate |
| `expense_audit_logger_agent` | WORM audit | Hash-chains every decision, approval, send, and held gate | External (custom sink); terminus |

Reply windows (`human_timeout_seconds`): Claimant 2 days, Manager (approver)
2 days, Finance 5 days (the weekly payment run), Finance-Ops Lead 3 days.

The **LeafMesh Manager** supervises. It escalates to the Finance-Ops Lead when an
agent fails with an error a retry cannot fix (auth, bad request, credit, bad
config), when 5 different agents fail in one session, or when restarts run out.
A broken hand-off contract raises an alert only. Policy flags and a form that
still does not tie out reach the Lead on the agents' own wires.

### Expense policy (dev store: `agency/_shared/store.py` → `POLICY_CAPS`)

| Class | Lodging / night | Meals / day | Airfare / ticket | Ground transport / day |
|---|---|---|---|---|
| local | — | $40 | — | $60 |
| domestic | $250 | $75 | $750 | $120 |
| international | $325 | $100 | $2,500 | $150 |

Odo reads these with `read_expense_policy`; Odo's floor re-checks every USD line
(and every line where Odo filled `amount_usd`) and flags `over_cap` itself.
Foreign-currency lines without `amount_usd` rely on Odo's own conversion and
check. Replace the table with your own policy.

## Configuration — what to set, in three tiers

Everything is set in `.env` (`cp env .env`). The **whole LLM chain (extract →
build → approval routing) runs on Tier 1 alone** against the seed proof store
(`./data`); proof reads, Box approval, and Finance submission use dev stand-ins
that **announce themselves** until you wire Tiers 2–3.

### Tier 1 — required to boot (dev mode)
| Setting | For | Notes |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | LeafMesh runtime | **Required.** |
| `ANTHROPIC_API_KEY` | Odo + Fern (Claude) | **Required.** |
| `OPENAI_API_KEY` | Remi + Manager (`gpt-4o-mini`) | **Required** unless you change the models. |
| `REDIS_HOST` / `PORT` / `PASSWORD` | State store | Defaults to `localhost:6379`. `docker run -d -p 6379:6379 redis:7-alpine`. |
| *(no setting)* — human members | Human approvals | Answer in Studio's Inbox. To notify an external tool instead, create a vault connection (an "Add custom" record on the Infrastructure page, service type 'Outbound webhook') and set `webhook_config: {connection: <name>}` on the seat. |

### Tier 2 — real proof connectors (vault connection, then uncomment the `mcp` block)
| Vault connection | Enables |
|---|---|
| `outlook_mcp` — the Outlook MCP server's URL + token | Real receipt emails + calendar reads |
| `box_mcp` — the Box MCP server's URL + token | Real Box folder reads + approval workflow |

> Addresses and tokens live **only in the vault** (Infrastructure → Integrations
> → MCP, or an "Add custom" record with service type Tools) — a URL or token
> written in `configs/config.yaml` is refused at load. Create the connections
> **first**, then uncomment the `mcp` block — in `configs/config.yaml` before the
> first start, in Studio's YAML editor after it (applies live, no restart; see
> *Changing the configuration after the first start*). An agent whose named
> connection does not exist is switched off until it is created. Nothing goes in
> `.env`: `agency/tools.py` checks whether the vault record `outlook_mcp` or
> `box_mcp` exists, only to word an empty dev-store answer.

### Tier 3 — SAP direct posting replaces the Finance email (later).

## Run it

```bash
pip install -r requirements.txt          # core LeafMesh runs the pod day-0
docker run -d -p 6379:6379 redis:7-alpine
cp env .env                              # fill at least Tier 1
python validate_config.py                # pre-flight: wiring, yields, dead-code
python main.py                           # API at http://127.0.0.1:18820/docs
```

Submit a claim (day-0, against the seed store — no connector needed):

```bash
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"submit_receipts",
       "data":{"claim_id":"CLM-DEMO-001","message":"expenses for my Chicago client visit"}}'
```

`CLM-DEMO-001` includes an illegible receipt on purpose — watch Odo ask the
employee rather than guess. The other seed claims, one per route:

| `claim_id` | What happens |
|---|---|
| `CLM-DEMO-002` | International (EUR); Odo converts, caps checked → form → approver |
| `CLM-DEMO-003` | Clean domestic trip, $682.80, inside every cap → form → approver → Finance |
| `CLM-DEMO-004` | Hotel at $412 a night vs the $250 cap → `over_cap` → Finance-Ops Lead |
| `CLM-DEMO-005` | Re-claims the airfare from `CLM-DEMO-001` → `duplicate_receipt` → Finance-Ops Lead |
 On approval, Sol renders the approved pack to `./out/`
and appends `./data/expense_ledger.json`.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real Outlook/Box connectors add `leafmesh[mcp]`. Avoid
> `leafmesh[all]` on Python 3.12+ (it pulls `cchardet`, which has no wheel) — add
> only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*

## Changing the configuration after the first start

`configs/config.yaml` is only the first-start seed. On the first start (an empty store) the agency imports it as version 1 and from then on keeps its configuration in the store. After that the file is not read again: an edit to it is **not** applied, even after a restart (the boot log says "that edit was NOT applied").

To change a running agency:

- **Studio** — its settings pages, or the raw YAML editor.
- **API** — `PUT /api/yaml/raw` with an `X-API-Key` header and the body `{"yaml_content": "<the whole YAML>", "save_to_disk": true}`, or `PATCH /api/yaml/config` with `{"updates": {...}, "save_to_disk": true}`.

Each save is a new version and applies live on every pod — no restart. (A few settings, such as brokers, make the agency reload itself in place within seconds.) So wherever this README or a comment says "uncomment X in `configs/config.yaml`", do it in the file before the first start, or in Studio's YAML editor after it.

## Where the data store is set

From leafmesh 2.4.482 the store (Redis or Postgres) is set **only in `.env`** — never in `configs/config.yaml`. A `persistence:` block in the YAML is ignored with a warning on leafmesh 2.4.482–2.4.485; from 2.4.486 the agency refuses to start if that block differs from `.env`, and names each `.env` line to add. The project's `.env` sets the store explicitly (`LEAFMESH_STORE`, `LEAFMESH_AGENCY_NAME`, `REDIS_*`).

- Redis (default): `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`; optional `REDIS_DEFAULT_TTL`, `REDIS_SESSION_TTL`, `REDIS_SSL*`, `REDIS_CLUSTER_NODES`.
- Postgres instead: `LEAFMESH_STORE=postgres` plus `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional `POSTGRES_SSLMODE`).
- Or the whole server in one value: `REDIS_URL=redis://user:pw@host:6379/0` (`rediss://` turns TLS on) or `DATABASE_URL=postgresql://user:pw@host:5432/db`. The single names fill in what the URL leaves out.
- With Docker Compose the app reaches Redis as `redis` (the service name); compose sets that for you.
- Check it in Studio → **Infrastructure → Datastores**: it shows whether the store is reachable (never the address or password).

## Your vault key — back it up

`create-leafmesh` put a `LEAFMESH_VAULT_KEY` in your `.env` when it made this project. It is the master key that encrypts every connection and credential you store in the vault (in Redis / Postgres).

- **Back it up like a master password.** Lose it and every stored connection has to be entered again.
- **Never change or regenerate it** for an existing project — a new key locks the existing vault. To change it, use `leafmesh vault rotate-key`.
- Every copy of the app (every replica) must get the **same** value. Docker Compose passes it in from `.env` as an environment variable.
- Never commit `.env` (it is already in `.gitignore`).
