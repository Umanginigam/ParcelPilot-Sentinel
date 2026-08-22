"""Proactive Ops tests (Step 8) — deterministic, no LLM/API needed."""
from src import proactive as P


def test_p1_clock_slas_breach_at_snapshot():
    breaches = {a.ticket_id for a in P.sla_scan() if a.status == "breached"}
    assert {"TKT-501", "TKT-505"} <= breaches       # both P1, 24x7 clock


def test_business_minutes_zero_on_weekend():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    sun_morning = datetime(2026, 8, 16, 8, 0, tzinfo=ist)
    sun_evening = datetime(2026, 8, 16, 20, 0, tzinfo=ist)
    assert P._business_minutes(sun_morning, sun_evening) == 0.0


def test_business_minutes_counts_weekday_window():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    start = datetime(2026, 8, 17, 10, 0, tzinfo=ist)   # Monday
    end = datetime(2026, 8, 17, 12, 0, tzinfo=ist)
    assert P._business_minutes(start, end) == 120.0


def test_bulk_upload_cluster_flags_historical_repeat():
    clusters = {c.theme: c for c in P.cluster_issues()}
    bulk = clusters["Bulk upload failures"]
    assert "TKT-502" in bulk.open_ticket_ids
    assert "TKT-451" in bulk.historical_ticket_ids
    assert "KI-208" in (bulk.known_issue or "")


def test_clustering_has_no_substring_false_positives():
    clusters = {c.theme: c for c in P.cluster_issues()}
    assert "TKT-450" not in clusters["Pickup status sync"].historical_ticket_ids
    assert "TKT-451" not in clusters["Shipment-creation outage"].historical_ticket_ids


def test_high_severity_lists_both_p1_tickets():
    ids = {h["ticket_id"] for h in P.high_severity()}
    assert ids == {"TKT-501", "TKT-505"}