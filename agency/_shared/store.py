"""Dev store — a working stand-in for the systems of record, so the pod runs
day-0 with NO connector wired.

This is a DEV STAND-IN, not a system of record. In production the proof reads
come from Outlook/Box (the mcp block in config.yaml), the outbox is the Box
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


# ── Seed proofs — two sample claims so the pod demonstrates end-to-end on
#    first run. Replace with real Outlook/Box reads (see config.yaml mcp block). ──
SEED_CLAIMS: dict[str, dict[str, Any]] = {
    "CLM-DEMO-001": {
        "employee_id": "emp-1042",
        "employee_name": "A. Rivera",
        "trip": {"purpose": "Client visit — Acme", "class": "domestic",
                 "start": "2026-05-04", "end": "2026-05-06"},
        "proofs": [
            {"proof_id": "rc-1", "source": "outlook",
             "merchant": "SkyJet Airways", "date": "2026-05-04",
             "amount": 312.40, "currency": "USD", "tax": 24.10,
             "category": "airfare", "legible": True},
            {"proof_id": "rc-2", "source": "box",
             "merchant": "Grand Plaza Hotel", "date": "2026-05-05",
             "amount": 189.00, "currency": "USD", "tax": 15.12,
             "category": "lodging", "legible": True},
            {"proof_id": "rc-3", "source": "outlook",
             "merchant": "(unreadable scan)", "date": "2026-05-05",
             "amount": None, "currency": "USD", "tax": None,
             "category": "meals", "legible": False},   # forces a question, not a guess
        ],
    },
    "CLM-DEMO-002": {
        "employee_id": "emp-2277",
        "employee_name": "M. Osei",
        "trip": {"purpose": "Conference — Berlin", "class": "international",
                 "start": "2026-06-10", "end": "2026-06-13"},
        "proofs": [
            {"proof_id": "rc-4", "source": "box",
             "merchant": "Lufthansa", "date": "2026-06-10",
             "amount": 842.00, "currency": "EUR", "tax": 0.0,
             "category": "airfare", "legible": True},
        ],
    },
}


# ── Proof reads (dev-store fallback for the mcp/connector path) ──────────────
def read_proofs(claim_id: str) -> dict[str, Any]:
    claim = SEED_CLAIMS.get(claim_id)
    if not claim:
        return {"available": False, "reason": f"no seed proofs for claim {claim_id!r}; wire OUTLOOK_MCP_URL/BOX_MCP_URL"}
    return {"available": True, "claim_id": claim_id,
            "employee_id": claim["employee_id"], "proofs": claim["proofs"]}


def read_calendar(claim_id: str) -> dict[str, Any]:
    claim = SEED_CLAIMS.get(claim_id)
    if not claim:
        return {"available": False, "reason": "no seed calendar; wire OUTLOOK_MCP_URL"}
    return {"available": True, "trip": claim["trip"]}


def list_prior_claims(employee_id: str) -> dict[str, Any]:
    prior = [cid for cid, c in SEED_CLAIMS.items() if c["employee_id"] == employee_id]
    return {"available": True, "employee_id": employee_id, "prior_claim_ids": prior}


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
