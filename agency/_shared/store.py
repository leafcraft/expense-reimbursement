"""Dev store — a working stand-in for the systems of record, so the pod runs
day-0 with NO connector wired.

This is a DEV STAND-IN, not a system of record. In production the proof reads
come from Outlook/Box (the mcp block in the configuration), the outbox is the Box
approval workflow, and the ledger is your finance system. **The function
signatures are the contract you swap real systems into** — the mesh does not
change.

Nothing here writes to a system of record; it holds seed proofs (so Odo has
something to read) and appends the pod's own outbox + append-only ledger under
./data. Per the doctrine (where-data-lives): a real store enforces its own
invariants — this file is dev only.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DATA_DIR = Path("./data")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(name: str, default: Any) -> Any:
    p = _DATA_DIR / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(name: str, data: Any) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _DATA_DIR / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(_DATA_DIR / name)


# ── Expense policy — caps per trip class and category, in USD. A real team
#    keeps these in the travel & expense policy; Odo reads them with the
#    read_expense_policy tool and Odo's floor re-checks USD lines against them.
#    lodging = per night, meals = per day, airfare = per ticket (economy). ──
POLICY_CURRENCY = "USD"
POLICY_CAPS: dict[str, dict[str, float]] = {
    "local":         {"meals": 40.0,  "ground_transport": 60.0},
    "domestic":      {"lodging": 250.0, "meals": 75.0,  "airfare": 750.0,  "ground_transport": 120.0},
    "international": {"lodging": 325.0, "meals": 100.0, "airfare": 2500.0, "ground_transport": 150.0},
}


def read_policy(claim_class: str) -> dict[str, Any]:
    caps = POLICY_CAPS.get(str(claim_class or "").strip().lower())
    if caps is None:
        return {"available": False,
                "reason": f"no policy set for class {claim_class!r} (local | domestic | international)"}
    return {"available": True, "claim_class": claim_class, "currency": POLICY_CURRENCY,
            "caps": caps, "per": {"lodging": "night", "meals": "day",
                                  "airfare": "ticket", "ground_transport": "day"}}


# ── Seed proofs — sample claims so the pod demonstrates every route on first
#    run. Replace with real Outlook/Box reads (see the mcp block in the configuration).
#    People and merchants are fictional. ──
SEED_CLAIMS: dict[str, dict[str, Any]] = {
    # Question route: one meal receipt is an unreadable scan, and the trip has
    # two hotel nights but only one hotel invoice.
    "CLM-DEMO-001": {
        "employee_id": "emp-1042",
        "employee_name": "Ana Rivera",
        "trip": {"purpose": "Client visit — Halvorsen Freight, Chicago", "class": "domestic",
                 "start": "2026-05-04", "end": "2026-05-06"},
        "proofs": [
            {"proof_id": "rc-1", "source": "outlook",
             "merchant": "Altavia Airways", "date": "2026-05-04",
             "amount": 312.40, "currency": "USD", "tax": 24.10,
             "category": "airfare", "legible": True},
            {"proof_id": "rc-2", "source": "box",
             "merchant": "Larkspur Hotel Loop", "date": "2026-05-05",
             "amount": 189.00, "currency": "USD", "tax": 15.12,
             "category": "lodging", "nights": 1, "legible": True},
            {"proof_id": "rc-3", "source": "outlook",
             "merchant": "(unreadable scan)", "date": "2026-05-05",
             "amount": None, "currency": "USD", "tax": None,
             "category": "meals", "legible": False},   # forces a question, not a guess
        ],
    },
    # International: amounts in EUR. Odo converts at the transaction-date rate
    # (amount_usd) before the caps are checked.
    "CLM-DEMO-002": {
        "employee_id": "emp-2277",
        "employee_name": "Kwame Osei",
        "trip": {"purpose": "Conference — Berlin", "class": "international",
                 "start": "2026-06-10", "end": "2026-06-13"},
        "proofs": [
            {"proof_id": "rc-4", "source": "box",
             "merchant": "Nordwind Air", "date": "2026-06-10",
             "amount": 842.00, "currency": "EUR", "tax": 0.0,
             "category": "airfare", "legible": True},
            {"proof_id": "rc-5", "source": "outlook",
             "merchant": "Hotel Spreebogen", "date": "2026-06-13",
             "amount": 567.00, "currency": "EUR", "tax": 37.09,
             "category": "lodging", "nights": 3, "legible": True},
        ],
    },
    # Happy path: clean, inside every cap -> form -> decision-maker -> Finance.
    # 286.20 + 2 x 174.00 + 48.60 = 682.80
    "CLM-DEMO-003": {
        "employee_id": "emp-3315",
        "employee_name": "Priya Natarajan",
        "trip": {"purpose": "Quarterly review — Denver office", "class": "domestic",
                 "start": "2026-06-16", "end": "2026-06-18"},
        "proofs": [
            {"proof_id": "rc-6", "source": "outlook",
             "merchant": "Altavia Airways", "date": "2026-06-16",
             "amount": 286.20, "currency": "USD", "tax": 21.35,
             "category": "airfare", "legible": True},
            {"proof_id": "rc-7", "source": "box",
             "merchant": "Cedar Ridge Suites", "date": "2026-06-18",
             "amount": 348.00, "currency": "USD", "tax": 27.84,
             "category": "lodging", "nights": 2, "legible": True},
            {"proof_id": "rc-8", "source": "outlook",
             "merchant": "Union Station Taxi Co.", "date": "2026-06-18",
             "amount": 48.60, "currency": "USD", "tax": 0.0,
             "category": "ground_transport", "legible": True},
        ],
    },
    # Over a policy cap: $412 a night against the $250 domestic lodging cap
    # -> policy flag -> Finance-Ops Lead.
    "CLM-DEMO-004": {
        "employee_id": "emp-1042",
        "employee_name": "Ana Rivera",
        "trip": {"purpose": "Trade show — New York", "class": "domestic",
                 "start": "2026-07-07", "end": "2026-07-08"},
        "proofs": [
            {"proof_id": "rc-9", "source": "box",
             "merchant": "The Meridian Park Hotel", "date": "2026-07-08",
             "amount": 412.00, "currency": "USD", "tax": 59.74,
             "category": "lodging", "nights": 1, "legible": True},
            {"proof_id": "rc-10", "source": "outlook",
             "merchant": "Altavia Airways", "date": "2026-07-07",
             "amount": 264.80, "currency": "USD", "tax": 19.86,
             "category": "airfare", "legible": True},
        ],
    },
    # Duplicate: the Altavia ticket from CLM-DEMO-001 claimed again
    # (same merchant, date and amount) -> policy flag -> Finance-Ops Lead.
    "CLM-DEMO-005": {
        "employee_id": "emp-1042",
        "employee_name": "Ana Rivera",
        "trip": {"purpose": "Client visit — Halvorsen Freight, Chicago", "class": "domestic",
                 "start": "2026-05-04", "end": "2026-05-06"},
        "proofs": [
            {"proof_id": "rc-11", "source": "outlook",
             "merchant": "Altavia Airways", "date": "2026-05-04",
             "amount": 312.40, "currency": "USD", "tax": 24.10,
             "category": "airfare", "legible": True},
        ],
    },
}


# ── Proof reads (dev-store fallback for the mcp/connector path) ──────────────
def read_proofs(claim_id: str) -> dict[str, Any]:
    claim = SEED_CLAIMS.get(claim_id)
    if not claim:
        return {"available": False, "reason": f"no seed proofs for claim {claim_id!r}"}
    return {"available": True, "claim_id": claim_id,
            "employee_id": claim["employee_id"], "proofs": claim["proofs"]}


def read_calendar(claim_id: str) -> dict[str, Any]:
    claim = SEED_CLAIMS.get(claim_id)
    if not claim:
        return {"available": False, "reason": f"no seed trip for claim {claim_id!r}"}
    return {"available": True, "trip": claim["trip"]}


def list_prior_claims(employee_id: str) -> dict[str, Any]:
    prior = [cid for cid, c in SEED_CLAIMS.items() if c["employee_id"] == employee_id]
    return {"available": True, "employee_id": employee_id, "prior_claim_ids": prior}


def find_prior_receipt(merchant: str, date: str, amount: Any, claim_id: str = "") -> str:
    """claim_id of an EARLIER claim (claim ids sort by submission) holding the
    same receipt (same merchant, date and amount), or "". The first claim of a
    receipt is never its own duplicate. PROD: your expense system's receipt index."""
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        return ""
    key = (str(merchant or "").strip().lower(), str(date or "").strip())
    for cid, c in SEED_CLAIMS.items():
        if claim_id and cid >= claim_id:
            continue
        for pr in c["proofs"]:
            if pr.get("amount") is None:
                continue
            if (str(pr.get("merchant") or "").strip().lower(), str(pr.get("date") or "")) == key \
                    and round(float(pr["amount"]), 2) == amt:
                return cid
    return ""


# ── Outbox (Sol's sends) + append-only ledger ───────────────────────────────
def record_outbox(entry: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        outbox = _read_json("outbox.json", [])
        rec = {"recorded_at": _now(), **entry}
        outbox.append(rec)
        _write_json("outbox.json", outbox)
    return rec


def append_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    """Append-only expense ledger (dev mirror of the WORM sink for local demo)."""
    with _LOCK:
        ledger = _read_json("expense_ledger.json", [])
        rec = {"recorded_at": _now(), **entry}
        ledger.append(rec)
        _write_json("expense_ledger.json", ledger)
    return rec


# ── Dev-store recovery for the finisher (post-HITL, when upstream is dropped) ──
def put_approved_claim(claim_id: str, pack: dict[str, Any]) -> None:
    with _LOCK:
        store = _read_json("approved_claims.json", {})
        store[claim_id] = {"stored_at": _now(), **pack}
        _write_json("approved_claims.json", store)


def get_approved_claim(claim_id: str) -> dict[str, Any]:
    return _read_json("approved_claims.json", {}).get(claim_id, {})
