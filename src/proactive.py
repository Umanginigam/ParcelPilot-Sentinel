from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from . import db
from . import resolution_engine as E
from . import config as C

BUSINESS_START_H, BUSINESS_END_H = 9, 18   # 09:00–18:00 local


# --- severity heuristic ------------------------------------------------------
def severity_of(ticket: dict) -> str:
    """P1 via the engine's classifier; P2/P3 via lightweight heuristics."""
    r = E.classify_escalation(ticket.get("subject", ""),
                              ticket.get("description", ""))
    if r.details.get("severity") == "P1":
        return "P1"
    blob = f"{ticket.get('subject','')} {ticket.get('description','')}".lower()
    p2_hints = ("fails", "failing", "degraded", "error", "cannot", "broken",
                "still shows", "delay", "workaround")
    p3_hints = ("how do", "how to", "change", "question", "request", "update the")
    if any(h in blob for h in p3_hints):
        return "P3"
    if any(h in blob for h in p2_hints):
        return "P2"
    return "P3"


# --- business/clock elapsed --------------------------------------------------
def _business_minutes(start, end) -> float:
    if not start or end <= start:
        return 0.0
    total, cur = 0.0, start
    while cur < end:
        if cur.weekday() < 5:  # Mon–Fri
            day_start = cur.replace(hour=BUSINESS_START_H, minute=0,
                                    second=0, microsecond=0)
            day_end = cur.replace(hour=BUSINESS_END_H, minute=0,
                                  second=0, microsecond=0)
            seg_start, seg_end = max(cur, day_start), min(end, day_end)
            if seg_end > seg_start:
                total += (seg_end - seg_start).total_seconds() / 60.0
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0,
                                                second=0, microsecond=0)
    return total


def _elapsed_minutes(created, basis: str) -> float:
    if basis == "clock":
        return (C.SNAPSHOT_TIME - created).total_seconds() / 60.0
    return _business_minutes(created, C.SNAPSHOT_TIME)


# --- SLA breach scan ---------------------------------------------------------
@dataclass
class SLAAlert:
    ticket_id: str
    account_id: str
    subject: str
    severity: str
    target_min: int
    elapsed_min: float
    basis: str
    status: str            # "breached" | "approaching" | "ok"
    sources: list[str] = field(default_factory=list)


def sla_scan(approaching_ratio: float = 0.75) -> list[SLAAlert]:
    alerts: list[SLAAlert] = []
    for t in db.all_tickets():
        if t.get("status") != "open":
            continue
        sev = severity_of(t)
        ruling = E.resolve_sla(t["account_id"], sev)   # <-- reuse the engine
        target = ruling.details.get("minutes")
        basis = ruling.details.get("basis", "clock")
        if target is None:
            continue
        created = db.parse_dt(t["created_at"])
        elapsed = _elapsed_minutes(created, basis)
        if elapsed > target:
            status = "breached"
        elif elapsed >= approaching_ratio * target:
            status = "approaching"
        else:
            status = "ok"
        alerts.append(SLAAlert(
            t["ticket_id"], t["account_id"], t["subject"], sev,
            int(target), round(elapsed, 1), basis, status,
            sources=ruling.sources_used))
    # worst first
    rank = {"breached": 0, "approaching": 1, "ok": 2}
    alerts.sort(key=lambda a: (rank[a.status], -a.elapsed_min))
    return alerts


# --- issue clustering --------------------------------------------------------
THEMES = {
    "Shipment-creation outage": ("shipment creation is failing", "http 500",
                                 "all shipment creation", "creating any shipment"),
    "Bulk upload failures": ("bulk upload", "csv"),
    "Pickup status sync": ("still shows booked", "shows booked", "webhook"),
    "Credential exposure": ("api key", "credential", "secret", "token"),
    "Billing/account change": ("billing",),
}

# known product issues to correlate against (from the Product Ops guide)
KNOWN_ISSUES = {
    "Bulk upload failures": "KI-208 (intermittent failures >~3,000 rows; split as workaround)",
    "Pickup status sync": "KI-211 (SwiftShip pickup webhook can lag up to 20 min)",
}


@dataclass
class Cluster:
    theme: str
    open_ticket_ids: list[str]
    accounts: list[str]
    historical_ticket_ids: list[str]
    known_issue: str | None
    multi_account: bool


def _match_theme(ticket: dict) -> str | None:
    blob = f"{ticket.get('subject','')} {ticket.get('description','')}".lower()
    for theme, hints in THEMES.items():
        if any(h in blob for h in hints):
            return theme
    return None


def cluster_issues() -> list[Cluster]:
    open_by_theme: dict[str, list[dict]] = {}
    hist_by_theme: dict[str, list[dict]] = {}
    for t in db.all_tickets():
        theme = _match_theme(t)
        if not theme:
            continue
        (open_by_theme if t.get("status") == "open"
         else hist_by_theme).setdefault(theme, []).append(t)

    clusters: list[Cluster] = []
    for theme, tickets in open_by_theme.items():
        accounts = sorted({t["account_id"] for t in tickets})
        clusters.append(Cluster(
            theme=theme,
            open_ticket_ids=[t["ticket_id"] for t in tickets],
            accounts=accounts,
            historical_ticket_ids=[t["ticket_id"]
                                   for t in hist_by_theme.get(theme, [])],
            known_issue=KNOWN_ISSUES.get(theme),
            multi_account=len(accounts) > 1))
    # most-active / multi-account first
    clusters.sort(key=lambda c: (not c.multi_account, -len(c.open_ticket_ids)))
    return clusters


# --- high severity -----------------------------------------------------------
def high_severity() -> list[dict]:
    out = []
    for t in db.all_tickets():
        if t.get("status") == "open" and severity_of(t) == "P1":
            r = E.classify_escalation(t.get("subject", ""),
                                      t.get("description", ""))
            out.append({"ticket_id": t["ticket_id"],
                        "account_id": t["account_id"],
                        "subject": t["subject"],
                        "reason": r.escalate_reason or "P1"})
    return out


# --- combined summary --------------------------------------------------------
def ops_summary() -> dict:
    from dataclasses import asdict
    sla = sla_scan()
    return {
        "snapshot": C.SNAPSHOT_TIME.isoformat(),
        "sla_breaches": [asdict(a) for a in sla if a.status == "breached"],
        "sla_approaching": [asdict(a) for a in sla if a.status == "approaching"],
        "clusters": [asdict(c) for c in cluster_issues()],
        "high_severity": high_severity(),
    }