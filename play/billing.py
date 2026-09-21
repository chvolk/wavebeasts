"""Stripe subscription helpers. $5/mo or annual; the webhook drives Wallet.subscribed, which gates the
paid features. Test-mode keys today; the same code works in live mode when the prod keys are set."""
import stripe
from django.conf import settings

ACTIVE = {"active", "trialing"}


def _init():
    stripe.api_key = settings.STRIPE_SECRET_KEY


def price_id(plan):
    return settings.STRIPE_PRICE_ANNUAL if plan == "annual" else settings.STRIPE_PRICE_MONTHLY


def ensure_customer(wallet, user):
    _init()
    if wallet.stripe_customer_id:
        return wallet.stripe_customer_id
    c = stripe.Customer.create(metadata={"user_id": str(user.id), "username": user.username})
    wallet.stripe_customer_id = c.id
    wallet.save(update_fields=["stripe_customer_id"])
    return c.id


def checkout_url(wallet, user, plan, success_url, cancel_url):
    _init()
    cust = ensure_customer(wallet, user)
    sess = stripe.checkout.Session.create(
        mode="subscription",
        customer=cust,
        line_items=[{"price": price_id(plan), "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        subscription_data={"metadata": {"user_id": str(user.id)}},
    )
    return sess.url


def portal_url(wallet, return_url):
    _init()
    if not wallet.stripe_customer_id:
        return None
    s = stripe.billing_portal.Session.create(customer=wallet.stripe_customer_id, return_url=return_url)
    return s.url


def apply_event(event):
    """Update the matching wallet from a Stripe webhook event. Returns True if a wallet was updated."""
    from .models import Wallet

    etype = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    cust = obj.get("customer")
    if not cust:
        return False
    w = Wallet.objects.filter(stripe_customer_id=cust).first()
    if not w:
        return False
    if etype.startswith("customer.subscription."):
        status = obj.get("status", "")
        w.subscription_status = status
        w.subscribed = status in ACTIVE
        w.save(update_fields=["subscription_status", "subscribed"])
        return True
    if etype == "checkout.session.completed":
        w.subscription_status = "active"
        w.subscribed = True
        w.save(update_fields=["subscription_status", "subscribed"])
        return True
    return False
