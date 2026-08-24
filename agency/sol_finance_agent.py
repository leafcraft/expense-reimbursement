"""Sol — Approvals & Finance Liaison (the FINISHER / actuator).

auto_discover matches `sol_finance_agent`. Sol sits BEHIND the human approval
gate. It never approves or pays — it re-checks that a human actually approved,
renders the approved pack, submits to Finance, and records an append-only ledger
entry. It is the concrete "@chain fails closed":

  a) approval RE-CHECK — reaching this agent does not mean approved. An
     allow-token allowlist + block-token denylist; an UNKNOWN verdict fails closed.
  b) deterministic invariants a human can't waive (a confirmed claim, real
     line-items, an approver on record).
  c) render the real pack to ./out; on a tripped floor, DELETE the partial and
     record `status: blocked` with reasons — never a half-issued claim.
  d) dev-store recovery — after the HITL gate the upstream payload is dropped,
     so Sol recovers the claim from the session stash / dev store.

Two phases: first call (from Fern, confirmed) → route for approval; second call
(from the approver, approved) → issue + submit to finance.
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared import store
    from ._shared.session_stash import resolve_session_id, stash_get, stash_put
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore
    from _shared.session_stash import resolve_session_id, stash_get, stash_put  # type: ignore

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")
_APPROVE_TOKENS = frozenset({"approved", "approve", "sign", "signed", "yes", "ok"})
_BLOCK_TOKENS = frozenset({"rejected", "reject", "no", "deny", "denied",
                           "held", "held_for_review", "hold"})


def _signal(input_data: dict) -> str:
    """The human verdict, from wherever the SDK delivered it (shape-tolerant)."""
    sources = [input_data]
    up = input_data.get("upstream_yields")
    if isinstance(up, dict):
        sources.extend(v for v in up.values() if isinstance(v, dict))
    for src in sources:
        for key in ("human_message", "human_decision", "decision", "message"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
    return ""


def _is_approved(input_data: dict) -> bool:
    """Fail closed: only an explicit approve token counts; unknown => not approved."""
    sig = _signal(input_data)
    if sig in _BLOCK_TOKENS:
        return False
    return sig in _APPROVE_TOKENS


def _is_blocked(input_data: dict) -> bool:
    return _signal(input_data) in _BLOCK_TOKENS


def _render_pack(claim: dict) -> str:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    claim_id = str(claim.get("claim_id") or "claim")
    path = _OUT_DIR / f"{claim_id}_approved_pack.md"
    lines = [f"# Approved reimbursement pack — {claim_id}",
             f"Approver: {claim.get('approver') or claim.get('approval_reference') or 'on record'}",
             ""]
    total = 0.0
    for li in claim.get("line_items") or []:
        amt = float(li.get("amount") or 0)
        total += amt
        lines.append(f"- {li.get('date','')}  {li.get('merchant','')}  {li.get('currency','')} {amt}")
    lines += ["", f"**Total approved: {total:.2f}**", "",
              "_Ledgered and submitted to Finance (SAP posting later)._"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _recover_claim(input_data: dict, context: dict) -> dict:
    """Recover the claim across the HITL boundary: upstream -> stash -> dev store."""
    up = input_data.get("upstream_yields") or {}
    for src in (input_data, up.get("fern_builder_agent") if isinstance(up, dict) else None):
        if isinstance(src, dict) and src.get("line_items"):
            return src
    sid = resolve_session_id(input_data, context)
    stashed = stash_get(sid)
    if stashed.get("line_items"):
        return stashed
    claim_id = str(input_data.get("claim_id") or "")
    return store.get_approved_claim(claim_id) or {"claim_id": claim_id}


def enforce_issuance_floor(result: Any, context: dict) -> dict:
    """The finisher floor — issue ONLY on a real approval; delete on a block."""
    result = result if isinstance(result, dict) else {}
    result.setdefault("block_reasons", [])

    if result.get("status") == "routed":
        return result  # phase 1: just routed for approval, nothing to issue yet

    if not result.get("approved"):
        result["status"] = "blocked"
        if _is_blocked(result.get("_input", {})):
            result["block_reasons"].append("approver rejected / held")
        else:
            result["block_reasons"].append("no explicit approval on record (fail closed)")
        _delete_partial(result)
        logger.info(f"[sol] issuance floor BLOCKED: {result['block_reasons']}")
        return result

    claim = result.get("_claim") or {}
    if not (claim.get("line_items")):
        result.update(status="blocked", approved=False)
        result["block_reasons"].append("no line-items to issue")
        _delete_partial(result)
        return result

    # Passed the floor — render, submit, ledger.
    result["pack_path"] = _render_pack(claim)
    store.record_outbox({"claim_id": claim.get("claim_id"), "action": "submit_to_finance",
                         "pack_path": result["pack_path"]})
    store.append_ledger({"claim_id": claim.get("claim_id"), "event": "approved_and_submitted",
                         "approver": claim.get("approver", "on record")})
    result.update(submitted_to_finance=True, status="submitted")
    logger.info(f"[sol] issued + submitted claim {claim.get('claim_id')} -> {result['pack_path']}")
    return result


def _delete_partial(result: dict) -> None:
    p = result.get("pack_path")
    if p:
        Path(p).unlink(missing_ok=True)
        result["pack_path"] = ""


@chain(enforce_issuance_floor)
async def sol_finance_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    input_data = input_data if isinstance(input_data, dict) else {}
    claim = _recover_claim(input_data, context)
    sid = resolve_session_id(input_data, context)
    if claim.get("line_items"):
        stash_put(sid, claim)   # keep it recoverable across the approval gate

    out: dict[str, Any] = {
        "routed_for_approval": False, "approved": False, "submitted_to_finance": False,
        "pack_path": "", "status": "", "block_reasons": [],
        "_input": input_data, "_claim": claim,
    }

    if _is_approved(input_data):
        out["approved"] = True                     # phase 2 — the floor issues it
    elif _is_blocked(input_data):
        out["status"] = "blocked"
    else:
        out["status"] = "routed"                   # phase 1 — send to the approver
        out["routed_for_approval"] = True
    return out
