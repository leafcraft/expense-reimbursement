"""Global tools for the expense-reimbursement pod.

These are Odo's day-0 tool surface — the tools it calls, in the turn, to PULL
proofs. Each reads the dev store (seed proofs) so the pod runs with no connector
wired, and **each announces itself**: when there is no real source and no seed,
it returns `available: false` and says why — never a synthetic success that
looks like a real read. To go live, wire the Outlook/Box mcp block in
config.yaml (each named action becomes its own tool); these dev tools are the
fallback contract.
"""
import os

from leafmesh import global_tool, LeafMeshLogger

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


def _connector_wired() -> bool:
    """True if a real proof connector is configured (Outlook/Box mcp URL set)."""
    return bool(os.getenv("OUTLOOK_MCP_URL") or os.getenv("BOX_MCP_URL"))


@global_tool(category="extraction")
def read_proofs(claim_id: str) -> dict:
    """Read every proof attached to a claim (receipts, invoices).

    Returns each proof with merchant, date, amount, currency, tax, category, and
    a `legible` flag. When no real connector is wired, reads the seed store.
    Announces `available: false` if there is genuinely nothing to read.

    Args:
        claim_id: The claim to read proofs for (e.g. "CLM-DEMO-001").
    """
    result = store.read_proofs(str(claim_id).strip())
    if not result.get("available") and _connector_wired():
        # A connector IS wired but this claim has no seed — the real path would
        # answer here; surface unreachable rather than an empty-but-confident 0.
        return {"available": False, "reason": "connector wired but returned nothing for this claim"}
    logger.info(f"read_proofs claim={claim_id} available={result.get('available')}")
    return result


@global_tool(category="extraction")
def read_calendar_window(claim_id: str) -> dict:
    """Read the trip window (purpose, class, dates) for a claim, to detect proofs
    missing against the trip (e.g. a hotel night with no invoice).

    Args:
        claim_id: The claim to read the trip window for.
    """
    return store.read_calendar(str(claim_id).strip())


@global_tool(category="extraction")
def list_prior_claims(employee_id: str) -> dict:
    """List an employee's prior claim ids, for duplicate-receipt detection across
    this and previous claims.

    Args:
        employee_id: The employee whose prior claims to list.
    """
    return store.list_prior_claims(str(employee_id).strip())
