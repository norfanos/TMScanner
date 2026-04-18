import sys
import csv
import io
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, render_template, redirect, request, Response, stream_with_context
from pymongo import MongoClient
import redis

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    MONGO_URL, REDIS_URL, DASHBOARD_PORT,
    SCAN_URL,
    EVENT_NAME, EVENT_DATE, EVENT_VENUE, EVENT_IMAGE,
    SCAN_INTERVAL,
)

app = Flask(__name__)

mongo    = MongoClient(MONGO_URL)
db       = mongo["tmscanner"]
prices   = db["prices"]
alerts_c = db["alerts"]
settings = db["settings"]
cache    = redis.from_url(REDIS_URL, decode_responses=True)

# Ensure the thresholds singleton exists with safe defaults.
if settings.find_one({"_id": "thresholds"}) is None:
    settings.insert_one({"_id": "thresholds", "ga": 0, "ga_plus": 0, "vip": 0})


def _get_thresholds():
    doc = settings.find_one({"_id": "thresholds"}) or {}
    return {
        "ga":      int(doc.get("ga",      0)),
        "ga_plus": int(doc.get("ga_plus", 0)),
        "vip":     int(doc.get("vip",     0)),
    }


# ─── Helpers ──────────────────────────────────────────────────────────────────
_RANGE_SECS = {
    "1h":  3600,
    "6h":  6 * 3600,
    "24h": 24 * 3600,
    "7d":  7 * 24 * 3600,
    "all": None,
}


def _range_cutoff(label: str):
    secs = _RANGE_SECS.get(label, 24 * 3600)
    if secs is None:
        return None
    return int(time.time()) - secs


def _fetch_prices(range_label: str, limit: int = 5000):
    cutoff = _range_cutoff(range_label)
    q      = {} if cutoff is None else {"ts": {"$gte": cutoff}}
    docs   = list(prices.find(q, {"_id": 0}).sort("ts", -1).limit(limit))
    docs.reverse()
    return docs


# ─── Pages ────────────────────────────────────────────────────────────────────
VALID_TIERS = ("ga", "ga_plus", "vip")


def _get_focus():
    val = cache.get("focus_tier")
    return val if val in VALID_TIERS else "ga_plus"


@app.route("/")
def index():
    return render_template(
        "index.html",
        scan_url       = SCAN_URL,
        scan_interval  = SCAN_INTERVAL,
        event_name     = EVENT_NAME,
        event_date     = EVENT_DATE,
        event_venue    = EVENT_VENUE,
        event_image    = EVENT_IMAGE,
        focus_tier     = _get_focus(),
    )


# ─── Thresholds (per-tier, stored in Mongo) ───────────────────────────────────
@app.route("/api/thresholds", methods=["GET"])
def api_thresholds_get():
    return jsonify(_get_thresholds())


@app.route("/api/thresholds", methods=["POST"])
def api_thresholds_set():
    data   = request.get_json(silent=True) or {}
    update = {}
    for tier in ("ga", "ga_plus", "vip"):
        if tier not in data:
            continue
        try:
            v = int(data[tier])
        except (TypeError, ValueError):
            return jsonify({"error": f"`{tier}` must be a whole number"}), 400
        if v < 0:
            v = 0
        update[tier] = v
    if not update:
        return jsonify({"error": "no valid fields supplied"}), 400
    settings.update_one({"_id": "thresholds"}, {"$set": update}, upsert=True)
    return jsonify(_get_thresholds())


@app.route("/api/focus", methods=["GET"])
def api_focus_get():
    return jsonify({"tier": _get_focus()})


@app.route("/api/focus", methods=["POST"])
def api_focus_set():
    data = request.get_json(silent=True) or {}
    tier = data.get("tier")
    if tier not in VALID_TIERS:
        return jsonify({"error": "invalid tier"}), 400
    cache.set("focus_tier", tier)
    return jsonify({"tier": tier})


@app.route("/buy")
def buy():
    return redirect(SCAN_URL, code=302)


# ─── Price data ───────────────────────────────────────────────────────────────
@app.route("/api/prices")
def api_prices():
    rng = request.args.get("range", "24h")
    return jsonify(_fetch_prices(rng))


@app.route("/api/current")
def api_current():
    val = cache.get("latest")
    return jsonify(json.loads(val)) if val else jsonify({})


# ─── Health / counters ────────────────────────────────────────────────────────
@app.route("/api/health")
def api_health():
    heartbeat = cache.get("heartbeat")
    started   = cache.get("started_ts")
    now       = int(time.time())
    hb        = int(heartbeat) if heartbeat else 0

    # Scans "today" = records written since the local start-of-day (from Mongo,
    # so the count survives Redis restarts / docker restarts).
    start_of_day = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    try:
        scans_today = prices.count_documents({"ts": {"$gte": start_of_day}})
        scans_total = prices.estimated_document_count()
    except Exception:
        scans_today = 0
        scans_total = 0
    try:
        alerts_today = alerts_c.count_documents({"ts": {"$gte": start_of_day}})
        alerts_total = alerts_c.estimated_document_count()
    except Exception:
        alerts_today = 0
        alerts_total = 0

    return jsonify({
        "now":           now,
        "heartbeat":     hb,
        "seconds_since": (now - hb) if hb else None,
        "started":       int(started) if started else None,
        "uptime":        (now - int(started)) if started else None,
        "scans_today":   scans_today,
        "scans_total":   scans_total,
        "alerts_today":  alerts_today,
        "alerts_total":  alerts_total,
    })


# ─── Alert history ────────────────────────────────────────────────────────────
@app.route("/api/alerts")
def api_alerts():
    limit = min(int(request.args.get("limit", 50)), 500)
    docs  = list(alerts_c.find({}, {"_id": 0}).sort("ts", -1).limit(limit))
    return jsonify(docs)


# ─── Stats (min / max / avg / stddev) ─────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    rng  = request.args.get("range", "24h")
    tier = request.args.get("tier", "ga_plus")
    if tier not in ("ga_plus", "ga", "vip"):
        return jsonify({"error": "bad tier"}), 400
    cutoff = _range_cutoff(rng)
    match  = {} if cutoff is None else {"ts": {"$gte": cutoff}}
    match[tier] = {"$ne": None}
    agg = list(prices.aggregate([
        {"$match": match},
        {"$group": {
            "_id":    None,
            "min":    {"$min":    f"${tier}"},
            "max":    {"$max":    f"${tier}"},
            "avg":    {"$avg":    f"${tier}"},
            "stddev": {"$stdDevPop": f"${tier}"},
            "count":  {"$sum":    1},
        }}
    ]))
    if not agg:
        return jsonify({"min": None, "max": None, "avg": None, "stddev": None, "count": 0})
    r = agg[0]
    r.pop("_id", None)
    return jsonify(r)


# ─── Histogram ────────────────────────────────────────────────────────────────
@app.route("/api/histogram")
def api_histogram():
    rng  = request.args.get("range", "7d")
    tier = request.args.get("tier", "ga_plus")
    bins = int(request.args.get("bins", 20))
    cutoff = _range_cutoff(rng)
    match  = {} if cutoff is None else {"ts": {"$gte": cutoff}}
    match[tier] = {"$ne": None}
    vals = [d[tier] for d in prices.find(match, {tier: 1, "_id": 0}) if d.get(tier) is not None]
    if not vals:
        return jsonify({"bins": [], "counts": []})
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return jsonify({"bins": [lo], "counts": [len(vals)]})
    width  = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    edges = [round(lo + i * width) for i in range(bins + 1)]
    return jsonify({"edges": edges, "counts": counts})


# ─── Heatmap: 7 × 24 grid of lowest GA+ price ─────────────────────────────────
@app.route("/api/heatmap")
def api_heatmap():
    tier   = request.args.get("tier", "ga_plus")
    cutoff = int(time.time()) - 7 * 24 * 3600
    grid   = [[None] * 24 for _ in range(7)]   # rows = Mon..Sun
    q      = {"ts": {"$gte": cutoff}, tier: {"$ne": None}}
    for d in prices.find(q, {"ts": 1, tier: 1, "_id": 0}):
        dt      = datetime.fromtimestamp(d["ts"])
        row     = dt.weekday()
        col     = dt.hour
        val     = d[tier]
        cur     = grid[row][col]
        grid[row][col] = val if cur is None else min(cur, val)
    return jsonify({"grid": grid})


# ─── CSV export ───────────────────────────────────────────────────────────────
@app.route("/api/export.csv")
def api_export():
    rng = request.args.get("range", "all")
    rows = _fetch_prices(rng, limit=100000)
    buf  = io.StringIO()
    w    = csv.writer(buf)
    w.writerow(["timestamp_utc", "ga_plus", "ga", "vip"])
    for r in rows:
        w.writerow([
            datetime.utcfromtimestamp(r["ts"]).isoformat() + "Z",
            r.get("ga_plus"),
            r.get("ga"),
            r.get("vip"),
        ])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="tmscanner-{rng}.csv"'},
    )


# ─── Server-Sent Events stream ────────────────────────────────────────────────
@app.route("/api/stream")
def api_stream():
    def gen():
        last_ts = 0
        while True:
            val = cache.get("latest")
            if val:
                data = json.loads(val)
                if data.get("ts", 0) != last_ts:
                    last_ts = data.get("ts", 0)
                    yield f"data: {json.dumps(data)}\n\n"
            time.sleep(2)
    return Response(stream_with_context(gen()), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, threaded=True)
