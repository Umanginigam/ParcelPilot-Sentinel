"""STEP 6 — Golden trap cases (no LLM, no UI, no orchestration).

These run against the deterministic resolution engine + scoped tools directly,
so the hardest part of the assignment is PROVEN CORRECT before a single line of
agent or frontend code exists. This file is also the Trust/Reliability (Problem
2) deliverable: it is the regression guard against policy drift.

Run:  cd parcelpilot-sentinel && python build_data.py && pytest -q
"""
import pytest

from src import resolution_engine as E
from src import tools
from src import auth
from src.auth import AccessDenied
from src.agent_tools import _retriever


# ---------------------------------------------------------------------------
# CANCELLATION — the flagship conflict
# ---------------------------------------------------------------------------
def test_northstar_cancellation_is_free_agreement_overrides_sop():
    """ORD-1001: BOOKED, requested 120m after booking. SOP would charge INR 250;
    Northstar agreement waives it. Historical TKT-450 wrongly says INR 250."""
    r = E.resolve_cancellation("ORD-1001")
    assert r.details["fee_inr"] == 0
    assert "No cancellation fee" in r.answer
    assert "05_Northstar_Logistics_Enterprise_Agreement.pdf" in r.sources_used
    assert any("SOP" in o for o in r.sources_overridden)          # override recorded
    assert any("TKT-450" in h for h in r.historical_conflicts)    # wrong ticket flagged


def test_standard_account_cancellation_charges_fee_after_window():
    """ORD-3001 (Beacon, no agreement): requested 15m after booking -> free.
    Proves the rule GENERALISES rather than always waiving."""
    r = E.resolve_cancellation("ORD-3001")
    assert r.details["fee_inr"] == 0            # within 30-minute free window
    assert "03_Cancellation_and_Service_Credit_SOP_v4.pdf" in r.sources_used
    assert r.sources_overridden == []           # no agreement, no override


def test_picked_up_order_cannot_be_cancelled():
    """ORD-1002: PICKED_UP -> return-to-origin, not cancellation."""
    r = E.resolve_cancellation("ORD-1002")
    assert "return-to-origin" in r.answer.lower()


# ---------------------------------------------------------------------------
# SERVICE CREDIT — account-specific thresholds
# ---------------------------------------------------------------------------
def test_lumenworks_credit_uses_4h_threshold_and_fixed_300():
    """ORD-2002: carrier fault, still not picked up at snapshot. Delay from
    window-end (06:30) to snapshot (11:00) = 4.5h > LumenWorks 4h -> fixed 300."""
    r = E.resolve_service_credit("ORD-2002")
    assert r.details["amount_inr"] == 300
    assert "06_LumenWorks_Service_Agreement.pdf" in r.sources_used
    assert any("default" in o for o in r.sources_overridden)


def test_credit_denied_when_fault_not_established():
    """ORD-2001: no carrier fault, no customer fault -> do not promise; escalate."""
    r = E.resolve_service_credit("ORD-2001")
    assert r.escalate is True
    assert "fault" in (r.escalate_reason or "").lower()


# ---------------------------------------------------------------------------
# SLA — agreement overrides default plan targets
# ---------------------------------------------------------------------------
def test_northstar_p1_sla_is_15_minutes_not_default_30():
    r = E.resolve_sla("ACCT-001", "P1")
    assert r.details["minutes"] == 15
    assert "05_Northstar_Logistics_Enterprise_Agreement.pdf" in r.sources_used


def test_default_enterprise_p1_sla_is_30_minutes():
    """ACCT-004 (Axis, Enterprise, no agreement) falls back to Policy v3."""
    r = E.resolve_sla("ACCT-004", "P1")
    assert r.details["minutes"] == 30
    assert "01_Support_Policy_v3_CURRENT.pdf" in r.sources_used


# ---------------------------------------------------------------------------
# ESCALATION classification (P1 triggers)
# ---------------------------------------------------------------------------
def test_api_key_exposure_escalates_as_p1_security():
    r = E.classify_escalation(
        "Possible API key exposure",
        "An employee posted a screenshot containing a production API key.")
    assert r.escalate and r.details["severity"] == "P1"
    assert "security" in (r.escalate_reason or "").lower()


def test_full_outage_escalates_as_p1():
    r = E.classify_escalation(
        "All shipment creation is failing",
        "Every user gets HTTP 500 when creating any shipment.")
    assert r.escalate and r.details["severity"] == "P1"


# ---------------------------------------------------------------------------
# ACCESS CONTROL — enforced in the tool layer, not the prompt
# ---------------------------------------------------------------------------
def test_customer_cannot_read_another_accounts_order():
    lumen = auth.customer("ACCT-002")
    with pytest.raises(AccessDenied):
        tools.lookup_order(lumen, "ORD-1001")     # ORD-1001 belongs to ACCT-001


def test_customer_can_read_own_order():
    northstar = auth.customer("ACCT-001")
    order = tools.lookup_order(northstar, "ORD-1001")
    assert order["account_id"] == "ACCT-001"


def test_internal_can_read_any_account():
    ops = auth.internal()
    assert tools.lookup_order(ops, "ORD-1001")["account_id"] == "ACCT-001"
    assert tools.lookup_order(ops, "ORD-2002")["account_id"] == "ACCT-002"


# ---------------------------------------------------------------------------
# ACTION TOOL — prepare never writes; confirmation gates commit
# ---------------------------------------------------------------------------
def test_prepare_escalation_requires_confirmation_and_does_not_write():
    ops = auth.internal()
    plan = tools.EscalationPlan(
        account_id="ACCT-001", subject="All shipment creation failing",
        severity="P1", reason="P1 outage", linked_ticket_id="TKT-501")
    prepared = tools.prepare_escalation(ops, plan)
    assert prepared["requires_confirmation"] is True
    assert "status" not in prepared            # nothing created yet
# ---------------------------------------------------------------------------
# DOCUMENT PRIVACY — retrieval layer
# ---------------------------------------------------------------------------

def test_internal_can_retrieve_customer_agreements():
    """
    Internal ParcelPilot staff may retrieve customer agreements.
    """

    ops = auth.internal()

    results = _retriever().retrieve(
        "Northstar cancellation fee agreement",
        account_id=None,
        include_all_accounts=True,
        k=10,
    )

    doc_ids = {
        result.section.doc_id
        for result in results
    }

    assert "05_Northstar_Logistics_Enterprise_Agreement.pdf" in doc_ids