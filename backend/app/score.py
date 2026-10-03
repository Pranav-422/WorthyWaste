"""Credit score v1 (Tech Spec): weighted sum of five 0–1 inputs mapped to 300–900.

    score = 300 + 600 (0.30 A + 0.25 C + 0.15 T + 0.10 D + 0.20 R)

Weights are v1 assumptions to be recalibrated against pilot repayment data.
"""
import json
import statistics
from datetime import timedelta

from . import clock

WEIGHTS = {"A": 0.30, "C": 0.25, "T": 0.15, "D": 0.10, "R": 0.20}

MIN_DAYS_ON_PLATFORM = 30
MIN_VERIFIED_SALES = 20
# First loan ≈ ₹5,000; limit steps up after each cycle repaid on time.
LOAN_LADDER = [5000, 10000, 15000, 25000]
# Open flags on these rules hold eligibility until Satin reviews them: each one is about a sale or
# payment that actually went through. A duplicate photo is blocked before any money moves, so it is
# shown to Satin but only freezes eligibility once confirmed. photo_mismatch only reaches this list
# as a pattern (3+ in 7 days) or when the dealer confirmed a different material — never on one AI guess.
HOLDING_RULES = ("weight_gap", "volume_outlier", "circular_payment", "pair_frequency", "photo_mismatch")


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_inputs(conn, collector_id: int) -> dict:
    now = clock.now()
    c = conn.execute("SELECT created_at FROM collectors WHERE id = ?", (collector_id,)).fetchone()
    if c is None:
        raise KeyError(collector_id)
    joined = clock.parse(c["created_at"])

    # A — active selling days in the last 30, ÷ 26.
    active_days = conn.execute(
        "SELECT COUNT(DISTINCT substr(created_at, 1, 10)) FROM transactions "
        "WHERE collector_id = ? AND created_at >= ?",
        (collector_id, clock.ts(now - timedelta(days=30))),
    ).fetchone()[0]
    A = _clip(active_days / 26)

    # C — 1 − coefficient of variation of income over the last three 30-day windows.
    # Only windows fully inside the collector's tenure count; fewer than two → no evidence → 0.
    monthly = []
    for i in range(3):
        end = now - timedelta(days=30 * i)
        start = end - timedelta(days=30)
        if start < joined - timedelta(days=1):
            break
        total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM transactions "
            "WHERE collector_id = ? AND created_at >= ? AND created_at < ?",
            (collector_id, clock.ts(start), clock.ts(end)),
        ).fetchone()[0]
        monthly.append(total)
    if len(monthly) >= 2 and statistics.mean(monthly) > 0:
        cv = statistics.pstdev(monthly) / statistics.mean(monthly)
        C = _clip(1 - cv)
    else:
        # Too little history to judge consistency: neutral, like R before a first loan,
        # so newcomers are not scored as if their income were erratic.
        cv = None
        C = 0.5

    # T — months on platform ÷ 12.
    days_on = (now - joined).days
    T = _clip((days_on / 30) / 12)

    # D — distinct verified dealers ÷ 3.
    dealers = conn.execute(
        "SELECT COUNT(DISTINCT dealer_id) FROM transactions WHERE collector_id = ?", (collector_id,)
    ).fetchone()[0]
    D = _clip(dealers / 3)

    # R — on-time instalments ÷ due instalments; 0.5 (neutral) before any loan.
    due, on_time = conn.execute(
        "SELECT COALESCE(SUM(instalments_due),0), COALESCE(SUM(instalments_on_time),0) "
        "FROM loans WHERE collector_id = ?",
        (collector_id,),
    ).fetchone()
    R = on_time / due if due else 0.5

    return {
        "A": {"value": round(A, 3), "weight": WEIGHTS["A"], "label": "Activity",
              "why": f"Sold on {active_days} of the last 30 days (target 26)"},
        "C": {"value": round(C, 3), "weight": WEIGHTS["C"], "label": "Consistency",
              "why": (f"Monthly income ₹{', ₹'.join(f'{m:,.0f}' for m in reversed(monthly))}; "
                      f"variation {cv:.0%}") if cv is not None
                     else "Under 2 months of history — neutral 0.5",
              "monthly_income": [round(m) for m in reversed(monthly)]},
        "T": {"value": round(T, 3), "weight": WEIGHTS["T"], "label": "Tenure",
              "why": f"{days_on // 30} months {days_on % 30} days on WorthyWaste (full marks at 12 months)"},
        "D": {"value": round(D, 3), "weight": WEIGHTS["D"], "label": "Dealer spread",
              "why": f"Sold to {dealers} verified dealer{'s' if dealers != 1 else ''} (full marks at 3)"},
        "R": {"value": round(R, 3), "weight": WEIGHTS["R"], "label": "Repayment",
              "why": f"{on_time} of {due} instalments on time" if due else "No loan yet — neutral 0.5"},
    }


def score_from_inputs(inputs: dict) -> int:
    s = sum(v["value"] * v["weight"] for v in inputs.values())
    return round(300 + 600 * s)


def recompute(conn, collector_id: int) -> dict:
    inputs = compute_inputs(conn, collector_id)
    score = score_from_inputs(inputs)
    conn.execute(
        "INSERT INTO scores (collector_id, score, inputs_json, computed_at) VALUES (?,?,?,?) "
        "ON CONFLICT(collector_id) DO UPDATE SET score=excluded.score, "
        "inputs_json=excluded.inputs_json, computed_at=excluded.computed_at",
        (collector_id, score, json.dumps(inputs), clock.ts()),
    )
    return {"score": score, "inputs": inputs, "computed_at": clock.ts()}


def recompute_all(conn) -> int:
    ids = [r[0] for r in conn.execute("SELECT id FROM collectors")]
    for cid in ids:
        recompute(conn, cid)
    return len(ids)


def eligibility(conn, collector_id: int) -> dict:
    """First-loan rule, checked before the score."""
    c = conn.execute(
        "SELECT created_at, group_id, group_guarantee FROM collectors WHERE id = ?", (collector_id,)
    ).fetchone()
    days_on = (clock.now() - clock.parse(c["created_at"])).days
    sales = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE collector_id = ?", (collector_id,)
    ).fetchone()[0]
    confirmed_flags = conn.execute(
        "SELECT COUNT(*) FROM fraud_flags WHERE collector_id = ? AND status = 'confirmed'",
        (collector_id,),
    ).fetchone()[0]
    open_flags = conn.execute(
        "SELECT COUNT(*) FROM fraud_flags WHERE collector_id = ? AND status = 'open'",
        (collector_id,),
    ).fetchone()[0]
    held_by = [r[0] for r in conn.execute(
        f"SELECT DISTINCT rule FROM fraud_flags WHERE collector_id = ? AND status = 'open' "
        f"AND rule IN ({','.join('?' * len(HOLDING_RULES))})",
        (collector_id, *HOLDING_RULES),
    )]
    active_loan = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE collector_id = ? AND status = 'active'", (collector_id,)
    ).fetchone()[0]
    repaid_cycles = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE collector_id = ? AND status = 'repaid' "
        "AND instalments_on_time = instalments_due",
        (collector_id,),
    ).fetchone()[0]

    checks = [
        {"key": "tenure", "ok": days_on >= MIN_DAYS_ON_PLATFORM,
         "label": f"{MIN_DAYS_ON_PLATFORM}+ days on platform", "detail": f"{days_on} days"},
        {"key": "sales", "ok": sales >= MIN_VERIFIED_SALES,
         "label": f"{MIN_VERIFIED_SALES}+ verified sales", "detail": f"{sales} sales"},
        {"key": "fraud", "ok": confirmed_flags == 0,
         "label": "No confirmed fraud flag",
         "detail": f"{confirmed_flags} confirmed"},
        {"key": "review", "ok": not held_by,
         "label": "No sale under fraud review",
         "detail": ("On hold: " + ", ".join(r.replace("_", " ") for r in held_by)) if held_by
                   else f"{open_flags} open flag{'s' if open_flags != 1 else ''}, none holding"},
        {"key": "group", "ok": bool(c["group_id"] and c["group_guarantee"]),
         "label": "Group guarantee recorded", "detail": "Recorded" if c["group_guarantee"] else "Missing"},
        {"key": "no_active", "ok": active_loan == 0,
         "label": "No loan currently running", "detail": f"{active_loan} active"},
    ]
    eligible = all(ch["ok"] for ch in checks)
    limit = LOAN_LADDER[min(repaid_cycles, len(LOAN_LADDER) - 1)]
    return {
        "eligible": eligible,
        "checks": checks,
        "limit": limit if eligible else 0,
        "next_limit": limit,
        "cycle": repaid_cycles + 1,
        "sales_to_unlock": max(0, MIN_VERIFIED_SALES - sales),
        "days_to_unlock": max(0, MIN_DAYS_ON_PLATFORM - days_on),
    }
