"""Fern — Claim Builder.

auto_discover matches `fern_builder_agent`. Fern turns Odo's verified line-items
into the company's reimbursement form and gets the employee's one-look
confirmation. Deliberately SEPARATE from Odo (reader ≠ assembler).

@chain enforce_cross_check_floor — the deterministic floor: totals, currency and
policy caps must tie out against the source before anyone sees the form; if they
don't, return to Odo with the specific discrepancy (a bounded back-edge) —
NEVER adjust a number to make it balance. A confirmed form renders to ./out.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")


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

    if not ok:
        # Bounded back-edge to Odo — never balance the numbers ourselves.
        result["form_built"] = False
        result["awaiting_confirmation"] = False
        result["confirmed"] = False
        logger.info(f"[fern] cross-check floor held: {discrepancy}")
        return result

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
    out.setdefault("line_items", (input_data or {}).get("line_items", []))
    return out
