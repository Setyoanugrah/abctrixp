# abctrixp

ShrinkMe shortlink bypass API di GitHub Actions.

    GET  https://smby.rikuzetsi.my.id/health
    GET  https://smby.rikuzetsi.my.id/bypass?url=https://shrinkme.click/XXXX
    POST https://smby.rikuzetsi.my.id/bypass   {"url":"..."}

Header: `X-Token: <SMBY_TOKEN>`.

Engine: Playwright + Chromium (xvfb, headful) -> Turnstile -> form#go-link -> POST /links/go.

`SMBY_PROXY` (opsional): arahkan trafik browser ke proxy luar, mis. `socks5://127.0.0.1:1080`
yang di-bridge dari HP lewat `cloudflared access tcp`.
