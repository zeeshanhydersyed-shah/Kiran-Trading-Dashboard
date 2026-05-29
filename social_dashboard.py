"""
Social Media Studio — local dashboard for @KaramaSheikh
========================================================
Run:  python social_dashboard.py
Opens automatically at http://localhost:8765
Press Ctrl+C to stop.

No new pip installs needed. Uses only stdlib + packages already
in your pipeline (pandas, matplotlib via content_generator).
Chat agent powered by Groq (free) — reads GROQ_API_KEY from .env.
READ-ONLY: never writes to any database.
"""

import base64
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "twitter_output"
DRAFTS_FILE = OUTPUT_DIR / "drafts.json"
sys.path.insert(0, str(BASE_DIR))

PORT = 8765

# ── Load .env ─────────────────────────────────────────────────────────────────
_env = BASE_DIR / ".env"
if _env.exists():
    with open(_env) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                # Strip surrounding quotes from value (single or double)
                v = v.strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip().strip('"').strip("'")
GROQ_MODELS  = [          # tried in order until one works
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
]

AGENT_SYSTEM = """You are a social media content assistant for @KaramaSheikh — a PSX (Pakistan Stock Exchange) swing trader who posts data-driven market insights on Twitter/X.

His voice: direct, data-backed, accessible English (simple enough for non-native readers). Short sentences. Lead with a number or fact, then follow with an opinion or insight. No jargon. No hype.

You help him:
- Rephrase tweets to sound more natural or punchy
- Generate alternative versions of a draft
- Suggest new content ideas based on his market data
- Adjust tone (more casual / more analytical)
- Add or remove hashtags
- Write fresh tweet ideas on any PSX market topic he mentions

Hard rules — never break these:
- NEVER suggest posting personal P&L figures, win/loss records, or trade journal data
- Always keep "Not financial advice" in any setup-related content
- Keep at minimum #PSX #KSE100 for market tweets
- Keep tweets under 280 characters (point it out if a draft is over)

Preferred post times (PKT): Breadth at 4:30 PM weekdays, Setups on Sunday 9 AM, Sectors on Monday 8 AM."""


# ── Data helpers ──────────────────────────────────────────────────────────────
def load_drafts() -> dict:
    if not DRAFTS_FILE.exists():
        return {}
    with open(DRAFTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def refresh_drafts() -> dict:
    try:
        from content_generator import generate_all
        return generate_all()
    except Exception as e:
        return {"error": str(e)}


def serve_png(path: str, handler) -> bool:
    """Serve a PNG file directly. Returns True if file was found."""
    p = Path(path)
    if p.exists():
        data = p.read_bytes()
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
        return True
    return False


# ── Groq chat ─────────────────────────────────────────────────────────────────
def call_llm(messages: list) -> str:
    """Chat via Groq (free). Tries multiple models until one responds."""
    if not GROQ_API_KEY:
        return "⚠️ GROQ_API_KEY not found in .env — restart after adding it."

    try:
        from groq import Groq
    except ImportError:
        return "⚠️ Groq SDK not installed. Run: pip install groq"

    client = Groq(api_key=GROQ_API_KEY)

    for model in GROQ_MODELS:
        try:
            print(f"[groq] trying model: {model}", flush=True)
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.72,
                max_tokens=900,
            )
            print(f"[groq] success with {model}", flush=True)
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[groq] {model} failed: {e}", flush=True)

    return "⚠️ All Groq models failed — check terminal for details."


# ── HTML builder ──────────────────────────────────────────────────────────────
def build_html(drafts: dict) -> str:
    generated_at = drafts.get("generated_at", "")
    content      = drafts.get("content", {})

    breadth     = content.get("breadth", {})
    setups      = content.get("setups", {})
    sectors     = content.get("sectors", {})

    # Check if chart files exist (for showing/hiding placeholder)
    breadth_chart_ok = Path(breadth.get("chart", "")).exists()
    kse_chart_ok     = Path(breadth.get("kse_chart", "")).exists()
    sector_chart_ok  = Path(sectors.get("chart", "")).exists()

    breadth_tweet  = (breadth.get("tweet") or "").replace("`", "\\`").replace("\\n", "\\n")
    sectors_tweet  = (sectors.get("tweet") or "").replace("`", "\\`")

    setups_stale  = setups.get("stale", False)
    setups_thread = setups.get("thread", [])

    # Build setup thread HTML
    if setups_stale:
        setups_html = f"""
        <div class="stale-banner">
          ⏰ Setups are stale — newest qualifying setup is from {setups.get('newest_date','?')}.
          Run <code>python content_generator.py</code> after the next scraper run for fresh picks.
        </div>"""
    elif not setups_thread:
        setups_html = '<p class="no-data">No qualifying setups found (risk &gt; 6% or no data).</p>'
    else:
        tweets_html = ""
        for i, tw in enumerate(setups_thread):
            label   = "Intro" if i == 0 else ("Disclaimer" if i == len(setups_thread) - 1 else f"Tweet {i}")
            escaped = tw.replace("\\", "\\\\").replace("`", "\\`").replace("\n", "\\n")
            tweets_html += f"""
            <div class="thread-tweet">
              <div class="thread-label">{label}</div>
              <pre class="tweet-text">{tw}</pre>
              <button class="btn-copy" onclick="copyText(`{escaped}`)">Copy</button>
            </div>"""
        setups_html = tweets_html

    # Drafts context for the agent (injected into system prompt)
    drafts_context = ""
    if breadth_tweet:
        drafts_context += f"\n\nCurrent breadth draft:\n{breadth.get('tweet','')}"
    if sectors_tweet:
        drafts_context += f"\n\nCurrent sector rotation draft:\n{sectors.get('tweet','')}"
    if setups_thread and not setups_stale:
        drafts_context += f"\n\nCurrent setups thread ({len(setups_thread)} tweets):\n" + "\n---\n".join(setups_thread)

    agent_system_json = json.dumps(AGENT_SYSTEM + drafts_context)

    gen_label = f"Last generated: {generated_at[:16].replace('T',' ')} PKT" if generated_at else "No drafts yet — run content_generator.py first"

    breadth_img_tag = '<img src="/chart/breadth" alt="Breadth chart" style="width:100%"/>' if breadth_chart_ok else '<p class="no-chart">Chart not found — run generator first.</p>'
    kse_img_tag     = '<img src="/chart/kse" alt="KSE-100 chart" style="width:100%"/>'     if kse_chart_ok     else ''
    sector_img_tag  = '<img src="/chart/sectors" alt="Sector chart" style="width:100%"/>'  if sector_chart_ok  else '<p class="no-chart">Chart not found — run generator first.</p>'

    breadth_escaped  = breadth_tweet.replace("\n", "\\n").replace("`", "\\`")
    sectors_escaped  = sectors_tweet.replace("\n", "\\n").replace("`", "\\`")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Social Studio · @KaramaSheikh</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0f1117;color:#e2e8f0;height:100vh;display:flex;flex-direction:column;overflow:hidden}}

  /* ── Top bar ── */
  .topbar{{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;background:#0f1117;border-bottom:1px solid #1e293b;flex-shrink:0}}
  .topbar-left{{display:flex;align-items:center;gap:10px}}
  .topbar h1{{font-size:15px;font-weight:700;color:#f1f5f9}}
  .handle{{font-size:11px;color:#7dd3fc;font-weight:600;background:#0f2a3f;padding:3px 10px;border-radius:12px}}
  .gen-label{{font-size:10px;color:#475569}}
  .topbar-right{{display:flex;gap:8px}}
  .btn-refresh{{background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:6px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;transition:.15s}}
  .btn-refresh:hover{{background:#334155;color:#e2e8f0}}
  .btn-refresh.spinning{{opacity:.6;pointer-events:none}}

  /* ── Main layout ── */
  .main{{display:flex;flex:1;overflow:hidden}}

  /* ── Drafts panel ── */
  .panel-drafts{{width:58%;border-right:1px solid #1e293b;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:16px}}

  .draft-card{{background:#161b27;border:1px solid #1e293b;border-radius:10px;overflow:hidden}}
  .card-header{{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid #1e293b}}
  .card-title{{font-size:12px;font-weight:700;color:#f1f5f9;display:flex;align-items:center;gap:7px}}
  .cadence{{font-size:9px;font-weight:600;background:#1e293b;color:#64748b;padding:2px 8px;border-radius:10px}}
  .card-body{{padding:14px}}

  pre.tweet-text{{font-family:inherit;font-size:12px;color:#cbd5e1;line-height:1.55;white-space:pre-wrap;word-break:break-word;margin-bottom:10px}}
  .char-count{{font-size:10px;margin-bottom:8px}}
  .char-ok{{color:#64748b}} .char-warn{{color:#f59e0b}} .char-over{{color:#ef4444}}

  .btn-copy{{background:#1e3a5f;color:#7dd3fc;border:1px solid #1e4a7f;padding:5px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;transition:.15s}}
  .btn-copy:hover{{background:#1e4a7f}}
  .btn-copy.copied{{background:#14532d;color:#86efac;border-color:#166534}}

  .card-img{{margin-top:12px;border-radius:6px;overflow:hidden;border:1px solid #1e293b}}
  .card-img img{{width:100%;display:block}}
  .no-chart{{font-size:11px;color:#475569;padding:10px;text-align:center}}

  /* Thread tweets */
  .thread-tweet{{background:#0f1117;border:1px solid #1e293b;border-radius:8px;padding:12px;margin-bottom:8px}}
  .thread-label{{font-size:9px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
  .stale-banner{{background:#2d1f00;border:1px solid #92400e;border-radius:8px;padding:10px 12px;font-size:11px;color:#fbbf24;line-height:1.5}}
  .stale-banner code{{background:#1f1200;padding:2px 6px;border-radius:4px;font-size:10px;color:#fde68a}}
  .no-data{{font-size:11px;color:#475569;padding:10px}}

  /* ── Chat panel ── */
  .panel-chat{{flex:1;display:flex;flex-direction:column;min-width:0}}
  .chat-header{{padding:12px 16px;border-bottom:1px solid #1e293b;flex-shrink:0}}
  .chat-header h2{{font-size:13px;font-weight:700;color:#f1f5f9}}
  .chat-header p{{font-size:10px;color:#475569;margin-top:2px}}

  .messages{{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px}}
  .msg{{max-width:90%;padding:10px 13px;border-radius:10px;font-size:12px;line-height:1.55;word-break:break-word;white-space:pre-wrap}}
  .msg-user{{align-self:flex-end;background:#1e3a5f;color:#e0f2fe;border-bottom-right-radius:3px}}
  .msg-agent{{align-self:flex-start;background:#1e293b;color:#cbd5e1;border-bottom-left-radius:3px}}
  .msg-system{{align-self:center;background:transparent;color:#475569;font-size:10px;font-style:italic}}
  .typing{{align-self:flex-start;background:#1e293b;color:#475569;font-size:12px;padding:10px 14px;border-radius:10px;border-bottom-left-radius:3px}}

  .quick-actions{{padding:8px 16px;display:flex;gap:6px;flex-wrap:wrap;border-top:1px solid #1e293b;flex-shrink:0}}
  .qa{{background:#1e293b;color:#94a3b8;border:1px solid #334155;padding:4px 10px;border-radius:12px;font-size:10px;font-weight:600;cursor:pointer;transition:.15s;white-space:nowrap}}
  .qa:hover{{background:#334155;color:#e2e8f0}}

  .chat-input-row{{display:flex;gap:8px;padding:12px 16px;border-top:1px solid #1e293b;flex-shrink:0}}
  #chat-input{{flex:1;background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:9px 13px;border-radius:8px;font-size:12px;font-family:inherit;resize:none;height:60px;outline:none;line-height:1.45}}
  #chat-input:focus{{border-color:#3b82f6}}
  #send-btn{{background:#2563eb;color:#fff;border:none;padding:0 16px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:700;transition:.15s;flex-shrink:0}}
  #send-btn:hover{{background:#1d4ed8}}
  #send-btn:disabled{{opacity:.4;pointer-events:none}}

  ::-webkit-scrollbar{{width:5px}} ::-webkit-scrollbar-track{{background:#0f1117}} ::-webkit-scrollbar-thumb{{background:#334155;border-radius:3px}}
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
  <div class="topbar-left">
    <h1>🐦 Social Studio</h1>
    <span class="handle">@KaramaSheikh</span>
    <span class="gen-label">{gen_label}</span>
  </div>
  <div class="topbar-right">
    <button class="btn-refresh" id="refresh-btn" onclick="refreshDrafts()">⚡ Refresh Drafts</button>
  </div>
</div>

<!-- Main -->
<div class="main">

  <!-- Drafts panel -->
  <div class="panel-drafts">

    <!-- Breadth -->
    <div class="draft-card">
      <div class="card-header">
        <div class="card-title">📊 Market Breadth <span class="cadence">Daily · 4:30 PM PKT</span></div>
        <button class="btn-copy" id="copy-breadth" onclick="copyText(`{breadth_escaped}`, 'copy-breadth')">Copy</button>
      </div>
      <div class="card-body">
        {'<p class="no-data">No breadth data — run content_generator.py first.</p>' if not breadth_tweet else f'<pre class="tweet-text">{breadth.get("tweet","")}</pre><div class="char-count" id="cc-breadth"></div>'}
        <div class="card-img">{breadth_img_tag}</div>
        {f'<div class="card-img" style="margin-top:8px">{kse_img_tag}</div>' if kse_img_tag else ''}
      </div>
    </div>

    <!-- Sector Rotation -->
    <div class="draft-card">
      <div class="card-header">
        <div class="card-title">📈 Sector Rotation <span class="cadence">Weekly · Mon 8 AM PKT</span></div>
        <button class="btn-copy" id="copy-sectors" onclick="copyText(`{sectors_escaped}`, 'copy-sectors')">Copy</button>
      </div>
      <div class="card-body">
        {'<p class="no-data">No sector data — run content_generator.py first.</p>' if not sectors_tweet else f'<pre class="tweet-text">{sectors.get("tweet","")}</pre><div class="char-count" id="cc-sectors"></div>'}
        <div class="card-img">{sector_img_tag}</div>
      </div>
    </div>

    <!-- Setups -->
    <div class="draft-card">
      <div class="card-header">
        <div class="card-title">🔍 Screener Setups <span class="cadence">Weekly · Sun 9 AM PKT</span></div>
      </div>
      <div class="card-body">
        {setups_html}
      </div>
    </div>

  </div><!-- /panel-drafts -->

  <!-- Chat panel -->
  <div class="panel-chat">
    <div class="chat-header">
      <h2>💬 Social Media Agent</h2>
      <p>Rephrase tweets · Generate ideas · Adjust tone · Check length</p>
    </div>

    <div class="messages" id="messages">
      <div class="msg msg-system">Agent loaded with today's drafts. Ask anything.</div>
    </div>

    <div class="quick-actions">
      <button class="qa" onclick="quickAction('Rephrase the breadth tweet to sound punchier and more casual.')">Rephrase breadth tweet</button>
      <button class="qa" onclick="quickAction('Suggest 3 alternative hashtag combinations for PSX market tweets.')">Hashtag ideas</button>
      <button class="qa" onclick="quickAction('Give me 2 fresh tweet ideas based on the current market data — breadth is neutral at 45%.')">Fresh ideas</button>
      <button class="qa" onclick="quickAction('Check if any of today\\'s drafts are over 280 characters and suggest how to shorten them.')">Check length</button>
      <button class="qa" onclick="quickAction('Write a short engaging hook line I can use to start a thread about sector rotation.')">Thread hook</button>
    </div>

    <div class="chat-input-row">
      <textarea id="chat-input" placeholder="Ask the agent anything — rephrase this, give me ideas, make it shorter..." onkeydown="handleKey(event)"></textarea>
      <button id="send-btn" onclick="sendMessage()">➤</button>
    </div>
  </div>

</div><!-- /main -->

<script>
  // ── Chat state ────────────────────────────────────────────────────────────
  const SYSTEM = {agent_system_json};
  const history = [];

  function addMsg(role, text) {{
    const el = document.createElement('div');
    el.className = role === 'user' ? 'msg msg-user' : 'msg msg-agent';
    el.textContent = text;
    document.getElementById('messages').appendChild(el);
    el.scrollIntoView({{behavior:'smooth'}});
    return el;
  }}

  function addTyping() {{
    const el = document.createElement('div');
    el.className = 'typing'; el.id = 'typing'; el.textContent = '…';
    document.getElementById('messages').appendChild(el);
    el.scrollIntoView({{behavior:'smooth'}});
  }}

  function removeTyping() {{
    const el = document.getElementById('typing');
    if (el) el.remove();
  }}

  async function sendMessage(text) {{
    const input = document.getElementById('chat-input');
    const msg   = text || input.value.trim();
    if (!msg) return;
    input.value = '';
    document.getElementById('send-btn').disabled = true;

    addMsg('user', msg);
    history.push({{role:'user', content:msg}});
    addTyping();

    try {{
      const res = await fetch('/api/chat', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{
          messages: [{{role:'system', content:SYSTEM}}, ...history]
        }})
      }});
      const data = await res.json();
      removeTyping();
      const reply = data.reply || '(no response)';
      addMsg('agent', reply);
      history.push({{role:'assistant', content:reply}});
    }} catch(e) {{
      removeTyping();
      addMsg('agent', 'Error: ' + e.message);
    }}

    document.getElementById('send-btn').disabled = false;
    input.focus();
  }}

  function quickAction(text) {{ sendMessage(text); }}

  function handleKey(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{ e.preventDefault(); sendMessage(); }}
  }}

  // ── Copy ──────────────────────────────────────────────────────────────────
  function copyText(text, btnId) {{
    const clean = text.replace(/\\\\n/g, '\\n');
    navigator.clipboard.writeText(clean).then(() => {{
      if (!btnId) return;
      const btn = document.getElementById(btnId);
      if (!btn) return;
      const orig = btn.textContent;
      btn.textContent = '✓ Copied';
      btn.classList.add('copied');
      setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 2000);
    }});
  }}

  // ── Char counts ───────────────────────────────────────────────────────────
  function charCount(text, elId) {{
    const el = document.getElementById(elId);
    if (!el || !text) return;
    const n = text.replace(/\\\\n/g,'\\n').length;
    const cls = n > 280 ? 'char-over' : n > 250 ? 'char-warn' : 'char-ok';
    el.className = 'char-count ' + cls;
    el.textContent = n + ' / 280 characters';
  }}
  charCount(`{breadth_escaped}`, 'cc-breadth');
  charCount(`{sectors_escaped}`, 'cc-sectors');

  // ── Refresh ───────────────────────────────────────────────────────────────
  async function refreshDrafts() {{
    const btn = document.getElementById('refresh-btn');
    btn.textContent = '⏳ Generating…';
    btn.classList.add('spinning');
    try {{
      await fetch('/api/refresh', {{method:'POST', body:'{{}}', headers:{{'Content-Type':'application/json'}}}});
      window.location.reload();
    }} catch(e) {{
      btn.textContent = '⚡ Refresh Drafts';
      btn.classList.remove('spinning');
      alert('Error: ' + e.message);
    }}
  }}
</script>
</body>
</html>"""


# ── HTTP Server ───────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Quiet server logs

    def send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            drafts = load_drafts()
            html   = build_html(drafts).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        elif self.path == "/chart/breadth":
            drafts = load_drafts()
            path = drafts.get("content", {}).get("breadth", {}).get("chart", "")
            if not serve_png(path, self):
                self.send_response(404); self.end_headers()

        elif self.path == "/chart/kse":
            drafts = load_drafts()
            path = drafts.get("content", {}).get("breadth", {}).get("kse_chart", "")
            if not serve_png(path, self):
                self.send_response(404); self.end_headers()

        elif self.path == "/chart/sectors":
            drafts = load_drafts()
            path = drafts.get("content", {}).get("sectors", {}).get("chart", "")
            if not serve_png(path, self):
                self.send_response(404); self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")

        if self.path == "/api/chat":
            messages = body.get("messages", [])
            print("[server] /api/chat received", flush=True)
            reply    = call_llm(messages)
            self.send_json({"reply": reply})

        elif self.path == "/api/refresh":
            result = refresh_drafts()
            self.send_json(result)

        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Startup diagnostics
    print("\n── Social Studio startup ──────────────────────────", flush=True)
    if GROQ_API_KEY:
        print(f"  GROQ_API_KEY : found ({len(GROQ_API_KEY)} chars, starts with {GROQ_API_KEY[:8]}...)", flush=True)
    else:
        print("  GROQ_API_KEY : NOT FOUND — check your .env file", flush=True)
    try:
        from groq import Groq
        print("  Groq SDK     : installed ✓", flush=True)
    except ImportError:
        print("  Groq SDK     : NOT installed — run: pip install groq", flush=True)
    print("───────────────────────────────────────────────────\n", flush=True)

    # Generate drafts on first run if output doesn't exist
    if not DRAFTS_FILE.exists():
        print("No drafts found — generating now…")
        OUTPUT_DIR.mkdir(exist_ok=True)
        refresh_drafts()

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url    = f"http://localhost:{PORT}"

    print(f"🐦  Social Studio running at {url}")
    print("    Press Ctrl+C to stop.\n")

    # Open browser after a short delay
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
