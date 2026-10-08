"""Atomic, account-scoped receipts. No raw sensor values or credentials are logged."""

from contextvars import ContextVar
from functools import wraps
from inspect import signature
import json
from django.db import transaction
from .models import ActivityEntry, Wallet, Node, TradeOffer

_active = ContextVar("activity_users", default=frozenset())


def balances(user):
    wallet = Wallet.objects.get(user=user)
    return {
        "shards": wallet.shards,
        "cores": wallet.cores,
        **{"item:" + k: v for k, v in user.items.values_list("item_id", "qty")},
    }


def receipt(user, kind, summary, before, source="", beast_key=""):
    after = balances(user)
    changes = {
        k: after.get(k, 0) - before.get(k, 0)
        for k in before.keys() | after.keys()
        if after.get(k, 0) != before.get(k, 0)
    }
    return ActivityEntry.objects.create(
        user=user,
        kind=kind,
        summary=str(summary)[:300],
        source=str(source)[:128],
        beast_key=str(beast_key)[:64],
        changes=changes,
        balances=after,
    )


def audit(kind, label):
    """Wrap one gameplay operation; nested helpers produce a single receipt per account."""

    def decorate(fn):
        sig = signature(fn)

        @wraps(fn)
        def wrapped(*args, **kwargs):
            bound = sig.bind(*args, **kwargs).arguments
            request = bound.get("request")
            node = bound.get("node")
            user = bound.get("user")
            if request is not None:
                token = request.headers.get("X-WB-Node-Token", "")
                if token:
                    node = (
                        Node.objects.select_related("user").filter(token=token).first()
                    )
                    user = node.user if node else None
                elif request.user.is_authenticated:
                    user = request.user
            if node is not None:
                user = node.user
            if "offer" in bound:
                user = bound["offer"].from_user
            users = {u.pk: u for u in [user] if u is not None}
            if fn.__name__ == "trade_accept" and user:
                offer = TradeOffer.objects.filter(
                    pk=bound.get("offer_id"), listing__user=user
                ).first()
                if offer:
                    for other in TradeOffer.objects.filter(
                        listing=offer.listing, status="pending"
                    ).select_related("from_user"):
                        users[other.from_user_id] = other.from_user
            if fn.__name__ == "resolve_match":
                users = {bound[k].user.pk: bound[k].user for k in ["a", "b"]}
            users = {k: v for k, v in users.items() if k not in _active.get()}
            if not users:
                return fn(*args, **kwargs)
            with transaction.atomic():
                for uid in sorted(users):
                    Wallet.objects.get_or_create(user=users[uid])
                list(
                    Wallet.objects.select_for_update()
                    .filter(user_id__in=users)
                    .order_by("user_id")
                )
                before = {uid: balances(u) for uid, u in users.items()}
                beasts = {
                    uid: dict(u.beasts.filter(status="owned").values_list("pk", "name"))
                    for uid, u in users.items()
                }
                token = _active.set(_active.get() | users.keys())
                try:
                    result = fn(*args, **kwargs)
                finally:
                    _active.reset(token)
                payload = {}
                if hasattr(result, "content") and result.get(
                    "Content-Type", ""
                ).startswith("application/json"):
                    try:
                        payload = json.loads(result.content)
                    except (ValueError, TypeError):
                        pass
                elif isinstance(result, tuple):
                    payload = next((r for r in result if isinstance(r, dict)), {})
                successful = getattr(
                    result, "status_code", 200
                ) < 400 and not payload.get("error")
                for uid, u in users.items():
                    after_beasts = dict(
                        u.beasts.filter(status="owned").values_list("pk", "name")
                    )
                    changed = before[uid] != balances(u) or beasts[uid] != after_beasts
                    event = successful and (
                        payload.get("accepted")
                        or payload.get("dismissed")
                        or payload.get("caught")
                        or payload.get("levels_gained")
                        or payload.get("events")
                        or (kind == "buddy" and payload.get("result"))
                        or (kind == "battle" and result is not None)
                    )
                    if changed or event:
                        detail = (
                            payload.get("message") or payload.get("detail") or label
                        )
                        if fn.__name__ == "trade_accept" and uid not in (
                            user.pk,
                            offer.from_user_id,
                        ):
                            detail = "Trade escrow refunded"
                        if kind == "shop":
                            detail = f"Bought {bound.get('qty',1)} {bound.get('item_id','item')}"
                        if request is not None and fn.__name__ == "battle_fight":
                            battle = request.session.get("last_battle", {})
                            if battle.get("error") and not changed:
                                continue
                            detail = "Battle: " + battle.get("outcome", "finished")
                        entry = receipt(
                            u,
                            kind,
                            detail,
                            before[uid],
                            node.name if node else "Account",
                        )
                        added = set(after_beasts) - set(beasts[uid])
                        removed = set(beasts[uid]) - set(after_beasts)
                        if added or removed:
                            entry.changes.update({"beasts": len(added) - len(removed)})
                            entry.summary += "".join(
                                " · " + prefix + ": " + ", ".join(names[i] for i in ids)
                                for prefix, ids, names in [
                                    ("Joined", added, after_beasts),
                                    ("Departed", removed, beasts[uid]),
                                ]
                                if ids
                            )
                            entry.summary = entry.summary[:300]
                            entry.save(update_fields=["changes", "summary"])
                return result

        return wrapped

    return decorate
