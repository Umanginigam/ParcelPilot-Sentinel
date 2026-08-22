"""STEP 5 — Authority + conflict engine (the deterministic core).

The engine turns a question + account/order facts into a STRUCTURED RULING, not
prose. The LLM's only job downstream is to narrate this. That is what converts
"confidently wrong" into "auditable and correct".

Two conflict rules are applied SEPARATELY and named in the output, because they
are genuinely different checks that compose:

  * FRESHNESS  — a deprecated source is demoted; it can never be the ruling basis.
  * SCOPE/OVERRIDE — an in-scope customer agreement overrides the global default
                     for the specific dimension it addresses.

Historical ticket resolutions are surfaced as `historical_conflicts` when they
disagree with the ruling — proving the system deliberately ignored planted
wrong guidance rather than never seeing it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import db
from . import registry as R
from . import config as C


# --- ruling container --------------------------------------------------------
@dataclass
class Ruling:
    question_type: str
    answer: str
    rule_applied: str
    sources_used: list[str] = field(default_factory=list)
    sources_overridden: list[str] = field(default_factory=list)   # (source, why)
    historical_conflicts: list[str] = field(default_factory=list)
    confidence: str = "high"          # high | medium | low
    escalate: bool = False
    escalate_reason: Optional[str] = None
    details: dict = field(default_factory=dict)


# --- helpers -----------------------------------------------------------------
def _hours_between(a, b) -> float:
    return (b - a).total_seconds() / 3600.0


def _truthy(value) -> bool:
    """Excel booleans survive as bool, int (1/0), or text ('TRUE') depending on
    the writer. Normalise all of them."""
    if isinstance(value, str):
        return value.strip().upper() in ("TRUE", "1", "YES")
    return bool(value)


# --- cancellation ------------------------------------------------------------
def resolve_cancellation(order_id: str) -> Ruling:
    order = db.get_order(order_id)
    if not order:
        return Ruling("cancellation", f"Order {order_id} not found.", "n/a",
                      confidence="low", escalate=True,
                      escalate_reason="unknown order")

    acct = order["account_id"]
    ap = R.account_policy(acct)
    status = order["status"]
    default = R.DEFAULT_CANCELLATION
    used, overridden, hist = [], [], []

    # terminal states first (SOP v4 §1)
    if status == "PICKED_UP":
        return Ruling("cancellation",
                      "Cannot cancel: shipment already PICKED_UP. Use the "
                      "return-to-origin workflow instead.",
                      "SOP v4: PICKED_UP not cancellable",
                      sources_used=[default["source"]],
                      details={"status": status})
    if status == "DELIVERED":
        return Ruling("cancellation", "Cannot cancel: shipment already DELIVERED.",
                      "SOP v4: DELIVERED not cancellable",
                      sources_used=[default["source"]], details={"status": status})

    # BOOKED / DRAFT — compute the default fee, then apply overrides.
    booked = db.parse_dt(order["booked_at"])
    req = db.parse_dt(order["cancellation_requested_at"]) or C.SNAPSHOT_TIME
    mins = (req - booked).total_seconds() / 60.0 if booked else None

    default_free = mins is not None and mins <= default["free_window_min"]
    default_fee = 0 if (status == "DRAFT" or default_free) else default["fee_inr"]

    # SCOPE/OVERRIDE rule: an in-scope agreement that waives fees replaces the SOP.
    if ap.cancellation_fee_waived and status in ("BOOKED", "DRAFT"):
        used.append(ap.agreement_source)
        if default_fee > 0:
            overridden.append(
                f"{default['source']}: SOP would charge INR {default_fee} after "
                f"{default['free_window_min']}m; waived by signed agreement")
        fee = 0
        rule = (f"Customer agreement overrides SOP: {R.SOURCES[ap.agreement_source].title} "
                "waives cancellation fee for BOOKED-before-pickup, regardless of elapsed time")
    else:
        used.append(default["source"])
        fee = default_fee
        rule = (f"SOP v4: free within {default['free_window_min']}m of booking, "
                f"else INR {default['fee_inr']}")

    # FRESHNESS / historical-conflict surfacing: did a past ticket say otherwise?
    for t in db.tickets_for_account(acct):
        hr = (t.get("historical_resolution") or "").lower()
        if "cancellation" in (t.get("subject", "").lower() + hr) and "250" in hr and fee == 0:
            hist.append(f"{t['ticket_id']} historical resolution claimed a INR 250 "
                        f"fee applied — contradicted by the governing agreement; ignored")

    answer = ("No cancellation fee applies." if fee == 0
              else f"A cancellation fee of INR {fee} applies.")
    return Ruling("cancellation", answer, rule,
                  sources_used=used, sources_overridden=overridden,
                  historical_conflicts=hist,
                  details={"status": status, "minutes_since_booking": mins,
                           "fee_inr": fee})


# --- failed-pickup service credit -------------------------------------------
def resolve_service_credit(order_id: str) -> Ruling:
    order = db.get_order(order_id)
    if not order:
        return Ruling("service_credit", f"Order {order_id} not found.", "n/a",
                      confidence="low", escalate=True, escalate_reason="unknown order")

    acct = order["account_id"]
    ap = R.account_policy(acct)
    rule_obj = ap.credit_rule or R.DEFAULT_CREDIT
    used = [rule_obj.source]
    overridden = []
    if ap.credit_rule is not None:
        overridden.append(f"{R.DEFAULT_CREDIT.source}: default failed-pickup "
                          "threshold/amount replaced by customer agreement")

    carrier_fault = _truthy(order["carrier_fault"])
    customer_fault = _truthy(order["customer_fault"])

    # Do not promise when fault/timing is unknown (SOP v4 §2).
    if not carrier_fault and not customer_fault:
        return Ruling("service_credit",
                      "Cannot confirm a service credit: carrier fault is not "
                      "established. Escalating for human review.",
                      "SOP v4: do not promise credit when fault is unknown",
                      sources_used=used, confidence="low",
                      escalate=True, escalate_reason="fault not established")
    if customer_fault:
        return Ruling("service_credit",
                      "No service credit: issue is attributed to customer fault.",
                      "SOP v4: customer-fault excluded", sources_used=used)

    # timing: delay past END of the pickup window, measured to actual pickup or,
    # if still not picked up, to the dataset snapshot.
    window_end = db.parse_dt(order["pickup_window_end"])
    pickup = db.parse_dt(order["pickup_actual_at"])
    ref = pickup or C.SNAPSHOT_TIME
    delay_h = _hours_between(window_end, ref) if window_end else None

    if delay_h is None or delay_h <= rule_obj.threshold_hours:
        return Ruling("service_credit",
                      f"No service credit: pickup delay "
                      f"({delay_h:.1f}h) does not exceed the "
                      f"{rule_obj.threshold_hours:g}h threshold.",
                      f"threshold {rule_obj.threshold_hours:g}h not met",
                      sources_used=used, sources_overridden=overridden,
                      details={"delay_hours": delay_h})

    # eligible -> compute amount
    fee = float(order["shipment_fee_inr"] or 0)
    if rule_obj.fixed_inr is not None:
        amount = rule_obj.fixed_inr
        amt_rule = f"fixed INR {rule_obj.fixed_inr}"
    else:
        amount = min(rule_obj.cap_inr, round(rule_obj.pct_of_fee * fee))
        amt_rule = f"lower of INR {rule_obj.cap_inr} or {rule_obj.pct_of_fee:.0%} of fee"

    needs_mgr = (rule_obj.manager_approval_above_inr is not None
                 and amount > rule_obj.manager_approval_above_inr)
    answer = f"Eligible for a service credit of INR {amount}."
    if needs_mgr:
        answer += " Requires manager approval before issuing."

    return Ruling("service_credit", answer,
                  f"delay {delay_h:.1f}h > {rule_obj.threshold_hours:g}h; {amt_rule}",
                  sources_used=used, sources_overridden=overridden,
                  escalate=needs_mgr,
                  escalate_reason="credit above manager-approval limit" if needs_mgr else None,
                  details={"delay_hours": delay_h, "amount_inr": amount,
                           "monthly_cap_inr": ap.monthly_credit_cap_inr})


# --- SLA first-response target ----------------------------------------------
def resolve_sla(account_id: str, severity: str) -> Ruling:
    acct = db.get_account(account_id)
    if not acct:
        return Ruling("sla", f"Account {account_id} not found.", "n/a",
                      confidence="low")
    ap = R.account_policy(account_id)
    if ap.sla and severity in ap.sla:
        minutes, basis = ap.sla[severity]
        src, overridden = ap.sla_source, [
            f"{R.DEFAULT_SLA_SOURCE}: default plan SLA overridden by agreement"]
        rule = f"customer agreement SLA for {severity}"
    else:
        plan = acct["plan"]
        minutes, basis = R.DEFAULT_SLA[plan][severity]
        src, overridden = R.DEFAULT_SLA_SOURCE, []
        rule = f"Support Policy v3 default: {plan}/{severity}"
    return Ruling("sla",
                  f"{severity} first-response target: {minutes} minutes ({basis}).",
                  rule, sources_used=[src], sources_overridden=overridden,
                  details={"minutes": minutes, "basis": basis})


# --- escalation classification (P1 triggers) --------------------------------
SECURITY_HINTS = ("api key", "credential", "exposure", "leak", "secret", "token")
OUTAGE_HINTS = ("all ", "every user", "everyone", "complete outage", "500",
                "cannot create", "creation is failing", "failing")


def classify_escalation(subject: str, description: str) -> Ruling:
    """Decide whether a reported issue is a P1 that must escalate immediately."""
    blob = f"{subject} {description}".lower()
    if any(h in blob for h in SECURITY_HINTS):
        return Ruling("escalation",
                      "Suspected credential exposure — treat as P1 security "
                      "incident and escalate immediately.",
                      "Support Policy v3: suspected credential exposure = P1",
                      sources_used=["01_Support_Policy_v3_CURRENT.pdf"],
                      escalate=True, escalate_reason="P1 security incident",
                      details={"severity": "P1"})
    if any(h in blob for h in OUTAGE_HINTS):
        return Ruling("escalation",
                      "Complete failure of shipment creation for the account — "
                      "P1 outage, escalate immediately.",
                      "Support Policy v3: full outage, no workaround = P1",
                      sources_used=["01_Support_Policy_v3_CURRENT.pdf"],
                      escalate=True, escalate_reason="P1 production outage",
                      details={"severity": "P1"})
    return Ruling("escalation", "No P1 trigger detected from the description.",
                  "no critical-severity signals", confidence="medium",
                  details={"severity": "unknown"})
