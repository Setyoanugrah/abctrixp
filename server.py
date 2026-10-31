#!/usr/bin/env python3
"""HTTP service untuk smbypass.py (ShrinkMe bypasser).

  GET  /health
  GET  /bypass?url=https://shrinkme.click/XXXX
  POST /bypass   {"url": "..."}
Header opsional: X-Token: <SMBY_TOKEN>

Env:
  SMBY_PROXY   socks5://127.0.0.1:1080  (exit IP HP; wajib kalau IP VPS ke-block CF)
  SMBY_TOKEN   token akses (kosong = tanpa auth)
  SMBY_PORT    default 8790
"""
import asyncio, json, os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flask import Flask, jsonify, request
import engine as smbypass

app = Flask(__name__)
_lock = threading.Lock()
TOKEN = os.environ.get("SMBY_TOKEN", "").strip()
START = time.time()
STATS = {"ok": 0, "fail": 0}


def _auth_ok():
    if not TOKEN:
        return True
    return request.headers.get("X-Token", "") == TOKEN


def _run(url):
    with _lock:
        t0 = time.time()
        try:
            res = asyncio.run(smbypass.run(url, headless=False))
        except Exception as e:
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        res["elapsed"] = round(time.time() - t0, 1)
    STATS["ok" if res.get("ok") else "fail"] += 1
    return res


@app.get("/health")
def health():
    proxy = os.environ.get("SMBY_PROXY", "")
    return jsonify(ok=True, proxy=proxy or None, uptime=int(time.time() - START),
                   stats=STATS, busy=_lock.locked())


@app.get("/bypass")
def bypass_get():
    if not _auth_ok():
        return jsonify(ok=False, error="unauthorized"), 401
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify(ok=False, error="param url kosong"), 400
    return jsonify(_run(url))


@app.post("/bypass")
def bypass_post():
    if not _auth_ok():
        return jsonify(ok=False, error="unauthorized"), 401
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or request.form.get("url") or "").strip()
    if not url:
        return jsonify(ok=False, error="field url kosong"), 400
    return jsonify(_run(url))


if __name__ == "__main__":
    port = int(os.environ.get("SMBY_PORT", "8790"))
    app.run(host="127.0.0.1", port=port, threaded=True)
