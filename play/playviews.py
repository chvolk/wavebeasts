"""HTTP surface for Google Play Billing: the app verifies purchases, asks what it may offer, and Google
pushes subscription changes (Real-time Developer Notifications over Pub/Sub)."""
import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import playbilling
from .models import Node

log = logging.getLogger(__name__)
VERIFY_RATE_LIMIT = 30  # per IP per minute


def _private(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")) or "unknown"


def _node(request):
    return Node.objects.select_related("user").filter(token=request.headers.get("X-WB-Node-Token", "")).first()


def _json(request):
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


@csrf_exempt
@require_POST
def verify(request):
    """The Android app posts a fresh purchase token (after checkout, and again on every launch for the
    cached purchase). Only the phone that signed in (an `app` node) may bind a purchase to the account."""
    from .views import _wallet, account_summary
    key = f"play-verify:{_client_ip(request)}"
    cache.add(key, 0, 60)
    if cache.incr(key) > VERIFY_RATE_LIMIT:
        return _private({"error": "rate_limited"}, 429)
    node = _node(request)
    if not node:
        return _private({"error": "bad node token"}, 403)
    if node.kind != "app":
        return _private({"error": "app_node_required"}, 403)
    body = _json(request)
    if body is None:
        return _private({"error": "invalid_token"}, 400)
    wallet = _wallet(node.user)
    ok, payload, status = playbilling.verify_and_apply(wallet, str(body.get("purchase_token") or ""),
                                                       str(body.get("product_id") or "") or None)
    if not ok:
        return _private(payload, status)
    wallet.refresh_from_db()
    return _private({"ok": True, "account": account_summary(node.user, wallet)})


@require_GET
def offers(request):
    """What the calling client may offer. The Play build never sees web purchase paths (Play policy)."""
    from .views import _wallet
    node = _node(request)
    if not node:
        return _private({"error": "bad node token"}, 403)
    channel = request.GET.get("channel", "")
    w = _wallet(node.user)
    payload = {
        "provider": w.billing_provider, "subscribed": w.subscribed,
        "status": w.subscription_status or ("active" if w.subscribed else "free"),
        "renews_at": w.play_expires_at.isoformat() if w.billing_provider == "play" and w.play_expires_at else None,
        "auto_renewing": bool(w.play_auto_renewing) if w.billing_provider == "play" else False,
        # The app passes this to launchBillingFlow(setObfuscatedAccountId) so verify can bind the purchase.
        "obfuscated_id": playbilling.obfuscated_id(node.user),
        "play": {"product_id": settings.PLAY_PRODUCT_ID, "base_plans": list(settings.PLAY_BASE_PLANS),
                 "package": settings.PLAY_PACKAGE_NAME, "manage_url": playbilling.manage_url(),
                 "obfuscated_account_id": playbilling.obfuscated_id(node.user)},
    }
    if w.billing_provider == "stripe":
        payload["managed_elsewhere"] = True
    if channel != "play":
        payload["web"] = {"billing_url": settings.SITE_URL.rstrip("/") + "/billing/",
                          "portal_available": bool(w.stripe_customer_id)}
    return _private(payload)


@csrf_exempt
@require_POST
def webhook(request):
    """Pub/Sub push endpoint for Play RTDN. Anything other than an auth failure answers 2xx so Pub/Sub
    does not retry forever; outcomes are logged."""
    if not playbilling.verify_push_token(request.headers.get("Authorization", "")):
        return HttpResponse("unauthorized", status=401)
    note = playbilling.decode_push(request.body)
    if note is None:
        log.warning("play rtdn: unparseable push body")
        return HttpResponse(status=204)
    try:
        outcome = playbilling.handle_notification(note)
    except Exception:  # noqa: BLE001 - never turn a bug into a retry storm
        log.exception("play rtdn: handler failed")
        outcome = "error"
    log.info("play rtdn: %s", outcome)
    return JsonResponse({"ok": True, "outcome": outcome})
