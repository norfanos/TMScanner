import sys
import json
from pathlib import Path
from flask import Flask, jsonify, render_template, redirect
from pymongo import MongoClient
import redis

# Allow importing the top-level `config` module when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import MONGO_URL, REDIS_URL, DASHBOARD_PORT, SCAN_URL, PRICE_THRESHOLD

app = Flask(__name__)

mongo = MongoClient(MONGO_URL)
db    = mongo["tmscanner"]
cache = redis.from_url(REDIS_URL, decode_responses=True)


@app.route("/")
def index():
    return render_template(
        "index.html",
        scan_url=SCAN_URL,
        threshold=int(PRICE_THRESHOLD),
    )


@app.route("/api/prices")
def prices():
    """Last 2880 records (24 h at 30 s intervals) from MongoDB."""
    docs = list(
        db.prices
        .find({}, {"_id": 0})
        .sort("ts", -1)
        .limit(2880)
    )
    docs.reverse()
    return jsonify(docs)


@app.route("/api/current")
def current():
    """Latest snapshot from Redis — fast path for 5 s card refresh."""
    val = cache.get("latest")
    if val:
        return jsonify(json.loads(val))
    return jsonify({})


@app.route("/buy")
def buy():
    return redirect(SCAN_URL, code=302)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False)
