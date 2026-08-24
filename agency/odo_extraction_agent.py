"""Odo — Proofs & Extraction Analyst.

auto_discover matches `odo_extraction_agent` to the YAML agent. Odo (an
llm + super_agent) reads proofs through its tools and produces confidence-scored
line-items. The MODEL decides and pulls; this CODE fails closed.

@chain enforce_confidence_floor — the deterministic floor a prompt can't waive:
a field the model scored low, or a line-item missing an amount, or an illegible
proof, can NEVER be passed downstream as "clean". If anything is uncertain, the
extract is forced un-clean and turned into a question for the employee — a
guessed number never reaches Fern's form.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from leafmesh import LeafMeshLogger, chain

logger = LeafMeshLogger(__name__)

_CONFIDENCE_MIN = 0.85


def enforce_confidence_floor(result: Any, context: dict) -> dict:
    """Fail closed: never hand a low-confidence / incomplete extract to Fern."""
    result = result if isinstance(result, dict) else {}
    line_items = result.get("line_items") or []
    low_conf = list(result.get("low_confidence_fields") or [])

    # Deterministic re-check the model cannot talk its way past.
    for li in line_items if isinstance(line_items, list) else []:
        if not isinstance(li, dict):
            continue
        if li.get("amount") in (None, "", 0) and not li.get("amount_zero_ok"):
            low_conf.append(f"{li.get('proof_id', 'proof')}:amount")
        for field in ("merchant", "date", "amount"):
            score = li.get(f"{field}_confidence")
            if isinstance(score, (int, float)) and score < _CONFIDENCE_MIN:
                low_conf.append(f"{li.get('proof_id', 'proof')}:{field}")

    low_conf = sorted(set(low_conf))
    result["low_confidence_fields"] = low_conf

    if low_conf:
        result["extract_clean"] = False
        if not result.get("question_for_employee"):
            result["question_for_employee"] = (
                "We could not read these with confidence — please confirm: "
                + ", ".join(low_conf)
            )
        logger.info(f"[odo] confidence floor held extract un-clean: {low_conf}")
    else:
        # Only 'clean' when there is genuinely something and nothing uncertain.
        result["extract_clean"] = bool(line_items) and not result.get("policy_flags")
    return result


@chain(enforce_confidence_floor)
async def odo_extraction_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    """Return the model's confidence-scored extraction; the floor re-checks it."""
    out = llm_response if isinstance(llm_response, dict) else {}
    # Normalise to the yields contract so downstream conditions never read a
    # missing field (conditions fail closed on absence).
    out.setdefault("extract_clean", False)
    out.setdefault("claim_class", "")
    out.setdefault("low_confidence_fields", [])
    out.setdefault("policy_flags", [])
    out.setdefault("line_items", [])
    out.setdefault("question_for_employee", "")
    return out
