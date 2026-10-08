"""Only sensor categories and health metadata are retained, never raw readings."""

from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.conf import settings
from .client_updates import status as update_status

ERRORS = {
    "connection": "Could not reach the host",
    "auth": "Node token rejected",
    "update_required": "Client update required",
    "resolver": "Scan resolver unavailable",
    "invalid": "Invalid scan",
    "server": "Host error",
    "sensor": "No sensor readings available",
}


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        value = parse_datetime(value)
        if value and timezone.is_naive(value):
            value = timezone.make_aware(value)
        return value
    except (ValueError, TypeError, OverflowError):
        return None


def report(node, body):
    now = timezone.now()
    node.last_seen_at = now
    health = body.get("health") if isinstance(body, dict) else None
    if isinstance(health, dict):
        try:
            node.heartbeat_sec = max(
                60, min(1800, int(health.get("heartbeat_sec", 120)))
            )
        except (ValueError, TypeError):
            pass
        if health.get("mode") in ["auto", "manual", "paused", "sleeping"]:
            node.scan_mode = health["mode"]
        value = _date(health.get("next_attempt_at"))
        node.next_attempt_at = (
            value
            if value and now - timedelta(minutes=5) < value < now + timedelta(days=7)
            else None
        )
        value = _date(health.get("last_attempt_at"))
        if (
            value
            and value <= now + timedelta(minutes=2)
            and (not node.last_attempt_at or value > node.last_attempt_at)
        ):
            node.last_attempt_at = value
        sensors = health.get("sensors")
        if isinstance(sensors, list):
            node.sensors = [
                {
                    "name": str(s.get("name", ""))[:40],
                    "status": s.get("status", "unknown"),
                }
                for s in sensors[:24]
                if isinstance(s, dict)
                and s.get("status")
                in ["available", "configured", "unavailable", "unknown"]
            ]
        if "error" in health:
            node.last_error = ERRORS.get(str(health.get("error")), "")
        try:
            node.failures = max(
                0, min(100000, int(health.get("failures", node.failures)))
            )
        except (TypeError, ValueError):
            pass
    node.save(
        update_fields=[
            "last_seen_at",
            "heartbeat_sec",
            "scan_mode",
            "next_attempt_at",
            "last_attempt_at",
            "sensors",
            "last_error",
            "failures",
        ]
    )


def attempt(node, bundle):
    report(node, bundle)
    node.last_attempt_at = timezone.now()
    node.scan_mode = (
        "auto"
        if bundle.get("scan_mode") == "auto" or node.client_app == "wavebeast-node"
        else "manual"
    )
    signals = bundle.get("signals", [])
    kinds = (
        sorted(
            {
                s.get("kind")
                for s in signals[:100]
                if isinstance(s, dict) and isinstance(s.get("kind"), str)
            }
        )
        if isinstance(signals, list)
        else []
    )
    if kinds:
        node.sensors = [{"name": s[:40], "status": "available"} for s in kinds[:24]]
    node.save(update_fields=["last_attempt_at", "scan_mode", "sensors"])


def result(node, error="", wait=None):
    node.last_error = ERRORS.get(error, "")
    node.failures = node.failures + 1 if error else 0
    if wait is not None:
        node.next_attempt_at = timezone.now() + timedelta(seconds=max(0, wait))
    node.save(update_fields=["last_error", "failures", "next_attempt_at"])


def row(node):
    now = timezone.now()
    update = update_status(node)
    last = node.last_seen_at or node.last_snapshot_at
    stale = bool(
        node.heartbeat_sec
        and last
        and (now - last).total_seconds() > max(300, node.heartbeat_sec * 3)
    )
    if update.get("managed"):
        state = "browser / manual"
    elif stale:
        state = "offline"
    elif update.get("update_required"):
        state = "update required"
    elif node.last_error:
        state = "error"
    elif not node.heartbeat_sec:
        state = "heartbeat unavailable"
    elif node.scan_mode in ["sleeping", "paused"]:
        state = node.scan_mode
    elif (
        node.scan_mode == "auto" and node.next_attempt_at and node.next_attempt_at > now
    ):
        state = "waiting for next scan"
    elif node.seconds_until_ready() > 0:
        state = "cooldown"
    else:
        state = "ready" if node.scan_mode == "auto" else "manual / auto off"
    iso = lambda d: d.isoformat() if d else None
    return {
        "id": node.pk,
        "name": node.name,
        "state": state,
        "last_seen_at": iso(last),
        "last_success_at": iso(node.last_snapshot_at),
        "last_attempt_at": iso(node.last_attempt_at),
        "next_attempt_at": iso(node.next_attempt_at),
        "failures": node.failures,
        "last_error": node.last_error,
        "sensors": node.sensors,
        "mode": node.scan_mode,
        "host": settings.SITE_URL.rstrip("/"),
        "version": node.client_version or "Not reported",
        "update": update,
        "heartbeat_sec": node.heartbeat_sec,
    }
