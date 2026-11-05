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

from leafmesh import connection_rows, global_tool, LeafMeshLogger
from leafmesh.vault.refs import UnresolvedVaultRef

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


async def _vault_record_exists(name: str) -> bool:
    """True when the vault holds a record called `name` (Studio → Infrastructure).
    The record existing is the "real connector is wired" signal; its address
    and token stay in the vault and are never read here."""
    try:
        await connection_rows(name)
        return True
    except UnresolvedVaultRef:
        return False
    except PermissionError:  # SecretNotAllowed: the record exists; it only limits which agents read it
        return True


async def _connector_wired() -> bool:
    """True if a real proof connector is set up (vault record 'outlook_mcp' or 'box_mcp')."""
    return await _vault_record_exists("outlook_mcp") or await _vault_record_exists("box_mcp")


@global_tool(category="extraction")
async def read_proofs(claim_id: str) -> dict:
    """Read every proof attached to a claim (receipts, invoices).

    Returns each proof with merchant, date, amount, currency, tax, category, and
    a `legible` flag. When no real connector is wired, reads the seed store.
    Announces `available: false` if there is genuinely nothing to read.

    Args:
        claim_id: The claim to read proofs for (e.g. "CLM-DEMO-001").
    """
    result = store.read_proofs(str(claim_id).strip())
    if not result.get("available"):
        if await _connector_wired():
            # A connector IS wired but this claim has no seed — read it with the
            # outlook_/box_ MCP tools; never an empty-but-confident 0.
            return {"available": False,
                    "reason": "not in the seed store — read it with the outlook_/box_ MCP tools"}
        return {"available": False,
                "reason": (f"{result.get('reason')}; to read real proofs create vault record "
                           "'outlook_mcp' or 'box_mcp' on Infrastructure → Integrations → MCP "
                           "and uncomment the mcp block")}
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


@global_tool(category="extraction")
def read_expense_policy(claim_class: str) -> dict:
    """Read the expense policy caps for a trip class (local / domestic /
    international): USD caps per category — lodging per night, meals per day,
    airfare per ticket, ground transport per day.

    Args:
        claim_class: local | domestic | international.
    """
    return store.read_policy(str(claim_class).strip())
