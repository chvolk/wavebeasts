"""Google Play Billing: verify Android subscription purchases server-side and keep Wallet entitlement in
sync with Google's subscription state (purchase verification on the app's request, Real-time Developer
Notifications via Pub/Sub, and a daily reconcile as a safety net).

An account has one billing provider at a time: `Wallet.billing_provider` is "stripe" (website), "play"
(Android app) or "" (free). A purchase is bound to the signed-in account through the
`obfuscatedExternalAccountId` the app attaches at checkout (an HMAC of the user id).
"""
import base64
import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

log = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/androidpublisher"
API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
MANAGE_URL = "https://play.google.com/store/account/subscriptions?sku={product}&package={package}"

# subscriptionsv2 states -> (subscribed, status). CANCELED is handled separately (access until expiry).
STATES = {
    "SUBSCRIPTION_STATE_ACTIVE": (True, "active"),
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": (True, "past_due"),
    "SUBSCRIPTION_STATE_ON_HOLD": (False, "past_due"),
    "SUBSCRIPTION_STATE_PAUSED": (False, "paused"),
    "SUBSCRIPTION_STATE_PENDING": (False, "pending"),
    "SUBSCRIPTION_STATE_EXPIRED": (False, "expired"),
}

_session = None


def configured():
    return bool(settings.PLAY_SERVICE_ACCOUNT_JSON)


def manage_url():
    return MANAGE_URL.format(product=settings.PLAY_PRODUCT_ID, package=settings.PLAY_PACKAGE_NAME)


def obfuscated_id(user):
    """Stable, non-reversible account id the app passes to Play as obfuscatedExternalAccountId."""
    return hmac.new(settings.SECRET_KEY.encode(), str(user.id).encode(), hashlib.sha256).hexdigest()[:64]


def _credentials():
    from google.oauth2 import service_account
    raw = settings.PLAY_SERVICE_ACCOUNT_JSON.strip()
    if not raw.startswith("{"):
        raw = base64.b64decode(raw).decode("utf-8")
    return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[SCOPE])


def _http():
    global _session
    if _session is None:
        from google.auth.transport.requests import AuthorizedSession
        _session = AuthorizedSession(_credentials())
    return _session


class PlayError(Exception):
    def __init__(self, error, status=502):
        super().__init__(error)
        self.error, self.status = error, status


def fetch_subscription(token):
    """GET purchases.subscriptionsv2 for a purchase token. Returns the resource dict."""
    if not configured():
        raise PlayError("play_not_configured", 503)
    r = _http().get(f"{API}/{settings.PLAY_PACKAGE_NAME}/purchases/subscriptionsv2/tokens/{token}", timeout=10)
    if r.status_code == 404 or r.status_code == 400:
        raise PlayError("invalid_token", 400)
    if r.status_code != 200:
        log.warning("play subscriptionsv2 %s: %s", r.status_code, r.text[:300])
        raise PlayError("play_unavailable", 502)
    return r.json()


def acknowledge(token, product_id):
    """Acknowledge a purchase (legacy v3 endpoint; v2 has no acknowledge). Unacknowledged purchases are
    refunded by Google after three days."""
    if not configured():
        return False
    r = _http().post(f"{API}/{settings.PLAY_PACKAGE_NAME}/purchases/subscriptions/{product_id}/tokens/{token}:acknowledge",
                     json={}, timeout=10)
    if r.status_code // 100 != 2:
        log.warning("play acknowledge %s: %s", r.status_code, r.text[:300])
        return False
    return True


def _line_item(sub):
    items = sub.get("lineItems") or []
    return items[0] if items else {}


def apply_state(wallet, token, sub):
    """Map a subscriptionsv2 resource onto the wallet (caller holds the row lock and saves)."""
    item = _line_item(sub)
    expiry = parse_datetime(item.get("expiryTime") or "") if item.get("expiryTime") else None
    state = sub.get("subscriptionState", "")
    now = timezone.now()
    if state == "SUBSCRIPTION_STATE_CANCELED":
        subscribed, status = (expiry is not None and expiry > now), "canceled"
        if not subscribed:
            status = "expired"
    else:
        subscribed, status = STATES.get(state, (False, "expired"))
        if subscribed and expiry is not None and expiry <= now:
            subscribed, status = False, "expired"
    wallet.play_purchase_token = token
    wallet.play_product_id = (item.get("productId") or wallet.play_product_id or "")[:64]
    wallet.play_base_plan = ((item.get("offerDetails") or {}).get("basePlanId") or "")[:32]
    wallet.play_expires_at = expiry
    wallet.play_auto_renewing = bool((item.get("autoRenewingPlan") or {}).get("autoRenewEnabled")) and state != "SUBSCRIPTION_STATE_CANCELED"
    if not wallet.play_linked_at:
        wallet.play_linked_at = now
    wallet.subscribed = subscribed
    wallet.subscription_status = status
    if subscribed:
        wallet.billing_provider = "play"
    elif wallet.billing_provider == "play":
        wallet.billing_provider = ""
    return subscribed, status


PLAY_FIELDS = ["play_purchase_token", "play_product_id", "play_base_plan", "play_expires_at", "play_auto_renewing",
               "play_linked_at", "play_obfuscated_id", "subscribed", "subscription_status", "billing_provider"]


def verify_and_apply(wallet, token, product_id=None, refresh=False):
    """Verify a purchase token with Google and apply it to the wallet.
    Returns (ok, payload, status). `refresh=True` skips the Stripe-exclusivity refusal for RTDN/reconcile
    updates of a token this wallet already holds."""
    from .models import Wallet
    token = (token or "").strip()
    if not token or len(token) > 512:
        return False, {"error": "invalid_token"}, 400
    try:
        sub = fetch_subscription(token)
    except PlayError as e:
        return False, {"error": e.error}, e.status
    except Exception:  # noqa: BLE001 - network/auth failure talking to Google
        log.exception("play verification failed")
        return False, {"error": "play_unavailable"}, 502
    with transaction.atomic():
        w = Wallet.objects.select_for_update().select_related("user").get(pk=wallet.pk)
        if not refresh and w.subscribed and w.billing_provider != "play":
            # Premium already comes from somewhere else (Stripe, or a grandfathered/comped account).
            # Applying a Play purchase on top would double-bill or waste the player's money.
            if w.billing_provider == "stripe" or w.stripe_customer_id:
                return False, {"error": "stripe_active"}, 409
            return False, {"error": "already_premium"}, 409
        if Wallet.objects.filter(play_purchase_token=token).exclude(pk=w.pk).exists():
            return False, {"error": "token_in_use"}, 409
        expected = obfuscated_id(w.user)
        got = (sub.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId")
        if got and not hmac.compare_digest(str(got), expected):
            return False, {"error": "account_mismatch"}, 403
        item = _line_item(sub)
        if product_id and item.get("productId") and item["productId"] != product_id:
            log.info("play product id mismatch: app said %s, google says %s", product_id, item["productId"])
        apply_state(w, token, sub)
        w.play_obfuscated_id = expected
        w.save(update_fields=PLAY_FIELDS)
    if sub.get("acknowledgementState") == "ACKNOWLEDGEMENT_STATE_PENDING" and w.subscribed:
        try:
            acknowledge(token, w.play_product_id or product_id or settings.PLAY_PRODUCT_ID)
        except Exception:  # noqa: BLE001
            log.exception("play acknowledge failed")
    return True, {"subscribed": w.subscribed, "status": w.subscription_status, "renews_at": w.play_expires_at}, 200


def reconcile(limit=200):
    """Re-verify Play subscriptions near their expiry (or past it while still marked subscribed) in
    case a notification was missed. Returns (checked, changed)."""
    from .models import Wallet
    now = timezone.now()
    due = Wallet.objects.exclude(play_purchase_token="").filter(
        Q(play_expires_at__range=(now - timedelta(days=3), now + timedelta(days=3)))
        | Q(subscribed=True, billing_provider="play", play_expires_at__lt=now)
    ).order_by("play_expires_at")[:limit]
    checked = changed = 0
    for w in due:
        before = (w.subscribed, w.subscription_status, w.play_expires_at)
        ok, _, _ = verify_and_apply(w, w.play_purchase_token, refresh=True)
        checked += 1
        if ok:
            w.refresh_from_db()
            if before != (w.subscribed, w.subscription_status, w.play_expires_at):
                changed += 1
    return checked, changed


# ---- Real-time developer notifications (Pub/Sub push) ------------------------------------------

def verify_push_token(authorization):
    """Validate the OIDC token Pub/Sub attaches to push deliveries. Returns True when accepted."""
    expected = settings.PLAY_RTDN_SERVICE_ACCOUNT
    if not expected:
        # Dev without any Play configuration stays open; once a service-account key is configured
        # (production), a missing PLAY_RTDN_SERVICE_ACCOUNT must fail closed rather than accept anyone.
        return not configured()
    if not authorization.startswith("Bearer "):
        return False
    try:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(authorization[7:], g_requests.Request(), audience=settings.PLAY_RTDN_AUDIENCE)
    except Exception:  # noqa: BLE001
        log.warning("play rtdn: push token rejected", exc_info=True)
        return False
    return bool(claims.get("email_verified")) and claims.get("email") == expected


def decode_push(body):
    """Pub/Sub envelope -> the developer notification dict, or None when unparseable."""
    try:
        envelope = json.loads(body.decode("utf-8") or "{}")
        data = (envelope.get("message") or {}).get("data") or ""
        return json.loads(base64.b64decode(data).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def handle_notification(note):
    """Apply a developer notification. Returns a short outcome string for logging/tests."""
    from .models import Wallet
    if not isinstance(note, dict):
        return "ignored"
    if note.get("packageName") and note["packageName"] != settings.PLAY_PACKAGE_NAME:
        return "wrong_package"
    if "testNotification" in note:
        log.info("play rtdn: test notification %s", note["testNotification"])
        return "test"
    sub_note = note.get("subscriptionNotification") or {}
    voided = note.get("voidedPurchaseNotification") or {}
    token = sub_note.get("purchaseToken") or voided.get("purchaseToken")
    if not token:
        return "ignored"
    wallet = Wallet.objects.filter(play_purchase_token=token).first()
    if wallet is None:
        try:
            sub = fetch_subscription(token)
        except PlayError as e:
            return f"unknown_token:{e.error}"
        oid = (sub.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId") or ""
        wallet = Wallet.objects.filter(play_obfuscated_id=oid).first() if oid else None
        if wallet is None:
            log.warning("play rtdn: no wallet for token (type %s)", sub_note.get("notificationType"))
            return "no_wallet"
    ok, payload, _ = verify_and_apply(wallet, token, refresh=True)
    return "applied" if ok else f"failed:{payload.get('error')}"
