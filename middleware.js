// ─────────────────────────────────────────────────────────────────────────────
// Vercel Edge Middleware — SERVER-SIDE access gate (the real boundary).
//
// This runs on Vercel's edge BEFORE any file is served, so data.json and index.html
// are never delivered without a valid session cookie. Unlike the in-page passcode
// (which is a display gate only), this is enforced server-side.
//
// SETUP (see DEPLOY.md §8):
//   1. Put this file (middleware.js) at the REPO ROOT (same folder as index.html).
//   2. In Vercel → Project → Settings → Environment Variables, add:
//        SITE_PASSWORD = <your password>     (e.g. 23008133)
//      Redeploy. If SITE_PASSWORD is unset, this gate is inert (no server lock).
//
// The cookie is SameSite=None; Secure so it also works when the dashboard is
// embedded as a cross-origin <iframe> on Squarespace.
// ─────────────────────────────────────────────────────────────────────────────
import { next } from '@vercel/edge';

export const config = {
  // run on everything except Vercel internals + the favicon
  matcher: '/((?!_vercel/|favicon.ico).*)',
};

const COOKIE = 'fcm_gate';
const MAX_AGE = 60 * 60 * 12; // 12h session

async function sha256hex(s) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function loginPage(msg) {
  const err = msg ? `<p class="e">${msg}</p>` : '';
  const html = `<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>受控研究 · Access</title>
<style>
  *{box-sizing:border-box} html,body{margin:0;height:100%}
  body{background:#0a0e14;color:#e6edf3;font-family:Inter,system-ui,-apple-system,"PingFang TC","Microsoft JhengHei",sans-serif;
    display:flex;align-items:center;justify-content:center}
  .box{width:min(92vw,420px);background:linear-gradient(180deg,#10151d,#0c1118);border:1px solid #1e2631;
    border-radius:16px;padding:34px 30px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,.5)}
  .lock{font-size:11px;letter-spacing:.18em;color:#f5a623;font-weight:600;margin-bottom:18px}
  h1{font-size:15px;font-weight:700;letter-spacing:.04em;margin:0 0 4px;
    background:linear-gradient(90deg,#58a6ff,#a78bfa);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
  .sub{color:#8b98a9;font-size:12px;margin-bottom:22px;line-height:1.6}
  input{width:100%;background:#0a0e14;border:1px solid #1e2631;border-radius:9px;padding:12px 14px;color:#e6edf3;
    font-size:15px;text-align:center;letter-spacing:.1em;outline:none}
  input:focus{border-color:#58a6ff}
  button{width:100%;margin-top:14px;background:#f5a623;color:#1a1205;border:none;border-radius:9px;padding:12px;
    font-weight:700;font-size:14px;cursor:pointer}
  .e{color:#f6465d;font-size:12px;margin:12px 0 0;font-family:ui-monospace,monospace}
  .note{margin-top:14px;padding-top:13px;border-top:1px solid #1e2631;color:#5b6675;font-size:10px;line-height:1.6}
</style></head><body>
  <form class="box" method="POST" action="/?__auth=1">
    <div class="lock">🔒 ACCESS · 受控研究</div>
    <h1>金融狀況 / 風險體制監測</h1>
    <div class="sub">Financial Conditions &amp; Risk-Regime Monitor · 投資委員會內部使用</div>
    <input name="p" type="password" inputmode="numeric" autocomplete="off" placeholder="輸入通行碼 · passcode" autofocus>
    <button type="submit">進入 · Enter</button>
    ${err}
    <div class="note">伺服器端存取控管(Vercel Edge)。通過後才會傳送任何資料(含 data.json)。</div>
  </form>
</body></html>`;
  return new Response(html, {
    status: msg ? 401 : 401,
    headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
  });
}

export default async function middleware(request) {
  const url = new URL(request.url);
  const password = (typeof process !== 'undefined' && process.env && process.env.SITE_PASSWORD) || '';
  if (!password) return next(); // not configured → server gate inert (in-page gate still applies)

  const expected = await sha256hex(password);

  // login submission
  if (request.method === 'POST' && url.searchParams.has('__auth')) {
    let p = '';
    try { const form = await request.formData(); p = (form.get('p') || '').toString(); } catch (e) {}
    if (p === password) {
      const h = new Headers({ location: '/', 'cache-control': 'no-store' });
      h.append('set-cookie',
        `${COOKIE}=${expected}; Path=/; HttpOnly; Secure; SameSite=None; Max-Age=${MAX_AGE}`);
      return new Response(null, { status: 303, headers: h });
    }
    return loginPage('密碼錯誤 · incorrect passcode');
  }

  // valid session?
  const cookie = request.headers.get('cookie') || '';
  const m = cookie.match(new RegExp(COOKIE + '=([a-f0-9]+)'));
  if (m && m[1] === expected) return next();

  return loginPage('');
}
