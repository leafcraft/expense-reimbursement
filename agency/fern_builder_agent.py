"""Fern — Claim Builder.

auto_discover matches `fern_builder_agent`. Fern turns Odo's verified line-items
into the company's reimbursement form and gets the employee's one-look
confirmation. Deliberately SEPARATE from Odo (reader ≠ assembler).

@chain enforce_cross_check_floor — the deterministic floor: totals, currency and
policy caps must tie out against the source before anyone sees the form; if they
don't, return to Odo with the specific discrepancy — NEVER adjust a number to
make it balance. The back-edge is bounded: Odo gets ONE more pass (counted per
session); after that `retry_exhausted` is true and the claim goes to the
Finance-Ops Lead. Policy caps are checked earlier, by Odo's floor. A confirmed
form renders to ./out.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared.session_stash import resolve_session_id, stash_get, stash_put
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared.session_stash import resolve_session_id, stash_get, stash_put  # type: ignore

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")
_MAX_RETRIES = 1        # one re-extraction pass, then the Finance-Ops Lead


def _render_draft(result: dict) -> str:
    """Render the draft reimbursement form to ./out (Markdown fallback of your
    Word/Excel template). Returns the path."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    claim_id = str(result.get("claim_id") or "claim")
    path = _OUT_DIR / f"{claim_id}_reimbursement_draft.md"
    lines = [f"# Reimbursement claim — {claim_id}", ""]
    total = 0.0
    for li in result.get("line_items") or []:
        amt = li.get("amount") or 0
        total += float(amt or 0)
        lines.append(f"- {li.get('date','')}  {li.get('merchant','')}  "
                     f"{li.get('category','')}  {li.get('currency','')} {amt}")
    lines += ["", f"**Total: {total:.2f}**", "",
              "_Draft — awaiting employee confirmation. Every field traceable to a proof._"]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def enforce_cross_check_floor(result: Any, context: dict) -> dict:
    """Fail closed: the form must tie out to the source, or it goes back to Odo."""
    result = result if isinstance(result, dict) else {}
    line_items = result.get("line_items") or []

    stated_total = result.get("stated_total")
    computed = sum(float(li.get("amount") or 0) for li in line_items if isinstance(li, dict))
    result["computed_total"] = round(computed, 2)

    ok = True
    discrepancy = ""
    if isinstance(stated_total, (int, float)) and abs(float(stated_total) - computed) > 0.01:
        ok = False
        discrepancy = f"stated total {stated_total} != sum of line-items {computed:.2f}"
    if any((li.get("amount") in (None, "")) for li in line_items if isinstance(li, dict)):
        ok = False
        discrepancy = discrepancy or "a line-item is missing an amount"

    result["cross_check_ok"] = ok
    result["discrepancy"] = discrepancy

    sid = str(result.pop("_session_id", "") or "")
    if not ok:
        # Bounded back-edge to Odo — never balance the numbers ourselves.
        # Count by session, else by claim. With neither there is no way to
        # bound the loop, so it goes straight to the Lead (fail closed).
        claim_key = str(result.get("claim_id") or "")
        key = (f"{sid}:fern_retries" if sid
               else f"claim:{claim_key}:fern_retries" if claim_key else "")
        if key:
            rounds = int(stash_get(key).get("rounds", 0)) + 1
            stash_put(key, {"rounds": rounds})
        else:
            rounds = _MAX_RETRIES + 1
        result["retry_exhausted"] = rounds > _MAX_RETRIES
        result["form_built"] = False
        result["awaiting_confirmation"] = False
        result["confirmed"] = False
        logger.info(f"[fern] cross-check floor held: {discrepancy} "
                    f"(round {rounds}, exhausted={result['retry_exhausted']})")
        return result
    result["retry_exhausted"] = False

    # Ties out → build the draft and ask the employee to confirm (once).
    if not result.get("confirmed"):
        result["form_built"] = True
        result["artifact_path"] = _render_draft(result)
        result["awaiting_confirmation"] = True
    return result


@chain(enforce_cross_check_floor)
async def fern_builder_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    out = llm_response if isinstance(llm_response, dict) else {}
    out.setdefault("form_built", False)
    out.setdefault("cross_check_ok", False)
    out.setdefault("discrepancy", "")
    out.setdefault("awaiting_confirmation", False)
    out.setdefault("confirmed", False)
    out.setdefault("artifact_path", "")
    out.setdefault("retry_exhausted", False)
    out.setdefault("line_items", (input_data or {}).get("line_items", []))
    out["_session_id"] = resolve_session_id(input_data if isinstance(input_data, dict) else {},
                                            context if isinstance(context, dict) else {})
    return out
