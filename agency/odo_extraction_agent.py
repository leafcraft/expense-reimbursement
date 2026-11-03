"""Odo — Proofs & Extraction Analyst.

auto_discover matches `odo_extraction_agent` to the YAML agent. Odo (an
llm + super_agent) reads proofs through its tools and produces confidence-scored
line-items. The MODEL decides and pulls; this CODE fails closed.

@chain enforce_confidence_floor — the deterministic floor a prompt can't waive:
a field the model scored low, or a line-item missing an amount, or an illegible
proof, can NEVER be passed downstream as "clean". If anything is uncertain, the
extract is forced un-clean and turned into a question for the employee — a
guessed number never reaches Fern's form.

It also re-asserts two policy flags the model may miss (it may add flags, never
remove them): a USD line (or a line with `amount_usd`) above its cap in the
expense policy (store.POLICY_CAPS; lodging per night, meals per day), and a
receipt already claimed on an earlier claim (same merchant + date + amount).
Either flag keeps the extract un-clean and routes the claim to the Finance-Ops
Lead. Foreign-currency lines without `amount_usd` are left to Odo's own check.
"""
from __future__ import annotations

import os
import sys
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared import store
except ImportError:  # pragma: no cover
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)

_CONFIDENCE_MIN = 0.85


def _usd_amount(li: dict) -> float | None:
    for key in ("amount_usd",):
        if isinstance(li.get(key), (int, float)):
            return float(li[key])
    if str(li.get("currency") or "").upper() == store.POLICY_CURRENCY \
            and isinstance(li.get("amount"), (int, float)):
        return float(li["amount"])
    return None


def _policy_flags(result: dict) -> list[str]:
    """Deterministic policy re-check: caps + receipts already claimed."""
    flags: list[str] = []
    caps = store.POLICY_CAPS.get(str(result.get("claim_class") or "").strip().lower(), {})
    claim_id = str(result.get("_claim_id") or result.get("claim_id") or "")
    for li in result.get("line_items") or []:
        if not isinstance(li, dict):
            continue
        pid = li.get("proof_id", "proof")
        cat = str(li.get("category") or "").strip().lower()
        usd = _usd_amount(li)
        if usd is not None and cat in caps:
            units = li.get("nights") if cat == "lodging" else li.get("days")
            try:
                units = max(int(units or 1), 1)
            except (TypeError, ValueError):
                units = 1
            if usd / units > caps[cat] + 0.005:
                flags.append(f"over_cap:{pid}:{cat}")
        prior = store.find_prior_receipt(li.get("merchant"), li.get("date"),
                                         li.get("amount"), claim_id)
        if prior:
            flags.append(f"duplicate_receipt:{pid}:{prior}")
    return flags


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

    # Policy re-check — the model may RAISE flags, never lower them.
    flags = list(result.get("policy_flags") or [])
    for f in _policy_flags(result):
        if f not in flags:
            flags.append(f)
    result["policy_flags"] = flags
    result.pop("_claim_id", None)

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
    if isinstance(input_data, dict) and input_data.get("claim_id"):
        out["_claim_id"] = str(input_data["claim_id"])
    return out
