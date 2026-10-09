"""In-app sign-in for the Android app, Android App Links, and account deletion.

Flow: the app generates a `state` nonce and opens /app/connect?state=&device= in a Custom Tab. After
Clerk sign-in the user approves connecting the device; we mint an `app` node plus a one-time LinkCode
and redirect to /app/callback?code=&state= (an Android App Link, so the installed app intercepts it).
The app then POSTs the code + state to /api/app/link/exchange through its engine and receives the
node token. The token never appears in a URL.
"""
import json
import logging
import re
import secrets
from datetime import timedelta

import requests
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from .names import player_name
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import billing as billing_mod
from .models import LinkCode, Node, TradeOffer, Wallet

log = logging.getLogger(__name__)

PLAY_URL = "https://play.google.com/store/apps/details?id=net.wavebeasts.app"
STATE_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
EXCHANGE_RATE_LIMIT = 20  # per IP per minute
DEVICE_DEFAULT = "Android phone"


def _site():
    return settings.SITE_URL.rstrip("/")


def _state(request):
    state = request.GET.get("state", "")
    return state if STATE_RE.fullmatch(state) else None


def _device(request):
    return (request.GET.get("device") or "").strip()[:64] or DEVICE_DEFAULT


def _display_name(user):
    return player_name(user)


@login_required
def connect(request):
    from .views import _node_limit_reached, _wallet
    state = _state(request)
    if state is None:
        return HttpResponseBadRequest("missing or invalid state")
    device = _device(request)
    context = {"nav": "", "device": device, "account_name": _display_name(request.user),
               "state": state, "msg": ""}
    if request.method == "POST":
        msg = _node_limit_reached(request.user)
        if msg:
            context["msg"] = msg
            return render(request, "app_connect.html", context, status=409)
        with transaction.atomic():
            node = Node.objects.create(user=request.user, name=device, kind="app")
            wallet = _wallet(request.user)
            if not wallet.onboarded:
                wallet.onboarded = True
                wallet.save(update_fields=["onboarded"])
            code = LinkCode.objects.create(node=node, state=state,
                                           expires_at=timezone.now() + timedelta(seconds=LinkCode.TTL_SEC))
        return redirect(f"{_site()}/app/callback?code={code.code}&state={state}")
    return render(request, "app_connect.html", context)


@require_GET
def callback(request):
    """Shown only when Android did not intercept the App Link (no app, or link not yet verified)."""
    code = request.GET.get("code", "")
    state = request.GET.get("state", "")
    ok = bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)) and STATE_RE.fullmatch(state) is not None
    deep_link = f"wavebeast://link?code={code}&state={state}" if ok else ""
    response = render(request, "app_callback.html", {"nav": "", "deep_link": deep_link, "play_url": PLAY_URL,
                                                    "ttl_min": LinkCode.TTL_SEC // 60}, status=200 if ok else 400)
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")) or "unknown"


def _json(request):
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _private(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@csrf_exempt
@require_POST
def exchange(request):
    key = f"link-exchange:{_client_ip(request)}"
    cache.add(key, 0, 60)
    if cache.incr(key) > EXCHANGE_RATE_LIMIT:
        return _private({"error": "rate_limited"}, 429)
    body = _json(request)
    if body is None:
        return _private({"error": "invalid_code"}, 400)
    code, state = str(body.get("code") or ""), str(body.get("state") or "")
    if not code or not state:
        return _private({"error": "invalid_code"}, 400)
    with transaction.atomic():
        link = LinkCode.objects.select_for_update().select_related("node").filter(code=code).first()
        if link is None or link.used_at is not None or not secrets.compare_digest(link.state, state):
            return _private({"error": "invalid_code"}, 400)
        if link.is_expired():
            return _private({"error": "expired"}, 410)
        link.used_at = timezone.now()
        link.save(update_fields=["used_at"])
        node = link.node
    return _private({"ok": True, "token": node.token, "site": _site(),
                     "node": {"id": node.id, "name": node.name, "kind": node.kind}})


@require_GET
def assetlinks(request):
    fingerprints = [f.strip().upper() for f in settings.ANDROID_CERT_SHA256.split(",") if f.strip()]
    statements = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": settings.ANDROID_PACKAGE,
                   "sha256_cert_fingerprints": fingerprints},
    }]
    response = HttpResponse(json.dumps(statements), content_type="application/json")
    response["Cache-Control"] = "public, max-age=3600"
    return response


# ---- account deletion ----------------------------------------------------------------------------

def _cancel_stripe(wallet):
    if not wallet.stripe_customer_id or not settings.STRIPE_SECRET_KEY:
        return
    try:
        import stripe
        billing_mod._init()
        for sub in stripe.Subscription.list(customer=wallet.stripe_customer_id, status="all", limit=20).auto_paging_iter():
            if sub.get("status") in ("active", "trialing", "past_due", "unpaid"):
                stripe.Subscription.cancel(sub["id"])
    except Exception:  # noqa: BLE001 - never block deletion on the payment processor
        log.exception("stripe cancellation failed during account deletion")


def _delete_clerk_user(username):
    key = getattr(settings, "CLERK_SECRET_KEY", "")
    if not key or not username.startswith("user_"):
        return
    try:
        requests.delete(f"https://api.clerk.com/v1/users/{username}",
                        headers={"Authorization": f"Bearer {key}"}, timeout=8).raise_for_status()
    except requests.RequestException:
        log.exception("clerk user deletion failed")


def delete_account(user):
    """Cancel billing, refund escrow held in the user's open offers, remove the identity provider
    record, then delete the Django user (FKs cascade: wallet, nodes, beasts, listings, offers, ladder,
    battles, activity). Offers *to* this user's listings refund their offerers first."""
    from .views import _refund_offer
    with transaction.atomic():
        wallet = Wallet.objects.select_for_update().filter(user=user).first()
        if wallet:
            _cancel_stripe(wallet)
        open_offers = TradeOffer.objects.select_for_update().filter(status="pending").filter(
            Q(from_user=user) | Q(listing__user=user)).select_related("from_user")
        for offer in open_offers:
            if offer.from_user_id != user.id:
                _refund_offer(offer)
            offer.status = "declined"
            offer.save(update_fields=["status"])
        username = user.username
        user.delete()
    _delete_clerk_user(username)


@csrf_exempt
@require_POST
def api_delete(request):
    node = Node.objects.select_related("user").filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return _private({"error": "bad node token"}, 403)
    if node.kind != "app":
        # Only the phone that signed in may erase the account; a leaked listener token must not be enough.
        return _private({"error": "app_node_required"}, 403)
    body = _json(request)
    if not body or body.get("confirm") != "DELETE":
        return _private({"error": "confirm_required"}, 400)
    delete_account(node.user)
    return _private({"ok": True})


@login_required
def web_delete(request):
    if request.method == "POST":
        if (request.POST.get("confirm") or "").strip() != "DELETE":
            return render(request, "account_delete.html", {"nav": "", "msg": "Type DELETE to confirm."}, status=400)
        user = request.user
        logout(request)
        delete_account(user)
        return redirect("/")
    return render(request, "account_delete.html", {"nav": "", "msg": ""})
