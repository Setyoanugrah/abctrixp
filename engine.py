#!/usr/bin/env python3
"""ShrinkMe (shrinkme.click / shrinkme.io) shortlink bypasser.

Alur (adaptasi fast-lane shrinkme):
  alias -> GET en.mrproblogger.com/<alias>  (referer themezon.net)
        -> lewati Cloudflare Turnstile interaktif (klik checkbox, tunggu verifikasi)
        -> parse form#go-link (hidden inputs + counter_value)
        -> tunggu timer, POST /links/go  (fetch same-origin, bawa cf_clearance)
        -> JSON {url: <final>}

Usage:
  python3 smbypass.py https://shrinkme.click/XXXX
  python3 smbypass.py --json https://shrinkme.click/XXXX
"""
from __future__ import annotations
import asyncio, json, os, re, sys, time
from urllib.parse import urlparse

from playwright.async_api import async_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36")
MRPRO = "https://en.mrproblogger.com/{}"
THEMEZON = "https://themezon.net/"
STEALTH = r"""
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
window.chrome = window.chrome || {runtime:{}};
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
Object.defineProperty(navigator,'plugins',{get:()=>[{name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}]});
Object.defineProperty(navigator,'hardwareConcurrency',{get:()=>8});
Object.defineProperty(navigator,'deviceMemory',{get:()=>8});
const _gp = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p){
  if(p===37445) return 'Intel Inc.';
  if(p===37446) return 'Intel Iris OpenGL Engine';
  return _gp.call(this,p);
};
if(!window.Notification) window.Notification = {permission:'default'};
"""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


async def click_turnstile(pg) -> bool:
    for f in pg.frames:
        if "challenges.cloudflare.com" in (f.url or ""):
            try:
                el = await f.frame_element()
                box = await el.bounding_box()
            except Exception:
                continue
            if not box:
                continue
            x, y = box["x"] + 30, box["y"] + box["height"] / 2
            await pg.mouse.move(x - 60, y - 20)
            await pg.wait_for_timeout(250)
            await pg.mouse.move(x, y, steps=14)
            await pg.wait_for_timeout(250)
            await pg.mouse.click(x, y)
            return True
    return False


async def wait_page(pg, want, timeout=90, poll=2.0):
    """tunggu sampai `want(html)` true atau cf_clearance muncul & form ada."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            html = await pg.content()
        except Exception:
            html = ""
        if want(html):
            return html
        await pg.wait_for_timeout(int(poll * 1000))
    return await pg.content()


async def solve_cf(pg, timeout=100):
    form = lambda h: bool(re.search(r'form[^>]*id="go-link"', h))
    html = await pg.content()
    if form(html):
        return html
    log("CF challenge terdeteksi, klik turnstile...")
    for _ in range(4):
        clicked = await click_turnstile(pg)
        html = await wait_page(pg, form, timeout=timeout)
        if form(html):
            log("CF lolos.")
            return html
        log("belum lolos, coba klik lagi...")
        await pg.wait_for_timeout(3000)
    return html


async def run(short_url: str, headless: bool = False) -> dict:
    proxy = os.environ.get("SMBY_PROXY", "").strip()
    alias = urlparse(short_url).path.strip("/").split("/")[0]
    if not alias:
        return {"ok": False, "error": "alias kosong", "input": short_url}
    facts: dict = {"input": short_url, "alias": alias,
                   "mrproblogger_url": MRPRO.format(alias)}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled",
                  "--window-size=1366,800", "--lang=en-US"])
        ctx = await browser.new_context(
            locale="en-US", viewport={"width": 1366, "height": 800},
            user_agent=UA, timezone_id="Asia/Jakarta",
            proxy={"server": proxy} if proxy else None)
        await ctx.add_init_script(STEALTH)
        pg = await ctx.new_page()
        try:
            await pg.goto(facts["mrproblogger_url"], wait_until="domcontentloaded",
                          timeout=60000, referer=THEMEZON)
            html = await solve_cf(pg)
            facts["cookies"] = [c["name"] for c in await ctx.cookies()]
            if not re.search(r'form[^>]*id="go-link"', html):
                facts.update(ok=False, error="form#go-link tidak muncul (CF gagal / alias invalid)",
                             title=await pg.title())
                return facts

            info = await pg.evaluate(r"""() => {
                const f = document.querySelector('form#go-link');
                const data = {};
                f.querySelectorAll('input').forEach(i => { if(i.name) data[i.name]=i.value; });
                const html = document.documentElement.innerHTML;
                const m = html.match(/counter_value["']?\s*[:=]\s*["']?(\d+)/);
                return {action: f.getAttribute('action') || '/links/go', data,
                        counter: m ? parseInt(m[1]) : 12, url: location.href};
            }""")
            facts["form_action"] = info["action"]
            facts["hidden_names"] = sorted(info["data"])
            facts["counter_value"] = info["counter"]
            log(f"form ok counter={info['counter']}s fields={sorted(info['data'])}")

            wait_s = max(1.0, float(info["counter"]) - 0.8)
            log(f"tunggu {wait_s:.1f}s lalu POST /links/go")
            await pg.wait_for_timeout(int(wait_s * 1000))

            data = json.dumps(info["data"])
            payload = await pg.evaluate(r"""async ([action, data]) => {
                const meta = document.querySelector('meta[name=csrf-token]');
                const body = new URLSearchParams(JSON.parse(data));
                const r = await fetch(action, {method:'POST', body,
                    headers:{'X-Requested-With':'XMLHttpRequest',
                             'Accept':'application/json, text/javascript, */*; q=0.01'},
                    credentials:'include'});
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch(e) {}
                return {status: r.status, json: j, raw: t.slice(0,300)};
            }""", [info["action"], data])
            facts["submit_status"] = payload["status"]
            facts["submit_payload"] = payload["json"]
            final = (payload["json"] or {}).get("url") if payload["json"] else None
            if final:
                facts.update(ok=True, bye=final)
                log("BYE:", final)
            else:
                facts.update(ok=False, error=(payload["json"] or {}).get("message")
                             or f"HTTP {payload['status']} tanpa url", raw=payload["raw"])
            return facts
        finally:
            await browser.close()


def main() -> int:
    argv = [a for a in sys.argv[1:]]
    as_json = "--json" in argv
    if as_json:
        argv.remove("--json")
    if not argv:
        print(__doc__)
        return 2
    res = asyncio.run(run(argv[0], headless=False))
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(res.get("bye") or "GAGAL: " + str(res.get("error")))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
