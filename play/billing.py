"""Stripe subscription helpers. $5/mo or annual; the webhook drives Wallet.subscribed, which gates the
paid features. Test-mode keys today; the same code works in live mode when the prod keys are set.

When settings.STRIPE_MANAGED_PAYMENTS is on, Checkout runs in Managed Payments mode (Stripe is the
merchant of record and calculates/remits tax) — that adds managed_payments[enabled]=true and requires the
STRIPE_PREVIEW_VERSION API version + an eligible tax_code on the product."""
import stripe
from django.conf import settings

ACTIVE = {"active", "trialing"}


def _init():
    stripe.api_key = settings.STRIPE_SECRET_KEY


def _managed():
    return bool(settings.STRIPE_MANAGED_PAYMENTS)


def _req_opts():
    """Per-request options: pin the preview API version for Managed Payments calls only."""
    return {"stripe_version": settings.STRIPE_PREVIEW_VERSION} if _managed() else {}


def price_id(plan):
    return settings.STRIPE_PRICE_ANNUAL if plan == "annual" else settings.STRIPE_PRICE_MONTHLY


def ensure_product_tax_code(price=None):
    """Managed Payments requires an eligible tax_code on the product. Idempotently set it on the product
    behind our monthly price (both prices share the same product). Returns the product id, or None."""
    _init()
    pid = price or settings.STRIPE_PRICE_MONTHLY
    if not pid:
        return None
    pr = stripe.Price.retrieve(pid, expand=["product"])
    prod = pr.product
    prod_id = prod if isinstance(prod, str) else prod.id
    current = None if isinstance(prod, str) else getattr(prod, "tax_code", None)
    if current != settings.STRIPE_TAX_CODE:
        stripe.Product.modify(prod_id, tax_code=settings.STRIPE_TAX_CODE)
    return prod_id


def ensure_customer(wallet, user):
    _init()
    if wallet.stripe_customer_id:
        # A stored id from a different mode (test↔live) or a deleted customer won't exist under the
        # current key. Verify it; recreate if it's gone rather than failing checkout.
        try:
            c = stripe.Customer.retrieve(wallet.stripe_customer_id)
            if not getattr(c, "deleted", False):
                return wallet.stripe_customer_id
        except stripe.error.InvalidRequestError:
            pass  # No such customer → fall through and make a fresh one
    c = stripe.Customer.create(metadata={"user_id": str(user.id), "username": user.username})
    wallet.stripe_customer_id = c.id
    wallet.save(update_fields=["stripe_customer_id"])
    return c.id


def checkout_url(wallet, user, plan, success_url, cancel_url):
    _init()
    cust = ensure_customer(wallet, user)
    params = dict(
        mode="subscription",
        customer=cust,
        line_items=[{"price": price_id(plan), "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        subscription_data={"metadata": {"user_id": str(user.id)}},
    )
    if _managed():
        # Stripe becomes merchant of record and handles tax; product must carry an eligible tax_code.
        ensure_product_tax_code()
        params["managed_payments"] = {"enabled": True}
    sess = stripe.checkout.Session.create(**params, **_req_opts())
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

    # construct_event returns a StripeObject, whose .get() raises in stripe-python 15.x — normalize to a
    # plain dict so attribute access is uniform (tests pass a dict; the live webhook passes a StripeObject).
    if not isinstance(event, dict):
        event = event.to_dict()  # StripeObject -> fully nested plain dict (data/object become dicts too)
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
