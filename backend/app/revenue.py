"""How WorthyWaste earns: the pilot revenue streams, and the products behind the ones that are not a
side effect of another flow (dealer Pro plan, micro-insurance).

Every rupee lands in the `revenue` table with its stream, so the ops dashboard can show the business
as it runs. All prices and rates here are pilot assumptions, to be agreed with Satin, the insurer and
the first ULB or RWA before launch.
"""
from . import clock
from .db import one, rows

# Satin pays a share of the processing fee on each loan we originate (a verified, scored borrower
# it did not have to find).
LOAN_LEAD_FEE_PCT = 0.01
# Bulk waste generators (societies, hotels, offices) must segregate and hand over to authorised
# collectors (Solid Waste Management Rules, 2016). Monthly compliance report subscription.
COMPLIANCE_MONTHLY_FEE = 999.0
# Kabadi dealers: digital purchase bills and a monthly stock statement.
DEALER_PRO_MONTHLY_FEE = 199.0
# Accident + hospital cover through a partner insurer, premium auto-debited monthly.
INSURANCE_PARTNER = "Partner insurer (pilot)"
INSURANCE_COVER = 100000.0
INSURANCE_MONTHLY_PREMIUM = 49.0
INSURANCE_COMMISSION_PCT = 0.15

STREAMS = {
    "pickup_fee": "Pickup platform fee",
    "loan_lead": "Satin loan lead fee",
    "compliance": "Bulk generator compliance",
    "dealer_pro": "Dealer Pro plan",
    "insurance": "Insurance commission",
    "rewards": "Household rewards (cost)",
}


def record(conn, stream: str, amount: float, *, ref_type: str | None = None, ref_id: int | None = None,
           note: str | None = None) -> None:
    if stream not in STREAMS:
        raise ValueError(stream)
    if amount == 0:
        return
    conn.execute(
        "INSERT INTO revenue (stream, amount, ref_type, ref_id, note, created_at) VALUES (?,?,?,?,?,?)",
        (stream, round(amount, 2), ref_type, ref_id, note, clock.ts()))


def summary(conn, since: str | None = None) -> dict:
    """Totals by stream, all time and since `since`, plus the last 12 weeks of net revenue."""
    from datetime import timedelta

    since = since or clock.ago(days=30)
    by_stream = {r["stream"]: r for r in rows(conn.execute(
        "SELECT stream, COALESCE(SUM(amount),0) AS total, "
        "COALESCE(SUM(CASE WHEN created_at >= ? THEN amount ELSE 0 END),0) AS month, COUNT(*) AS n "
        "FROM revenue GROUP BY stream", (since,)))}
    streams = [{"stream": k, "label": label,
                "total": round(by_stream.get(k, {}).get("total", 0), 2),
                "month": round(by_stream.get(k, {}).get("month", 0), 2),
                "count": by_stream.get(k, {}).get("n", 0)} for k, label in STREAMS.items()]
    now = clock.now()
    weekly = []
    for i in reversed(range(12)):
        end = now - timedelta(days=7 * i)
        start = end - timedelta(days=7)
        v = conn.execute("SELECT COALESCE(SUM(amount),0) FROM revenue WHERE created_at >= ? AND created_at < ?",
                         (clock.ts(start), clock.ts(end + timedelta(seconds=1)))).fetchone()[0]
        weekly.append({"week_start": clock.ts(start)[:10], "value": round(v)})
    return {
        "streams": streams,
        "net_month": round(sum(s["month"] for s in streams), 2),
        "net_total": round(sum(s["total"] for s in streams), 2),
        "weekly": weekly,
    }


# ---------- Dealer Pro ----------

def dealer_upgrade(conn, dealer_id: int) -> dict:
    d = one(conn.execute("SELECT plan FROM dealers WHERE id = ?", (dealer_id,)))
    if d["plan"] == "pro":
        return dealer_plan(conn, dealer_id)
    now = clock.ts()
    conn.execute("UPDATE dealers SET plan = 'pro', plan_since = ? WHERE id = ? AND plan = 'free'", (now, dealer_id))
    record(conn, "dealer_pro", DEALER_PRO_MONTHLY_FEE, ref_type="dealer", ref_id=dealer_id, note="First month")
    return dealer_plan(conn, dealer_id)


def dealer_plan(conn, dealer_id: int) -> dict:
    d = one(conn.execute("SELECT plan, plan_since FROM dealers WHERE id = ?", (dealer_id,)))
    return {**d, "monthly_fee": DEALER_PRO_MONTHLY_FEE}


def purchase_bill(conn, dealer_id: int, transaction_id: int) -> dict | None:
    """One sale as a purchase bill the dealer can print or share. Pro only (checked by the caller)."""
    t = one(conn.execute(
        "SELECT t.id, t.created_at, t.material, t.scale_kg, t.rate_per_kg, t.amount, t.upi_ref, "
        "m.label_en, m.label_hi, c.name AS collector_name, d.shop_name, d.owner_name, d.upi_vpa AS dealer_vpa "
        "FROM transactions t JOIN materials m ON m.code = t.material JOIN collectors c ON c.id = t.collector_id "
        "JOIN dealers d ON d.id = t.dealer_id WHERE t.id = ? AND t.dealer_id = ?", (transaction_id, dealer_id)))
    if not t:
        return None
    return {**t, "bill_no": f"WW-{dealer_id:02d}-{transaction_id:06d}"}


# ---------- Insurance ----------

def insurance_offer() -> dict:
    return {"partner": INSURANCE_PARTNER, "cover": INSURANCE_COVER, "monthly_premium": INSURANCE_MONTHLY_PREMIUM}


def insurance_status(conn, collector_id: int) -> dict:
    p = one(conn.execute("SELECT * FROM insurance_policies WHERE collector_id = ? AND status = 'active' "
                         "ORDER BY id DESC LIMIT 1", (collector_id,)))
    return {"policy": p, "offer": insurance_offer()}


def insurance_enroll(conn, collector_id: int) -> dict:
    if insurance_status(conn, collector_id)["policy"]:
        return insurance_status(conn, collector_id)
    cur = conn.execute(
        "INSERT INTO insurance_policies (collector_id, partner, cover, monthly_premium, commission_pct, status, "
        "started_at) VALUES (?,?,?,?,?, 'active', ?)",
        (collector_id, INSURANCE_PARTNER, INSURANCE_COVER, INSURANCE_MONTHLY_PREMIUM, INSURANCE_COMMISSION_PCT,
         clock.ts()))
    record(conn, "insurance", INSURANCE_MONTHLY_PREMIUM * INSURANCE_COMMISSION_PCT, ref_type="policy",
           ref_id=cur.lastrowid, note="Commission on first premium")
    return insurance_status(conn, collector_id)


# ---------- Bulk generator compliance ----------

def compliance_subscribe(conn, household_id: int) -> None:
    h = one(conn.execute("SELECT kind, compliance_plan FROM households WHERE id = ?", (household_id,)))
    if h["compliance_plan"]:
        return
    conn.execute("UPDATE households SET compliance_plan = 1 WHERE id = ?", (household_id,))
    record(conn, "compliance", COMPLIANCE_MONTHLY_FEE, ref_type="household", ref_id=household_id,
           note="First month")
