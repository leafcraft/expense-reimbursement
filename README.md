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
form and returns to Odo on a mismatch rather than balancing the books itself.
**Sol re-checks that a human actually approved** before it issues anything, and
**deletes a half-issued pack** if its floor trips. **Silence never advances a
claim** — every gate default-denies. Every decision, send, and approval lands in
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

The **LeafMesh Manager** supervises — it reads every hand-off and escalates
stalls / policy calls / approval timeouts to the Finance-Ops Lead automatically.

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
| `HITL_OUTBOUND_URL` | Where human members are notified | Defaults to a local stub. |

### Tier 2 — real proof connectors (set the URL, uncomment the `mcp` block)
| Setting | Enables |
|---|---|
| `OUTLOOK_MCP_URL` / `_TOKEN` | Real receipt emails + calendar reads |
| `BOX_MCP_URL` / `_TOKEN` | Real Box folder reads + approval workflow |

> ⚠️ The SDK rejects an `mcp` block with an **empty** URL at load, so the block
> ships **commented** in `configs/config.yaml`. Fill the URL, then uncomment.

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
       "data":{"claim_id":"CLM-DEMO-001","message":"expenses for my Acme trip"}}'
```

`CLM-DEMO-001` includes an illegible receipt on purpose — watch Odo ask the
employee rather than guess. On approval, Sol renders the approved pack to `./out/`
and appends `./data/expense_ledger.json`.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real Outlook/Box connectors add `leafmesh[mcp]`. Avoid
> `leafmesh[all]` on Python 3.12+ (it pulls `cchardet`, which has no wheel) — add
> only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*
