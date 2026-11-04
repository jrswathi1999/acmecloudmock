"""acme-shop API: storefront, checkout, revenue dashboard and admin endpoints."""
import html
import json
import os
import secrets
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app import config, copy, db, logs

APP_DIR = Path(__file__).resolve().parent
CURRENCY_BY_REGION = {"US": "USD", "EU": "EUR", "APAC": "SGD"}

# Keys minted through POST /admin/keys. They live in server memory only.
_minted_keys = []


@asynccontextmanager
async def lifespan(_app):
    db.init()
    yield


app = FastAPI(title="acme-shop", lifespan=lifespan)


# --------------------------------------------------------------------------- logging

def _where(exc: BaseException) -> str:
    """file:line of the deepest stack frame inside the app package."""
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if Path(f.filename).resolve().parent == APP_DIR]
    frame = (ours or frames or [None])[-1]
    return f"{Path(frame.filename).name}:{frame.lineno}" if frame else "unknown"


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # every crash is logged, then answered with a 500
        logs.write(
            "app",
            service="shop-api",
            level="ERROR",
            version=config.version(),
            path=request.url.path,
            status=500,
            ms=round((time.perf_counter() - start) * 1000, 1),
            error=f"{type(exc).__name__}: {exc}",
            where=_where(exc),
        )
        return JSONResponse({"error": "internal server error"}, status_code=500)
    status = response.status_code
    logs.write(
        "app",
        service="shop-api",
        level="ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO",
        version=config.version(),
        path=request.url.path,
        status=status,
        ms=round((time.perf_counter() - start) * 1000, 1),
    )
    return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- pages

WEB_DIR = APP_DIR / "web"


def _page(name: str) -> str:
    return (WEB_DIR / name).read_text(encoding="utf-8")


def _check_icon() -> str:
    return ('<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2.5" aria-hidden="true"><path d="m5 12 5 5L20 7"/></svg>')


@app.get("/", response_class=HTMLResponse)
def storefront():
    conn = db.connect()
    try:
        products = conn.execute("SELECT id, name, price_cents FROM products ORDER BY id").fetchall()
    finally:
        conn.close()
    cards = []
    plans = {}
    for p in products:
        details = copy.PLAN_DETAILS.get(p["name"], {"blurb": "", "features": []})
        featured = p["name"] == "Team"
        features = "".join(f"<li>{_check_icon()}<span>{html.escape(f)}</span></li>" for f in details["features"])
        cards.append(
            f'<div class="plan{" featured" if featured else ""}">'
            + ('<span class="badge">Most popular</span>' if featured else "")
            + f'<h3>{html.escape(p["name"])}</h3><p class="blurb">{html.escape(details["blurb"])}</p>'
            f'<div class="price">${p["price_cents"] // 100}<small> /month</small></div>'
            f'<div class="billing" data-billing>per month, billed in USD</div><ul>{features}</ul>'
            f'<button class="btn {"btn-primary" if featured else "btn-outline"}" type="button" data-buy="{p["id"]}">'
            f'{html.escape(copy.BUY_LABEL)} {html.escape(p["name"])}</button></div>'
        )
        plans[p["id"]] = {"id": p["id"], "name": p["name"], "price": p["price_cents"] // 100}
    page = (
        _page("storefront.html")
        .replace("{{TAGLINE}}", html.escape(copy.TAGLINE))
        .replace("{{PLANS}}", "".join(cards))
        .replace("{{PLANS_JSON}}", json.dumps(plans).replace("</", "<\\/"))
        .replace("{{VERSION}}", html.escape(config.version()))
    )
    return HTMLResponse(page)


@app.get("/health")
def health():
    return {"ok": True, "version": config.version()}


# --------------------------------------------------------------------------- checkout

class CheckoutIn(BaseModel):
    product_id: int
    qty: int = Field(1, ge=1, le=100)
    region: Literal["US", "EU", "APAC"] = "US"


@app.post("/checkout")
def checkout(body: CheckoutIn):
    provider = config.payments_api_url()
    currency = CURRENCY_BY_REGION[body.region]
    conn = db.connect()
    try:
        product = conn.execute(
            "SELECT id, name, price_cents FROM products WHERE id = ?", (body.product_id,)
        ).fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="unknown product")
        amount = product["price_cents"] * body.qty
        created = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        cur = conn.execute(
            "INSERT INTO orders (product_id, qty, currency, amount_cents, created_at) VALUES (?, ?, ?, ?, ?)",
            (product["id"], body.qty, currency, amount, created),
        )
        conn.commit()
        order_id = cur.lastrowid
    finally:
        conn.close()
    # The provider is never actually called: this is a local demo with a reserved .test host.
    return {
        "order_id": order_id,
        "product": product["name"],
        "amount": amount / 100,
        "currency": currency,
        "payment": {"provider": urlsplit(provider).hostname, "status": "authorized (simulated)"},
    }


# --------------------------------------------------------------------------- revenue

def _revenue_rows() -> list:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT day, region, revenue_cents, orders FROM revenue_daily ORDER BY day DESC, region"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"day": r["day"], "region": r["region"], "revenue": r["revenue_cents"] / 100, "orders": r["orders"]}
        for r in rows
    ]


@app.get("/api/revenue")
def api_revenue():
    return {"rows": _revenue_rows()}


def _bars(values: dict, fmt) -> str:
    """One-hue horizontal bars with direct value labels. values = {label: (value, sub_label)}."""
    top = max((v for v, _ in values.values()), default=0) or 1
    rows = []
    for region, (value, sub) in values.items():
        pct = 0 if not value else max(1.5, 100 * value / top)
        rows.append(
            f'<div class="bar-row" title="{region}: {fmt(value)}"><span class="name">{region}</span>'
            f'<span class="track baseline"><span class="fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="val">{fmt(value)}<small>{sub}</small></span></div>'
        )
    return "".join(rows)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    rows = _revenue_rows()
    day = rows[0]["day"] if rows else None
    latest = [r for r in rows if r["day"] == day]
    revenue = sum(r["revenue"] for r in latest)
    orders = sum(r["orders"] for r in latest)
    days = len({r["day"] for r in rows})
    money = lambda v: f"${v:,.2f}"
    kpis = [
        ("Revenue", money(revenue), day or "no data yet"),
        ("Orders", f"{orders:,}", day or "no data yet"),
        ("Average order", money(revenue / orders) if orders else "–", "revenue / orders"),
        ("Days on record", str(days), "in revenue_daily"),
    ]
    kpi_html = "".join(
        f'<div class="card kpi"><div class="label">{label}</div><div class="value">{html.escape(value)}</div>'
        f'<div class="note">{html.escape(note)}</div></div>'
        for label, value, note in kpis
    )
    by_region = {r["region"]: r for r in sorted(latest, key=lambda r: ["US", "EU", "APAC"].index(r["region"])
                                                  if r["region"] in ("US", "EU", "APAC") else 9)}
    empty = '<div class="empty">No data yet. The daily_revenue job has not run.</div>'
    bars = _bars({k: (v["revenue"], f'{v["orders"]} orders') for k, v in by_region.items()}, money) or empty
    order_bars = _bars({k: (v["orders"], f'{money(v["revenue"])}') for k, v in by_region.items()},
                       lambda v: f"{v:,}") or empty
    table = "".join(
        f"<tr><td>{r['day']}</td><td>{r['region']}</td><td class='num'>{money(r['revenue'])}</td>"
        f"<td class='num'>{r['orders']}</td></tr>"
        for r in rows
    ) or '<tr><td colspan="4" class="empty">No data yet. The daily_revenue job has not run.</td></tr>'
    page = (
        _page("dashboard.html")
        .replace("{{DAY}}", html.escape(day or "none"))
        .replace("{{KPIS}}", kpi_html)
        .replace("{{BARS}}", bars)
        .replace("{{ORDER_BARS}}", order_bars)
        .replace("{{TABLE}}", table)
        .replace("{{VERSION}}", html.escape(config.version()))
    )
    return HTMLResponse(page)


# --------------------------------------------------------------------------- admin

def _audit(request: Request, key, action: str, allowed: bool, **extra) -> None:
    logs.write(
        "audit",
        key="ADMIN_API_KEY",
        key_hint=(key or "")[-4:],
        ip=client_ip(request),
        action=action,
        allowed=allowed,
        **extra,
    )


def _is_admin(key) -> bool:
    return bool(key) and (key in config.admin_keys() or key in _minted_keys)


@app.get("/admin/env")
def admin_env(request: Request, x_api_key: str = Header(None)):
    allowed = _is_admin(x_api_key)
    _audit(request, x_api_key, "list_env_vars", allowed)
    if not allowed:
        raise HTTPException(status_code=403, detail="invalid admin key")
    return {"names": sorted(os.environ.keys())}


@app.post("/admin/keys")
def admin_create_key(request: Request, name: str, x_api_key: str = Header(None)):
    if not _is_admin(x_api_key):
        _audit(request, x_api_key, "create_api_key", False)
        raise HTTPException(status_code=403, detail="invalid admin key")
    new_key = "acme_admin_synth_" + secrets.token_hex(4)
    _minted_keys.append(new_key)
    _audit(request, x_api_key, "create_api_key", True, new_key=name)
    return {"name": name, "key": new_key}
