DEMO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FortifyLLM — try to get past the firewall</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
%%ANALYTICS_SCRIPT%%
<style>
  :root {
    --bg: #0A0E14;
    --panel: #10161F;
    --border: #1E2A38;
    --text: #E4ECF3;
    --muted: #7C8CA0;
    --safe: #35D0A0;
    --block: #FF6B5E;
    --signature: #F2B84B;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    background-image:
      linear-gradient(var(--border) 1px, transparent 1px),
      linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 32px 32px;
    background-position: -1px -1px;
    color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
  }
  .console {
    width: 100%;
    max-width: 720px;
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
  }
  .console-header {
    padding: 18px 22px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .status-dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: var(--signature);
    box-shadow: 0 0 8px var(--signature);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .brand-name {
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.02em;
  }
  .status-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .console-sub {
    padding: 14px 22px;
    border-bottom: 1px solid var(--border);
    font-size: 13px;
    color: var(--muted);
    line-height: 1.5;
  }
  .console-sub b { color: var(--text); }
  .transcript {
    height: 420px;
    overflow-y: auto;
    padding: 20px 22px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13.5px;
    line-height: 1.6;
  }
  .msg { margin-bottom: 16px; }
  .msg-label {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 3px;
  }
  .msg-user .msg-label { color: var(--text); }
  .msg-bot .msg-label { color: var(--safe); }
  .msg-blocked .msg-label { color: var(--block); }
  .msg-body { white-space: pre-wrap; word-break: break-word; }
  .msg-blocked .msg-body { color: var(--block); }
  .verdict-tag {
    display: inline-block;
    margin-top: 6px;
    font-size: 11px;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 2px 6px;
  }
  .input-row {
    display: flex;
    border-top: 1px solid var(--border);
    padding: 14px 16px;
    gap: 10px;
  }
  #input {
    flex: 1;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13.5px;
    padding: 10px 12px;
    outline: none;
  }
  #input:focus { border-color: var(--safe); }
  #send {
    background: var(--safe);
    color: var(--bg);
    border: none;
    border-radius: 4px;
    padding: 0 18px;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    font-size: 13px;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  #send:hover { opacity: 0.85; }
  #send:disabled { opacity: 0.4; cursor: not-allowed; }
  ::-webkit-scrollbar { width: 8px; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
</style>
</head>
<body>
  <div class="console">
    <div class="console-header">
      <div class="brand">
        <div class="status-dot"></div>
        <span class="brand-name">FortifyLLM</span>
      </div>
    </div>
    <div class="console-sub">
      A multi-tier firewall sitting in front of an LLM. Every message is screened
      before it ever reaches the model. <b>Try to get something past it</b> —
      every attempt is logged and shown with the detection layer that caught it, if any.
    </div>
    <div class="console-sub" id="live-stats" style="font-family:'IBM Plex Mono',monospace;font-size:12px;">
      loading stats...
    </div>
    <div class="transcript" id="transcript"></div>
    <div class="input-row">
      <input id="input" type="text" placeholder="Type a message, or try to jailbreak me..." autocomplete="off">
      <button id="send">SEND</button>
    </div>
  </div>

<script>
  const transcript = document.getElementById('transcript');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('send');
  let history = [];

  function stripMarkdown(text) {
    // Converts common LLM markdown into clean plain text for the terminal-
    // style transcript. Deliberately does NOT render actual HTML — this
    // stays a plain-text transform so we can keep using .textContent below,
    // never .innerHTML. Rendering LLM output as raw HTML would be a real
    // XSS risk (a crafted prompt could get the model to emit <script> tags) —
    // an especially bad look in a project specifically about prompt-injection
    // defense, so plain-text-only display is a deliberate safety choice, not
    // a missing feature.
    return text
      .replace(/\*\*(.+?)\*\*/g, '$1')   // **bold** -> bold
      .replace(/\*(.+?)\*/g, '$1')       // *italic* -> italic
      .replace(/^#{1,6}\s*(.+)$/gm, '$1') // ## Heading -> Heading
      .replace(/^[-*]\s+/gm, '  • ');    // - bullet -> • bullet
  }

  function addMessage(role, text, verdict) {
    const div = document.createElement('div');
    if (verdict && verdict.blocked) {
      div.className = 'msg msg-blocked';
      div.innerHTML = `<div class="msg-label">⛔ blocked</div>` +
        `<div class="msg-body"></div>` +
        `<div class="verdict-tag"></div>`;
      div.querySelector('.msg-body').textContent = text;
      div.querySelector('.verdict-tag').textContent =
        `layer=${verdict.layer}` + (verdict.score != null ? ` score=${verdict.score.toFixed(3)}` : '');
    } else {
      div.className = role === 'user' ? 'msg msg-user' : 'msg msg-bot';
      div.innerHTML = `<div class="msg-label">${role === 'user' ? 'you' : 'assistant'}</div>` +
        `<div class="msg-body"></div>`;
      div.querySelector('.msg-body').textContent = role === 'user' ? text : stripMarkdown(text);
    }
    transcript.appendChild(div);
    transcript.scrollTop = transcript.scrollHeight;
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendBtn.disabled = true;

    addMessage('user', text);
    history.push({ role: 'user', content: text });

    try {
      const res = await fetch('/api/demo-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });

      if (!res.ok) {
        addMessage('assistant', `Server error (HTTP ${res.status}). Check the server logs.`);
        history.pop();
        return;
      }

      const data = await res.json();

      if (data.blocked) {
        addMessage('assistant', text, data);
        // Don't let a blocked prompt pollute the conversation history sent
        // to the LLM on the next turn.
        history.pop();
      } else {
        addMessage('assistant', data.reply || '(no response)');
        history.push({ role: 'assistant', content: data.reply || '' });
      }
    } catch (err) {
      addMessage('assistant', 'Connection error — the server may be waking up (free-tier cold start). Try again in a few seconds.');
      history.pop();
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
  input.focus();

  // Live counter — safe aggregate numbers only, fetched from the public
  // stats endpoint (no auth needed, no PII returned).
  fetch('/api/public-stats')
    .then(r => r.json())
    .then(s => {
      document.getElementById('live-stats').textContent =
        `${s.messages_screened} messages screened · ${s.attacks_blocked} attacks blocked · ${s.unique_visitors} visitors so far`;
    })
    .catch(() => {
      document.getElementById('live-stats').textContent = '';
    });
</script>
</body>
</html>
"""

def render_demo_html(umami_website_id: str = "") -> str:
    if umami_website_id:
        script = f'<script defer src="https://cloud.umami.is/script.js" data-website-id="{umami_website_id}"></script>'
    else:
        script = ""
    return DEMO_HTML.replace("%%ANALYTICS_SCRIPT%%", script)
