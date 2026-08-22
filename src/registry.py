"""Source registry — the metadata layer that separates AUTHORITY from RETRIEVAL.

Two things live here, both assigned by a human at ingestion (never inferred by
the model at query time):

1. SOURCES: per-document metadata (tier, status, effective_date, scope). This is
   what a person fills in when a new file is added — and why "add more data"
   just works: the rules read this table, not the model.

2. ACCOUNT_POLICY / DEFAULT_POLICY: the *structured rule parameters* transcribed
   from each authoritative document, each tagged with the source it came from.
   We do NOT regex fees out of PDFs; a human encodes the rule and links it to the
   governing document, and the golden tests guard against drift.

Note the deliberate design line: parameters are keyed to ACCOUNT metadata
(does this account's agreement waive fees? what is their credit threshold?),
never to specific order IDs. The engine therefore generalises to any order/
account in the pack rather than hard-coding example answers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from . import config as C


# --- document metadata -------------------------------------------------------
@dataclass(frozen=True)
class Source:
    doc_id: str
    title: str
    tier: int
    status: str                 # "current" | "deprecated"
    effective_date: date
    scope: str                  # "global" or an account_id like "ACCT-001"

    @property
    def authoritative(self) -> bool:
        return self.tier > C.NON_AUTHORITATIVE_MAX_TIER


SOURCES: dict[str, Source] = {
    "01_Support_Policy_v3_CURRENT.pdf": Source(
        "01_Support_Policy_v3_CURRENT.pdf", "Support Policy v3",
        C.TIER_CURRENT_POLICY, "current", date(2026, 5, 1), "global"),
    "02_Support_Policy_v2_DEPRECATED.pdf": Source(
        "02_Support_Policy_v2_DEPRECATED.pdf", "Support Policy v2 (DEPRECATED)",
        C.TIER_DEPRECATED_POLICY, "deprecated", date(2025, 1, 1), "global"),
    "03_Cancellation_and_Service_Credit_SOP_v4.pdf": Source(
        "03_Cancellation_and_Service_Credit_SOP_v4.pdf",
        "Cancellation & Service Credit SOP v4",
        C.TIER_CURRENT_POLICY, "current", date(2026, 6, 1), "global"),
    "04_Product_Operations_Guide_and_Known_Issues.pdf": Source(
        "04_Product_Operations_Guide_and_Known_Issues.pdf",
        "Product Operations Guide & Known Issues",
        C.TIER_CURRENT_POLICY, "current", date(2026, 8, 14), "global"),
    "05_Northstar_Logistics_Enterprise_Agreement.pdf": Source(
        "05_Northstar_Logistics_Enterprise_Agreement.pdf",
        "Northstar Logistics Enterprise Agreement",
        C.TIER_CUSTOMER_AGREEMENT, "current", date(2026, 1, 1), "ACCT-001"),
    "06_LumenWorks_Service_Agreement.pdf": Source(
        "06_LumenWorks_Service_Agreement.pdf", "LumenWorks Service Agreement",
        C.TIER_CUSTOMER_AGREEMENT, "current", date(2026, 3, 1), "ACCT-002"),
}


# --- structured policy parameters -------------------------------------------
@dataclass(frozen=True)
class CreditRule:
    """A failed-pickup service-credit rule."""
    threshold_hours: float                # pickup delay past window-end to qualify
    fixed_inr: Optional[int] = None       # fixed amount, if the agreement sets one
    pct_of_fee: Optional[float] = None     # else % of shipment fee ...
    cap_inr: Optional[int] = None          # ... capped at this
    manager_approval_above_inr: Optional[int] = None
    monthly_cap_inr: Optional[int] = None
    source: str = ""


# Default global policy, transcribed from SOP v4 (03) and Support Policy v3 (01).
DEFAULT_CANCELLATION = {
    "free_window_min": 30,
    "fee_inr": 250,
    "source": "03_Cancellation_and_Service_Credit_SOP_v4.pdf",
}
DEFAULT_CREDIT = CreditRule(
    threshold_hours=2.0, pct_of_fee=0.10, cap_inr=500,
    manager_approval_above_inr=1000,
    source="03_Cancellation_and_Service_Credit_SOP_v4.pdf",
)
# First-response SLA targets (minutes). basis: "clock" = 24x7, "business" = business hours.
DEFAULT_SLA = {
    "Enterprise": {"P1": (30, "clock"), "P2": (120, "clock"), "P3": (480, "business")},
    "Growth":     {"P1": (120, "business"), "P2": (240, "business"), "P3": (960, "business")},
    "Standard":   {"P1": (240, "business"), "P2": (480, "business"), "P3": (960, "business")},
}
DEFAULT_SLA_SOURCE = "01_Support_Policy_v3_CURRENT.pdf"


@dataclass(frozen=True)
class AccountPolicy:
    """Per-account overrides. Any field left None falls back to the default."""
    cancellation_fee_waived: Optional[bool] = None
    credit_rule: Optional[CreditRule] = None
    sla: Optional[dict] = None            # {"P1": (minutes, basis), ...}
    sla_source: Optional[str] = None
    monthly_credit_cap_inr: Optional[int] = None
    agreement_source: Optional[str] = None


ACCOUNT_POLICY: dict[str, AccountPolicy] = {
    # Northstar (05): waives all BOOKED-before-pickup cancellation fees; keeps
    # SOP credit rule but adds a monthly aggregate cap; custom SLA.
    "ACCT-001": AccountPolicy(
        cancellation_fee_waived=True,
        credit_rule=None,                       # "current SOP applies"
        monthly_credit_cap_inr=5000,
        sla={"P1": (15, "clock"), "P2": (60, "clock"), "P3": (480, "business")},
        sla_source="05_Northstar_Logistics_Enterprise_Agreement.pdf",
        agreement_source="05_Northstar_Logistics_Enterprise_Agreement.pdf",
    ),
    # LumenWorks (06): no cancellation waiver; REPLACES the credit threshold and
    # amount with 4h / fixed INR 300; custom SLA, no weekend coverage.
    "ACCT-002": AccountPolicy(
        cancellation_fee_waived=False,
        credit_rule=CreditRule(
            threshold_hours=4.0, fixed_inr=300,
            manager_approval_above_inr=1000,
            source="06_LumenWorks_Service_Agreement.pdf"),
        sla={"P1": (120, "business"), "P2": (240, "business"), "P3": (960, "business")},
        sla_source="06_LumenWorks_Service_Agreement.pdf",
        agreement_source="06_LumenWorks_Service_Agreement.pdf",
    ),
    # ACCT-003 (Beacon), ACCT-004 (Axis): no agreement in pack -> all defaults.
}


def account_policy(account_id: str) -> AccountPolicy:
    return ACCOUNT_POLICY.get(account_id, AccountPolicy())
