#!/usr/bin/env python3
"""WaveBeast listener node — the slim client (stdlib only; NOT the full engine).

It assembles a ScanBundle from whatever local sensors it can read and POSTs it to your account on the
site (default wavebeasts.com) on a timer, honouring the site's rate limit. Run one on a phone, a Pi,
EDI/Bishop, or any PC signed in with a node token.

Config via env:
  WB_SITE          site base URL            (default https://wavebeasts.com)
  WB_NODE_TOKEN    node token from your profile   (required)
  WB_INTERVAL      fallback seconds between snapshots (default 300; the site's reply overrides)
  WB_ENVIRON_URL   optional JSON endpoint of environment scalars (e.g. Bishop enviro) to fold in
  WB_SIGNALS_CMD   optional command whose stdout is a JSON array of extra signals
  WB_ONCE          if set, send a single snapshot and exit
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

SITE = os.environ.get("WB_SITE", "https://wavebeasts.com").rstrip("/")
TOKEN = os.environ.get("WB_NODE_TOKEN", "")
INTERVAL = int(os.environ.get("WB_INTERVAL", "300"))
ENVIRON_URL = os.environ.get("WB_ENVIRON_URL", "")
SIGNALS_CMD = os.environ.get("WB_SIGNALS_CMD", "")


def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def collect_wifi():
    """Nearby APs via nmcli (common on Linux/Pi). Silent if unavailable."""
    if not shutil.which("nmcli"):
        return []
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL", "dev", "wifi"],
                             capture_output=True, text=True, timeout=8).stdout
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
        sigs.append({"kind": "wifi", "id": bssid, "strength": clamp01(pct / 100.0),
                     "value": {"ssid": ssid, "bssid": bssid, "rssi": rssi}})
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
    mapping = [("temperature", "temp_c", 40), ("humidity", "humidity_pct", 100),
               ("pressure", "pressure_hpa", 1100), ("lux", "lux", 1000), ("noise", "sound_db", 100)]
    for key, metric, norm in mapping:
        v = m.get(key)
        if isinstance(v, (int, float)):
            sigs.append({"kind": "scalar", "strength": clamp01(v / norm),
                         "value": {"metric": metric, "n": v}})
    return sigs


def collect_cmd():
    if not SIGNALS_CMD:
        return []
    try:
        out = subprocess.run(SIGNALS_CMD, shell=True, capture_output=True, text=True, timeout=10).stdout
        data = json.loads(out)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def build_bundle():
    signals = []
    signals += collect_wifi()
    signals += collect_environ()
    signals += collect_cmd()
    return {"schema": "wavebeast.scanbundle", "v": 1,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "client": {"id": "wavebeast-node", "app": "node"},
            "signals": signals}


def send(bundle):
    req = urllib.request.Request(
        f"{SITE}/api/snapshot", data=json.dumps(bundle).encode(),
        headers={"Content-Type": "application/json", "X-WB-Node-Token": TOKEN}, method="POST")
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


def main():
    if not TOKEN:
        print("WB_NODE_TOKEN is required (create a node in your profile)", file=sys.stderr)
        sys.exit(2)
    once = bool(os.environ.get("WB_ONCE"))
    while True:
        bundle = build_bundle()
        code, resp = send(bundle)
        n = len(bundle["signals"])
        if code == 200:
            print(f"[{time.strftime('%H:%M:%S')}] {n} signals -> {resp.get('outcome')}: {resp.get('detail','')}")
            wait = int(resp.get("next_snapshot_in", INTERVAL))
        elif code == 429:
            wait = int(resp.get("retry_after", INTERVAL))
            print(f"[{time.strftime('%H:%M:%S')}] rate limited, retry in {wait}s")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] send failed ({code}): {resp.get('error','')}", file=sys.stderr)
            wait = INTERVAL
        if once:
            return
        time.sleep(max(5, wait))


if __name__ == "__main__":
    main()
