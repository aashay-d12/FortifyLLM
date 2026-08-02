def render_stats_html(stats: dict) -> str:
    layer_rows = "".join(
        f'<div class="row"><span>{layer}</span><span>{count}</span></div>'
        for layer, count in stats["blocked_by_layer"].items()
    ) or '<div class="row muted"><span>no blocks yet</span></div>'

    source_rows = "".join(
        f'<div class="row"><span>{source}</span><span>{count}</span></div>'
        for source, count in stats["by_source"].items()
    ) or '<div class="row muted"><span>no traffic yet</span></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>FortifyLLM — stats</title>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0A0E14; --panel: #10161F; --border: #1E2A38;
    --text: #E4ECF3; --muted: #7C8CA0; --safe: #35D0A0;
    --block: #FF6B5E; --signature: #F2B84B;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: 'IBM Plex Sans', sans-serif; padding: 32px 24px;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  h1 {{
    font-family: 'IBM Plex Mono', monospace; font-size: 18px;
    margin: 0 0 4px 0;
  }}
  .subtitle {{ color: var(--muted); font-size: 13px; margin-bottom: 28px; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px; margin-bottom: 24px;
  }}
  .card {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 16px;
  }}
  .card .label {{
    font-family: 'IBM Plex Mono', monospace; font-size: 11px;
    text-transform: uppercase; color: var(--muted); letter-spacing: 0.06em;
  }}
  .card .value {{
    font-family: 'IBM Plex Mono', monospace; font-size: 26px;
    font-weight: 600; margin-top: 6px;
  }}
  .card.safe .value {{ color: var(--safe); }}
  .card.block .value {{ color: var(--block); }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 6px; padding: 16px; margin-bottom: 16px;
  }}
  .panel h2 {{
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    text-transform: uppercase; color: var(--muted); margin: 0 0 10px 0;
    letter-spacing: 0.06em;
  }}
  .row {{
    display: flex; justify-content: space-between;
    font-family: 'IBM Plex Mono', monospace; font-size: 13px;
    padding: 5px 0; border-bottom: 1px solid var(--border);
  }}
  .row:last-child {{ border-bottom: none; }}
  .row.muted {{ color: var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>FortifyLLM — Usage Stats</h1>
  <div class="subtitle">Computed from logs/requests.jsonl. Not publicly accessible.</div>

  <div class="grid">
    <div class="card"><div class="label">Total Requests</div><div class="value">{stats['total_events']}</div></div>
    <div class="card safe"><div class="label">Allowed</div><div class="value">{stats['allowed']}</div></div>
    <div class="card block"><div class="label">Blocked</div><div class="value">{stats['blocked']}</div></div>
    <div class="card"><div class="label">Block Rate</div><div class="value">{stats['block_rate']*100:.1f}%</div></div>
    <div class="card"><div class="label">Unique Visitors</div><div class="value">{stats['unique_client_ips']}</div></div>
    <div class="card"><div class="label">Upstream Errors</div><div class="value">{stats['upstream_errors']}</div></div>
  </div>

  <div class="panel">
    <h2>Blocked by layer</h2>
    {layer_rows}
  </div>

  <div class="panel">
    <h2>Traffic by source</h2>
    {source_rows}
  </div>
</div>
</body>
</html>"""
