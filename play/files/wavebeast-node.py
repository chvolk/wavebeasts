#!/usr/bin/env python3
"""WaveBeast listener node — the slim client (stdlib only; NOT the full engine).

It assembles a ScanBundle from whatever local sensors it can read and POSTs it to your account on the
site (default wavebeasts.com) on a timer, honouring the site's rate limit. Run one on a phone, a Pi,
EDI/Bishop, or any PC signed in with a node token.

Config via env:
  WB_SITE          site base URL            (default https://wavebeasts.com)
  WB_NODE_TOKEN    node token from your profile   (required)
  WB_INTERVAL      seconds between passive snapshots (minimum/default 1800)
  WB_ENVIRON_URL   optional JSON endpoint of environment scalars (e.g. Bishop enviro) to fold in
  WB_SIGNALS_CMD   optional command whose stdout is a JSON array of extra signals
  WB_ONCE          if set, send a single snapshot and exit
"""

import hashlib
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

SITE = os.environ.get("WB_SITE", "https://wavebeasts.com").rstrip("/")
TOKEN = os.environ.get("WB_NODE_TOKEN", "")
VERSION = "1.2.0"
INTERVAL = max(1800, int(os.environ.get("WB_INTERVAL", "1800")))
STATE = Path(
    os.environ.get(
        "WB_STATE_FILE",
        str(
            Path.home()
            / ".local/state/wavebeast-node"
            / (hashlib.sha256((SITE + TOKEN).encode()).hexdigest()[:16] + ".txt")
        ),
    )
)
ENVIRON_URL = os.environ.get("WB_ENVIRON_URL", "")
SIGNALS_CMD = os.environ.get("WB_SIGNALS_CMD", "")


def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def collect_wifi():
    """Nearby APs via nmcli (common on Linux/Pi). Silent if unavailable."""
    if not shutil.which("nmcli"):
        return []
    try:
        out = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL", "dev", "wifi"],
            capture_output=True,
            text=True,
            timeout=8,
        ).stdout
    except Exception:
        return []
    sigs = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0]
        signal = parts[-1]
        bssid = ":".join(parts[1:-1])
        try:
            pct = int(signal)
        except ValueError:
            continue
        rssi = int(pct / 2 - 100)  # rough %→dBm
        sigs.append(
            {
                "kind": "wifi",
                "id": bssid,
                "strength": clamp01(pct / 100.0),
                "value": {"ssid": ssid, "bssid": bssid, "rssi": rssi},
            }
        )
    return sigs[:20]


def collect_environ():
    if not ENVIRON_URL:
        return []
    try:
        with urllib.request.urlopen(ENVIRON_URL, timeout=6) as r:
            m = json.loads(r.read().decode())
    except Exception:
        return []
    sigs = []
    mapping = [
        ("temperature", "temp_c", 40),
        ("humidity", "humidity_pct", 100),
        ("pressure", "pressure_hpa", 1100),
        ("lux", "lux", 1000),
        ("noise", "sound_db", 100),
    ]
    for key, metric, norm in mapping:
        v = m.get(key)
        if isinstance(v, (int, float)):
            sigs.append(
                {
                    "kind": "scalar",
                    "strength": clamp01(v / norm),
                    "value": {"metric": metric, "n": v},
                }
            )
    return sigs


def collect_cmd():
    if not SIGNALS_CMD:
        return []
    try:
        out = subprocess.run(
            SIGNALS_CMD, shell=True, capture_output=True, text=True, timeout=10
        ).stdout
        data = json.loads(out)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_bundle():
    signals = []
    signals += collect_wifi()
    signals += collect_environ()
    signals += collect_cmd()
    return {
        "schema": "wavebeast.scanbundle",
        "v": 1,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "client": {"id": "wavebeast-node", "app": "node", "app_v": VERSION},
        "scan_mode": "auto",
        "signals": signals,
    }


def send(bundle, endpoint="snapshot"):
    req = urllib.request.Request(
        f"{SITE}/api/{endpoint}",
        data=json.dumps(bundle).encode(),
        headers={"Content-Type": "application/json", "X-WB-Node-Token": TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.getcode(), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def stamp(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch)) if epoch else None


def heartbeat(health):
    return send(
        {
            "client": {"id": "wavebeast-node", "app": "node", "app_v": VERSION},
            "health": health,
        },
        "node/check-in",
    )


def wait_with_heartbeats(until, health):
    # This deliberately does not collect sensors or submit snapshots.
    health["next_attempt_at"] = stamp(until)
    while time.time() < until:
        heartbeat(health)
        time.sleep(max(0, min(120, until - time.time())))


def main():
    if not TOKEN:
        print(
            "WB_NODE_TOKEN is required (create a node in your profile)", file=sys.stderr
        )
        sys.exit(2)
    once = bool(os.environ.get("WB_ONCE"))
    health = {
        "heartbeat_sec": 120,
        "mode": "auto",
        "failures": 0,
        "error": "",
        "sensors": [
            {
                "name": "wifi",
                "status": "configured" if shutil.which("nmcli") else "unavailable",
            }
        ],
    }
    if ENVIRON_URL:
        health["sensors"].append({"name": "environment", "status": "configured"})
    if SIGNALS_CMD:
        health["sensors"].append({"name": "custom", "status": "configured"})
    try:
        last = float(STATE.read_text())
    except (OSError, ValueError):
        last = 0
    health["last_attempt_at"] = stamp(last)
    health["next_attempt_at"] = stamp(max(time.time(), last + INTERVAL))
    code, update = heartbeat(health)
    print(
        f"WaveBeast listener {VERSION}; passive interval {INTERVAL}s; heartbeat 120s",
        flush=True,
    )
    if update.get("update_available"):
        print(
            "Update available: https://wavebeasts.com/download/wavebeast-node.py",
            flush=True,
        )
    while True:
        wait_with_heartbeats(last + INTERVAL, health)
        STATE.parent.mkdir(parents=True, exist_ok=True)
        last = time.time()
        temp = STATE.with_suffix(".tmp")
        temp.write_text(str(last))
        temp.replace(STATE)
        health["last_attempt_at"] = stamp(last)
        bundle = build_bundle()
        health["sensors"] = [
            {"name": k[:40], "status": "available"}
            for k in sorted(
                {
                    s.get("kind")
                    for s in bundle["signals"]
                    if isinstance(s, dict) and isinstance(s.get("kind"), str)
                }
            )[:24]
        ]
        code, resp = send(bundle)
        n = len(bundle["signals"])
        if code == 200:
            print(
                f"[{time.strftime('%H:%M:%S')}] {n} signals -> {resp.get('outcome')}: {resp.get('detail','')}"
            )
            wait = int(resp.get("next_snapshot_in", INTERVAL))
        elif code == 429:
            wait = int(resp.get("retry_after", INTERVAL))
            print(f"[{time.strftime('%H:%M:%S')}] rate limited, retry in {wait}s")
        else:
            print(
                f"[{time.strftime('%H:%M:%S')}] send failed ({code})", file=sys.stderr
            )
            wait = INTERVAL
        health["error"] = (
            ""
            if code in (200, 429)
            else (
                "auth"
                if code == 403
                else (
                    "update_required"
                    if code == 426
                    else "connection" if code == 0 else "server"
                )
            )
        )
        health["failures"] = health["failures"] + 1 if health["error"] else 0
        health["next_attempt_at"] = stamp(time.time() + max(INTERVAL, wait))
        heartbeat(health)
        if once:
            return
        wait_with_heartbeats(time.time() + max(INTERVAL, wait), health)


if __name__ == "__main__":
    main()
