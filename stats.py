import json
import os

import config


def compute_stats() -> dict:
    if not os.path.exists(config.LOG_FILE):
        return {
            "total_events": 0, "allowed": 0, "blocked": 0, "block_rate": 0,
            "blocked_by_layer": {}, "by_source": {}, "unique_client_ips": 0,
            "upstream_errors": 0, "first_event_ts": None, "last_event_ts": None,
        }

    total = allowed = blocked = upstream_errors = 0
    by_layer = {}
    by_source = {}
    unique_ips = set()
    first_ts = last_ts = None

    with open(config.LOG_FILE) as f:
        for line in f:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue

            total += 1
            ts = e.get("timestamp")
            if ts:
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)

            ip = e.get("client_ip")
            if ip:
                unique_ips.add(ip)

            source = e.get("source", "api")  # events without a source tag are the main API
            by_source[source] = by_source.get(source, 0) + 1

            event = e.get("event")
            if event == "blocked":
                blocked += 1
                layer = e.get("layer", "unknown")
                by_layer[layer] = by_layer.get(layer, 0) + 1
            elif event == "allowed":
                allowed += 1
            elif event == "upstream_error":
                upstream_errors += 1

    return {
        "total_events": total,
        "allowed": allowed,
        "blocked": blocked,
        "block_rate": round(blocked / total, 3) if total else 0,
        "blocked_by_layer": by_layer,
        "by_source": by_source,
        # Unique client IPs is a reasonable proxy for "distinct visitors" —
        # not perfect (shared IPs, VPNs) but honest and doesn't require any
        # tracking beyond what's already logged for security purposes.
        "unique_client_ips": len(unique_ips),
        "upstream_errors": upstream_errors,
        "first_event_ts": first_ts,
        "last_event_ts": last_ts,
    }
