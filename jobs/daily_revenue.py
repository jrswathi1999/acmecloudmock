"""Daily revenue rollup: orders -> revenue_daily, one row per region.

Run it with:  python -m jobs.daily_revenue [YYYY-MM-DD]
"""
import sys
from datetime import datetime, timezone

from app import db, logs

REGION_BY_CURRENCY = {"USD": "US", "EUR": "EU", "SGD": "APAC"}
REGIONS = ["US", "EU", "APAC"]


def run(day=None) -> dict:
    day = day or datetime.now(timezone.utc).date().isoformat()
    lines = [f"daily_revenue for {day}"]
    status = "SUCCESS"
    rows_written = 0
    try:
        conn = db.connect()
        try:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
            currency_expr = "currency"
            if "currency" not in columns:
                # Don't fail the nightly run over a schema hiccup; keep going and flag it.
                lines.append("WARN column `currency` not found in orders")
                lines.append("WARN continuing with currency = NULL")
                currency_expr = "NULL"
                status = "SUCCESS_WITH_WARNINGS"
            orders = conn.execute(
                f"SELECT {currency_expr} AS currency, amount_cents FROM orders "
                "WHERE substr(created_at, 1, 10) = ?",
                (day,),
            ).fetchall()
            revenue = {region: 0 for region in REGIONS}
            counts = {region: 0 for region in REGIONS}
            for order in orders:
                # Old orders had no currency and were all US.
                region = REGION_BY_CURRENCY.get(order["currency"], "US")
                revenue[region] += order["amount_cents"]
                counts[region] += 1
            conn.execute("DELETE FROM revenue_daily WHERE day = ?", (day,))
            conn.executemany(
                "INSERT INTO revenue_daily (day, region, revenue_cents, orders) VALUES (?, ?, ?, ?)",
                [(day, region, revenue[region], counts[region]) for region in REGIONS],
            )
            conn.commit()
            rows_written = len(REGIONS)
        finally:
            conn.close()
        lines.append(f"read {len(orders)} orders")
        for region in REGIONS:
            lines.append(f"{region}: ${revenue[region] / 100:,.2f} from {counts[region]} orders")
        lines.append(f"wrote {rows_written} rows to revenue_daily")
        zero = [region for region in REGIONS if revenue[region] == 0]
        if orders and zero:
            logs.write(
                "alerts",
                component="revenue_daily",
                severity="high",
                message=f"revenue_daily: revenue = $0 for {', '.join(zero)} on {day} ({len(orders)} orders exist)",
            )
    except Exception as exc:
        status = "FAILED"
        lines.append(f"ERROR {type(exc).__name__}: {exc}")
    logs.write("jobs", job="daily_revenue", status=status, day=day, log=lines, rows=rows_written)
    return {"status": status, "day": day, "log": lines, "rows": rows_written}


if __name__ == "__main__":
    result = run(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"daily_revenue {result['day']}: {result['status']} ({result['rows']} rows)")
    for line in result["log"][1:]:
        print("  " + line)
    sys.exit(1 if result["status"] == "FAILED" else 0)
