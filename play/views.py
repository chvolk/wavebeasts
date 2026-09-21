import hashlib
import json
import random
import secrets

import requests

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache

from . import billing as billing_mod, buddy as buddymod, clerkauth, ladder, resolver
from .models import (AsyncBattle, Buddy, BattleRecord, InventoryItem, LadderTeam, Node,
                     OwnedBeast, Snapshot, TradeListing, TradeOffer, Wallet)

DRIVE_MULT = {"spark_drive": 1.0, "pulse_drive": 1.5, "surge_drive": 2.5, "nova_drive": 4.0}
RARITY_RESIST = {"common": 1.0, "uncommon": 0.85, "rare": 0.65, "epic": 0.45, "legendary": 0.28}
BOOST_COST_CORES = 1
BOOST_DURATION_SEC = 600
GYM_CODES = ["wb-gym-ember", "wb-gym-tide", "wb-gym-stone"]
FREE_NODE_LIMIT = 3     # free accounts get 3 devices (e.g. phone + pi + pc)
PAID_NODE_LIMIT = 12    # a paid account's sensor fleet cap
WILD_TTL_SEC = 86400    # an uncaught wild sighting expires after a day so findings don't stack forever
MAX_UNSEEN_WILD = 100   # hard cap on pending wild sightings per account (oldest culled first)
# Beast health pool (account meta-HP, separate from in-battle stat HP). A fainted (0 HP) beast can't be
# your Buddy scout and can't fight scan-battles until it heals (regen over time, or a Potion).
HP_MAX = 100
HP_REGEN_PER_HOUR = 20.0   # full recovery in ~5h
HP_BATTLE_COST = 40        # HP each party member spends on a scan-battle


def _hp_now(ind):
    """Current health, regenerated over time from the stored (hp, hp_at). Defaults to full."""
    base = ind.get("hp")
    base = HP_MAX if base is None else base
    at = parse_datetime(ind.get("hp_at", "") or "")
    if at:
        hrs = max(0.0, (timezone.now() - at).total_seconds() / 3600.0)
        base = min(HP_MAX, base + hrs * HP_REGEN_PER_HOUR)
    return max(0, min(HP_MAX, int(round(base))))


def _set_hp(beast, val):
    ind = beast.individual_json or {}
    ind["hp"] = max(0, min(HP_MAX, int(val)))
    ind["hp_at"] = timezone.now().isoformat()
    beast.individual_json = ind
    beast.save(update_fields=["individual_json"])


def _wallet(user):
    w, _ = Wallet.objects.get_or_create(user=user)
    return w


def _paid(user):
    """Paid gate for premium features (trade, boosts, buddy, upload). Nodes + snapshots stay free."""
    return _wallet(user).subscribed


# ---- public / auth -------------------------------------------------------------------------------

def landing(request):
    return render(request, "landing.html")


def download(request):
    return render(request, "download.html", {"nav": "download"})


def privacy(request):
    return render(request, "privacy.html", {"nav": ""})


def terms(request):
    return render(request, "terms.html", {"nav": ""})


def docs(request, page="overview"):
    from .wiki import PAGES
    pages = [{"slug": slug, "title": title, "group": group, "url": "/docs/" if slug == "overview" else f"/docs/{slug}/"}
             for slug, title, group in PAGES]
    current = next((p for p in pages if p["slug"] == page), None)
    if current is None:
        raise Http404("No such wiki page")
    index = pages.index(current)
    context = {"nav": "docs", "wiki_pages": pages, "wiki_slug": page, "wiki_title": current["title"],
               "wiki_template": f"wiki/{page}.html", "site_url": settings.SITE_URL.rstrip("/"),
               "wiki_previous": pages[index - 1] if index else None,
               "wiki_next": pages[index + 1] if index + 1 < len(pages) else None}
    if page == "ai-setup":
        context["node_prompt"] = render_to_string("agent-prompts/node.txt", context)
        context["local_prompt"] = render_to_string("agent-prompts/local.txt", context)
    return render(request, "docs.html", context)


@require_GET
def agent_setup_prompt(request, mode):
    if mode not in {"node", "local"}:
        raise Http404("No such setup prompt")
    response = HttpResponse(render_to_string(f"agent-prompts/{mode}.txt", {"site_url": settings.SITE_URL.rstrip("/")}),
                            content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="wavebeasts-{mode}-setup.txt"'
    return response


def node_client(request):
    """Serve the stdlib-only listener-node client script (for curl/wget on any device)."""
    import os
    from django.conf import settings
    from django.http import HttpResponse
    path = os.path.join(settings.BASE_DIR, "play", "files", "wavebeast-node.py")
    try:
        with open(path, "r", encoding="utf-8") as f:
            body = f.read()
    except OSError:
        return HttpResponse("not found", status=404)
    resp = HttpResponse(body, content_type="text/x-python; charset=utf-8")
    resp["Cache-Control"] = "no-cache"
    return resp


# ---- Clerk auth ----------------------------------------------------------------------------------

def _clerk_ctx():
    return {"clerk_pk": settings.CLERK_PUBLISHABLE_KEY, "clerk_host": clerkauth.frontend_api_host()}


def sign_in(request):
    return render(request, "auth.html", {**_clerk_ctx(), "mode": "sign-in", "nav": ""})


def sign_up(request):
    return render(request, "auth.html", {**_clerk_ctx(), "mode": "sign-up", "nav": ""})


@csrf_exempt
def auth_clerk(request):
    """Exchange a verified Clerk session token for a Django session (called by the sign-in page)."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        token = json.loads(request.body.decode("utf-8")).get("token", "")
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    claims = clerkauth.verify_clerk_token(token)
    if not claims:
        return JsonResponse({"error": "invalid session"}, status=401)
    user, created = User.objects.get_or_create(username=claims["sub"])
    if created:
        user.set_unusable_password()
        user.save()
        Wallet.objects.get_or_create(user=user)
        InventoryItem.objects.get_or_create(user=user, item_id="spark_drive", defaults={"qty": 3})
    clerkauth.sync_profile(user)  # refresh verified identity, including primary email
    login(request, user)
    return JsonResponse({"ok": True, "redirect": "/me/" if _wallet(user).onboarded else "/onboarding/"})


def sign_out(request):
    logout(request)
    return redirect("/")


@login_required
def onboarding(request):
    w = _wallet(request.user)
    if request.method == "POST":
        w.onboarded = True
        w.save(update_fields=["onboarded"])
        return redirect("dashboard")
    return render(request, "onboarding.html", {"nav": "", **_clerk_ctx()})


# ---- billing (Stripe) ----------------------------------------------------------------------------

@login_required
def billing(request):
    w = _wallet(request.user)
    return render(request, "billing.html", {"nav": "", "wallet": w, "active": w.subscribed,
                                            "msg": request.session.pop("billing_msg", "")})


@login_required
@require_POST
def checkout(request):
    plan = request.POST.get("plan", "monthly")
    base = settings.SITE_URL
    try:
        url = billing_mod.checkout_url(_wallet(request.user), request.user, plan,
                                       base + "/billing/?ok=1", base + "/billing/?cancel=1")
    except Exception as e:
        request.session["billing_msg"] = f"Checkout unavailable: {e}"
        return redirect("billing")
    return redirect(url)


@login_required
def billing_portal(request):
    try:
        url = billing_mod.portal_url(_wallet(request.user), settings.SITE_URL + "/billing/")
    except Exception:
        request.session["billing_msg"] = "Billing portal is temporarily unavailable. Please try again."
        return redirect("billing")
    return redirect(url or "billing")


@csrf_exempt
def stripe_webhook(request):
    import stripe
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret and not settings.DEBUG:
        return HttpResponse("Webhook signing is not configured", status=503)
    try:
        if secret:
            event = stripe.Webhook.construct_event(request.body, request.META.get("HTTP_STRIPE_SIGNATURE", ""), secret)
        else:
            event = json.loads(request.body.decode("utf-8"))  # dev fallback when no signing secret is set
    except Exception:
        return HttpResponse(status=400)
    billing_mod.apply_event(event)
    return HttpResponse(status=200)


def app_version(request):
    """Version manifest the Android app polls to prompt for updates."""
    from . import appversion
    return JsonResponse({
        "version_code": appversion.VERSION_CODE,
        "version_name": appversion.VERSION_NAME,
        "notes": appversion.NOTES,
        "apk_url": settings.SITE_URL.rstrip("/") + "/download/app.apk",
    })


def app_apk(request):
    """Serve the APK from wavebeasts.com by streaming the current GitHub release asset through the site.
    A same-origin download with a clean Content-Length avoids the cross-origin signed-URL redirect chain
    that stalls some Android browsers (download 'starts but never finishes')."""
    from django.http import HttpResponse, StreamingHttpResponse
    url = "https://github.com/chvolk/wavebeast-dl/releases/latest/download/wavebeast.apk"
    try:
        up = requests.get(url, stream=True, timeout=30)
        up.raise_for_status()
    except Exception:
        return HttpResponse("upstream unavailable", status=502)
    resp = StreamingHttpResponse(up.iter_content(chunk_size=65536),
                                 content_type="application/vnd.android.package-archive")
    if up.headers.get("Content-Length"):
        resp["Content-Length"] = up.headers["Content-Length"]
    resp["Content-Disposition"] = 'attachment; filename="wavebeast.apk"'
    resp["Cache-Control"] = "no-cache"
    return resp


def login_page(request):
    """Django's built-in login, but bounce to Clerk when it's configured (the old /login/ URL)."""
    if settings.CLERK_PUBLISHABLE_KEY:
        return redirect("/sign-in/")
    from django.contrib.auth.views import LoginView
    return LoginView.as_view(template_name="login.html")(request)


def signup(request):
    if settings.CLERK_PUBLISHABLE_KEY:
        return redirect("/sign-up/")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        Wallet.objects.get_or_create(user=user)
        InventoryItem.objects.get_or_create(user=user, item_id="spark_drive", defaults={"qty": 3})
        login(request, user)
        return redirect("dashboard")
    return render(request, "signup.html", {"form": form})


# ---- beastiary -----------------------------------------------------------------------------------

@login_required
def beast_nickname(request, beast_id):
    """Rename one of your beasts from the site (session auth)."""
    if request.method == "POST":
        b = OwnedBeast.objects.filter(id=beast_id, user=request.user).first()
        if b:
            ind = b.individual_json or {}
            ind["nickname"] = (request.POST.get("nickname") or "").strip()[:24]
            b.individual_json = ind
            b.save(update_fields=["individual_json"])
    return redirect("dashboard")


@login_required
def dashboard(request):
    _cull_wilds(request.user)  # hide expired/overflow sightings on the web too
    beasts = list(request.user.beasts.all())
    for beast in beasts:
        beast.display_hp = _hp_now(beast.individual_json or {})
    listed_ids = set(TradeListing.objects.filter(user=request.user, is_open=True).values_list("beast_id", flat=True))
    team = _wallet(request.user).team_ids or []
    return render(request, "beastiary.html", {
        "owned": [b for b in beasts if b.status == "owned"],
        "wild": [b for b in beasts if b.status == "wild"],
        "wallet": _wallet(request.user),
        "items": list(request.user.items.filter(qty__gt=0)),
        "listed_ids": listed_ids,
        "team": team,
        "nav": "beastiary",
    })


@login_required
def catch(request, beast_id):
    beast = get_object_or_404(OwnedBeast, id=beast_id, user=request.user, status="wild")
    drive = request.POST.get("drive", "spark_drive")
    inv = InventoryItem.objects.filter(user=request.user, item_id=drive, qty__gt=0).first()
    if inv:
        inv.qty -= 1
        inv.save()
        p = 0.4 * DRIVE_MULT.get(drive, 1.0) * (0.2 + 0.8 * 0.5) * RARITY_RESIST.get(beast.rarity, 1.0)
        if random.random() < max(0.02, min(0.95, p)):
            beast.status = "owned"
            beast.save()
    return redirect("dashboard")


def sprite(request, beast_id):
    beast = get_object_or_404(OwnedBeast, id=beast_id)
    ind, sp = beast.individual_json, beast.species_json
    try:
        png = resolver.render(ind.get("palette") or sp.get("sprite_recipe", {}).get("base_palette"),
                              sp.get("sprite_recipe"), bool(ind.get("shiny")))
    except Exception:
        return HttpResponse(status=502)
    resp = HttpResponse(png, content_type="image/png")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


# ---- nodes ---------------------------------------------------------------------------------------

@login_required
def nodes(request):
    new_id = request.session.pop("new_token_id", None)
    new_node = request.user.nodes.filter(id=new_id).first() if new_id else None
    return render(request, "nodes.html", {
        "nodes": list(request.user.nodes.all()),
        "nodes_msg": request.session.pop("nodes_msg", ""),
        "new_node": new_node, "nav": "nodes"})


def _node_limit_reached(user):
    """Return a limit message if the user is at their node cap, else None."""
    limit = PAID_NODE_LIMIT if _paid(user) else FREE_NODE_LIMIT
    if user.nodes.count() >= limit:
        return (f"Node limit reached ({limit}). Upgrade for up to {PAID_NODE_LIMIT} nodes."
                if not _paid(user) else f"Node limit reached ({PAID_NODE_LIMIT}).")
    return None


@login_required
def node_create(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:256]
        msg = _node_limit_reached(request.user)
        if msg:
            request.session["nodes_msg"] = msg
        elif name:
            node = Node.objects.create(user=request.user, name=name)
            request.session["new_token_id"] = node.id
    return redirect("nodes")


@login_required
def node_app_token(request):
    """One-click token for the mobile app (Omnitool etc.): makes an 'app' node and surfaces its token
    to paste into the app's WORLD tab."""
    if request.method == "POST":
        msg = _node_limit_reached(request.user)
        if msg:
            request.session["nodes_msg"] = msg
        else:
            name = (request.POST.get("name") or "").strip()[:256] or "My phone (app)"
            node = Node.objects.create(user=request.user, name=name, kind="app")
            request.session["new_token_id"] = node.id
    return redirect("nodes")


@login_required
@require_POST
def node_boost(request, node_id):
    node = get_object_or_404(Node, id=node_id, user=request.user)
    if not _paid(request.user):
        request.session["nodes_msg"] = "Node boosts are a paid feature."
        return redirect("nodes")
    with transaction.atomic():
        w = Wallet.objects.select_for_update().get(user=request.user)
        node = Node.objects.select_for_update().get(pk=node.pk)
        if w.cores >= BOOST_COST_CORES:
            w.cores -= BOOST_COST_CORES
            w.save(update_fields=["cores"])
            node.boosted_until = max(node.boosted_until or timezone.now(), timezone.now()) + timezone.timedelta(seconds=BOOST_DURATION_SEC)
            node.save(update_fields=["boosted_until"])
        else:
            request.session["nodes_msg"] = "You need 1 core to boost a node."
    return redirect("nodes")


@login_required
def node_delete(request, node_id):
    Node.objects.filter(id=node_id, user=request.user).delete()
    return redirect("nodes")


# ---- trade market --------------------------------------------------------------------------------

@login_required
def trade(request):
    my_listings = list(request.user.listings.filter(is_open=True).select_related("beast"))
    market = list(TradeListing.objects.filter(is_open=True).exclude(user=request.user).select_related("beast", "user"))
    incoming = list(TradeOffer.objects.filter(listing__user=request.user, status="pending")
                    .select_related("listing__beast", "from_user").prefetch_related("offered_beasts"))
    outgoing = list(TradeOffer.objects.filter(from_user=request.user, status="pending")
                    .select_related("listing__beast", "listing__user").prefetch_related("offered_beasts"))
    # beasts you can offer/list: owned, not currently listed and not tied up in a pending offer of yours.
    tied = set(TradeOffer.objects.filter(from_user=request.user, status="pending")
               .values_list("offered_beasts__id", flat=True))
    listed_ids = set(TradeListing.objects.filter(beast__user=request.user, is_open=True).values_list("beast_id", flat=True))
    tradeable = [b for b in request.user.beasts.filter(status="owned")
                 if b.id not in listed_ids and b.id not in tied]
    return render(request, "trade.html", {
        "my_listings": my_listings, "market": market, "incoming": incoming, "outgoing": outgoing,
        "tradeable": tradeable, "wallet": _wallet(request.user),
        "max_beasts": TradeOffer.MAX_BEASTS, "trade_msg": request.session.pop("trade_msg", ""),
        "nav": "trade",
    })


@login_required
@require_POST
def trade_list_beast(request):
    if not _paid(request.user):
        request.session["trade_msg"] = "Trading is a paid feature."
        return redirect("trade")
    with transaction.atomic():
        Wallet.objects.select_for_update().get(user=request.user)
        beast = get_object_or_404(OwnedBeast.objects.select_for_update(), id=request.POST.get("beast_id"), user=request.user, status="owned")
        tied = TradeOffer.objects.filter(status="pending").filter(Q(offered_beast=beast) | Q(offered_beasts=beast)).exists()
        if not beast.verified:
            request.session["trade_msg"] = "Only verified beasts (caught through a node) can be traded."
        elif tied:
            request.session["trade_msg"] = "Withdraw the pending offer before listing this beast."
        else:
            TradeListing.objects.update_or_create(beast=beast, defaults={"user": request.user, "is_open": True,
                "note": (request.POST.get("note") or "")[:200]})
    return redirect("trade")


@login_required
@require_POST
def trade_unlist(request, listing_id):
    with transaction.atomic():
        listing = get_object_or_404(TradeListing.objects.select_for_update(), id=listing_id, user=request.user)
        listing.is_open = False
        listing.save(update_fields=["is_open"])
        for offer in listing.offers.select_for_update().filter(status="pending"):
            _refund_offer(offer)
            offer.status = "declined"
            offer.save(update_fields=["status"])
    return redirect("trade")


@login_required
@require_POST
def trade_offer(request, listing_id):
    if not _paid(request.user):
        request.session["trade_msg"] = "Trading is a paid feature."
        return redirect("trade")
    listing = get_object_or_404(TradeListing, id=listing_id, is_open=True)
    if listing.user_id == request.user.id:
        return redirect("trade")
    # Up to 3 beasts (beast_id may repeat in the form) + a shards/cores sweetener.
    ids = [i for i in request.POST.getlist("beast_id") if i]
    try:
        shards = max(0, int(request.POST.get("shards") or 0))
        cores = max(0, int(request.POST.get("cores") or 0))
    except (TypeError, ValueError):
        request.session["trade_msg"] = "Bad resource amount."
        return redirect("trade")
    if not ids and not shards and not cores:
        request.session["trade_msg"] = "Offer at least one beast or some resources."
        return redirect("trade")
    if len(ids) > TradeOffer.MAX_BEASTS:
        request.session["trade_msg"] = f"You can offer at most {TradeOffer.MAX_BEASTS} beasts."
        return redirect("trade")
    with transaction.atomic():
        listing = get_object_or_404(TradeListing.objects.select_for_update(), id=listing_id, is_open=True)
        wallet = Wallet.objects.select_for_update().get(user=request.user)
        # beasts must be yours, owned, verified, and not already tied up in a pending offer / listing
        tied = set(TradeOffer.objects.filter(from_user=request.user, status="pending")
                   .values_list("offered_beasts__id", flat=True))
        beasts = []
        for bid in dict.fromkeys(ids):  # dedupe, preserve order
            b = OwnedBeast.objects.filter(id=bid, user=request.user, status="owned").first()
            if not b:
                request.session["trade_msg"] = "One of those beasts isn't available."
                return redirect("trade")
            if not b.verified:
                request.session["trade_msg"] = "Only verified beasts (caught through a node) can be offered."
                return redirect("trade")
            if b.id in tied or TradeListing.objects.filter(beast=b, is_open=True).exists():
                request.session["trade_msg"] = "That beast is already listed or in another offer."
                return redirect("trade")
            beasts.append(b)
        if shards > wallet.shards or cores > wallet.cores:
            request.session["trade_msg"] = "Not enough resources for that offer."
            return redirect("trade")
        # escrow the currency so it can't be double-spent while the offer is pending
        wallet.shards -= shards
        wallet.cores -= cores
        wallet.save(update_fields=["shards", "cores"])
        offer = TradeOffer.objects.create(
            listing=listing, from_user=request.user,
            offered_beast=(beasts[0] if beasts else None),
            offered_shards=shards, offered_cores=cores)
        if beasts:
            offer.offered_beasts.set(beasts)
    return redirect("trade")


@login_required
@require_POST
def trade_accept(request, offer_id):
    if not _paid(request.user):
        request.session["trade_msg"] = "Trading is a paid feature."
        return redirect("trade")
    offer = get_object_or_404(TradeOffer, id=offer_id, listing__user=request.user, status="pending")
    with transaction.atomic():
        listing = TradeListing.objects.select_for_update().get(id=offer.listing_id)
        offer = get_object_or_404(TradeOffer.objects.select_for_update(), id=offer_id, status="pending")
        if not listing.is_open:
            request.session["trade_msg"] = "That listing is no longer open."
            return redirect("trade")
        their_beasts = list(OwnedBeast.objects.select_for_update()
                            .filter(id__in=[b.id for b in offer.beasts()]))
        my_beast = OwnedBeast.objects.select_for_update().get(id=listing.beast_id)
        if my_beast.user_id != request.user.id or any(b.user_id != offer.from_user_id or b.status != "owned" or not b.verified for b in their_beasts):
            request.session["trade_msg"] = "One of the offered beasts is no longer available."
            return redirect("trade")
        _detach_beasts(request.user, [my_beast.id])
        _detach_beasts(offer.from_user, [b.id for b in their_beasts])
        # give the lister the offered beasts + escrowed resources
        my_wallet = Wallet.objects.select_for_update().get(user=request.user)
        for tb in their_beasts:
            tb.user = request.user
            tb.status = "owned"
            tb.save(update_fields=["user", "status"])
        my_wallet.shards += offer.offered_shards
        my_wallet.cores += offer.offered_cores
        my_wallet.save(update_fields=["shards", "cores"])
        # give the offerer the listed beast
        my_beast.user = offer.from_user
        my_beast.status = "owned"
        my_beast.save(update_fields=["user", "status"])
        listing.is_open = False
        listing.save(update_fields=["is_open"])
        offer.status = "accepted"
        offer.save(update_fields=["status"])
        # decline + refund every other pending offer on this listing
        for other in listing.offers.filter(status="pending").exclude(id=offer.id):
            _refund_offer(other)
            other.status = "declined"
            other.save(update_fields=["status"])
    return redirect("trade")


def _detach_beasts(user, beast_ids):
    """A transferred beast cannot remain a previous owner's buddy or competitive fighter."""
    Buddy.objects.filter(user=user, beast_id__in=beast_ids).update(beast=None, carrier=None, last_event_at=None)
    w = Wallet.objects.select_for_update().get(user=user)
    removed = {str(i) for i in beast_ids}
    w.team_ids = [i for i in w.team_ids if str(i) not in removed]
    w.save(update_fields=["team_ids"])
    LadderTeam.objects.filter(user=user).update(fighters=[])


def _refund_offer(offer):
    """Return escrowed shards/cores to the offerer (beasts free themselves once status != pending)."""
    if offer.offered_shards or offer.offered_cores:
        w = Wallet.objects.select_for_update().get(user=offer.from_user)
        w.shards += offer.offered_shards
        w.cores += offer.offered_cores
        w.save(update_fields=["shards", "cores"])


@login_required
@require_POST
def trade_decline(request, offer_id):
    with transaction.atomic():
        offer = TradeOffer.objects.select_for_update().filter(
            id=offer_id, listing__user=request.user, status="pending").first()
        if offer:
            _refund_offer(offer)
            offer.status = "declined"
            offer.save(update_fields=["status"])
    return redirect("trade")


@login_required
@require_POST
def trade_withdraw(request, offer_id):
    """Offerer withdraws their own pending offer (refunds escrow, frees the beasts)."""
    with transaction.atomic():
        offer = TradeOffer.objects.select_for_update().filter(
            id=offer_id, from_user=request.user, status="pending").first()
        if offer:
            _refund_offer(offer)
            offer.status = "declined"
            offer.save(update_fields=["status"])
    return redirect("trade")


# ---- battle --------------------------------------------------------------------------------------

def _fighter(b):
    return {"species": b.species_json, "individual": b.individual_json}


def _team_for(user):
    ids = _wallet(user).team_ids or []
    byid = {str(b.id): b for b in OwnedBeast.objects.filter(user=user, status="owned", verified=True, id__in=ids)}
    return [_fighter(byid[str(i)]) for i in ids if str(i) in byid]


def _gym_team():
    team = []
    for code in GYM_CODES:
        for _ in range(8):  # generation may roll resource/nothing; retry to get a beast
            try:
                bundle = {"schema": "wavebeast.scanbundle", "v": 1, "signals": [
                    {"kind": "code", "strength": 1.0, "value": {"data": code + str(random.random())}},
                    {"kind": "wifi", "strength": 0.9, "value": {"rssi": -40}},
                    {"kind": "ble", "strength": 0.8, "value": {"rssi": -50}},
                ]}
                res = resolver.generate(bundle)
            except Exception:
                break
            if res.get("outcome") == "beast":
                team.append({"species": res["species"], "individual": res["individual"]})
                break
    return team


@login_required
def battle(request):
    owned = list(request.user.beasts.filter(status="owned"))
    team_ids = [str(i) for i in (_wallet(request.user).team_ids or [])]
    result = request.session.pop("last_battle", None)
    lt = LadderTeam.objects.filter(user=request.user).first()
    unseen = list(AsyncBattle.objects.filter(user=request.user, seen=False)[:20])
    if unseen:
        AsyncBattle.objects.filter(user=request.user, seen=False).update(seen=True)
    return render(request, "battle.html", {
        "owned": owned, "team_ids": team_ids, "result": result,
        "records": list(request.user.battles.all()[:8]), "nav": "battle",
        "ladder": lt, "unseen": unseen,
        "ladder_recent": list(request.user.ladder_battles.all()[:10]),
        "top": list(LadderTeam.objects.select_related("user")[:10]),
        "ladder_msg": request.session.pop("ladder_msg", None),
    })


@login_required
@require_POST
def ladder_enter(request):
    if not _paid(request.user):
        request.session["ladder_msg"] = "The async ladder is a paid feature."
        return redirect("battle")
    fighters = _team_for(request.user)
    if not fighters:
        request.session["ladder_msg"] = "Set a team of up to 3 beasts first."
    else:
        lt, _ = LadderTeam.objects.get_or_create(user=request.user)
        lt.fighters = fighters
        lt.save()
        request.session["ladder_msg"] = "On the ladder - other trainers will battle your team while you're away."
    return redirect("battle")


@login_required
@require_POST
def ladder_run(request):
    if not _paid(request.user):
        request.session["ladder_msg"] = "The async ladder is a paid feature."
        return redirect("battle")
    lt = LadderTeam.objects.filter(user=request.user).first()
    if not lt or not lt.fighters:
        request.session["ladder_msg"] = "Enter the ladder first."
        return redirect("battle")
    opponents = list(LadderTeam.objects.filter(user__wallet__subscribed=True).exclude(user=request.user).exclude(fighters=[]).select_related("user"))
    if not opponents:
        request.session["ladder_msg"] = "No opponents yet - check back once others join the ladder."
        return redirect("battle")
    random.shuffle(opponents)
    wins = 0
    played = 0
    for opp in opponents[:5]:
        r = ladder.resolve_match(lt, opp, initiator=request.user)
        if r is None:
            break
        played += 1
        if r == "win":
            wins += 1
    request.session["ladder_msg"] = f"Ran {played} ladder matches · {wins} won."
    return redirect("battle")


@login_required
def set_team(request):
    if request.method == "POST":
        ids = request.POST.getlist("beast_ids")[:3]
        # Only verified beasts fight on the ladder/gyms - no modded stats in competitive play.
        valid = list(OwnedBeast.objects.filter(user=request.user, status="owned", verified=True, id__in=ids).values_list("id", flat=True))
        w = _wallet(request.user)
        w.team_ids = [str(i) for i in valid]
        w.save(update_fields=["team_ids"])
    return redirect("battle")


@login_required
@require_POST
def battle_fight(request):
    if not _paid(request.user):
        request.session["last_battle"] = {"error": "Battles are a paid feature."}
        return redirect("battle")
    my_team = _team_for(request.user)
    if not my_team:
        request.session["last_battle"] = {"error": "Set a team of up to 3 beasts first."}
        return redirect("battle")
    # opponent: a random other player's team, else a gym
    opp_name, opp_team = "Gym", []
    others = list(Wallet.objects.filter(subscribed=True).exclude(user=request.user).exclude(team_ids=[]).select_related("user"))
    random.shuffle(others)
    for w in others:
        t = _team_for(w.user)
        if t:
            opp_name, opp_team = w.user.username, t
            break
    if not opp_team:
        opp_team = _gym_team()
    try:
        res = resolver.battle_auto(my_team, opp_team)
    except Exception as e:
        request.session["last_battle"] = {"error": f"Battle resolver unavailable: {e}"}
        return redirect("battle")
    outcome = "win" if res.get("winner") == "a" else ("draw" if res.get("winner") == "draw" else "loss")
    reward = 0
    if outcome == "win":
        reward = 25 + random.randint(0, 15)
        w = _wallet(request.user)
        w.shards += reward
        w.save(update_fields=["shards"])
    BattleRecord.objects.create(user=request.user, opponent=opp_name, result=outcome,
                                turns=res.get("turns", 0), reward=reward)
    request.session["last_battle"] = {"outcome": outcome, "opponent": opp_name, "reward": reward,
                                      "turns": res.get("turns", 0), "log": res.get("log", [])[:12]}
    return redirect("battle")


# ---- node snapshot ingest (token auth, rate limited) ---------------------------------------------

@csrf_exempt
def api_snapshot(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    token = request.headers.get("X-WB-Node-Token", "")
    node = Node.objects.filter(token=token).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    wait = node.seconds_until_ready()
    if wait > 0:
        return JsonResponse({"accepted": False, "error": "rate_limited", "retry_after": wait,
                             "hint": "boost this node with cores to raise the rate"}, status=429)
    try:
        bundle = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    try:
        # Server-authoritative roll: a per-submission random nonce the client can't predict, so the
        # resulting stats can't be modded or ground out. Species stays deterministic from the bundle.
        res = resolver.generate(bundle, roll_nonce=secrets.token_hex(16))
    except Exception as e:
        return JsonResponse({"error": f"resolver unavailable: {e}"}, status=502)
    node.last_snapshot_at = timezone.now()
    node.save(update_fields=["last_snapshot_at"])
    outcome = res.get("outcome")
    extra = {}
    if outcome == "resource":
        _apply_resource(node.user, res)
        detail = res.get("reward_label", "")
        extra["reward_label"] = detail
    elif outcome == "beast":
        bres = _apply_beast(node, res)
        detail = bres["detail"]
        # surface the server-rolled (verified) beast so a client can reveal it
        extra.update({k: bres.get(k) for k in ("beast", "caught", "fled", "battled", "free")})
        extra["verified"] = True
        if bres.get("beast"):
            extra["sprite_url"] = request.build_absolute_uri(f"/sprite/{bres['beast']['id']}.png")
    else:
        detail = res.get("message", "")
    Snapshot.objects.create(node=node, outcome=outcome or "nothing", entropy=res.get("entropy", 0), detail=detail[:200])
    return JsonResponse({"accepted": True, "outcome": outcome, "detail": detail,
                         "entropy": res.get("entropy", 0), "next_snapshot_in": node.min_interval(), **extra})


@csrf_exempt
def api_import(request):
    """Upload a subscriber's local collection to their account (deduped by the local beast id). Trust the
    uploaded species/individual (subscription-gated) but cap IVs/level. Called by the engine's /node/upload."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    if not _wallet(node.user).subscribed:
        return JsonResponse({"error": "subscription required"}, status=402)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beasts = data.get("beasts", []) if isinstance(data, dict) else []
    imported = skipped = 0
    for b in beasts[:500]:
        sp, ind = b.get("species") or {}, b.get("individual") or {}
        sid = str(ind.get("id") or "")
        if not sid or OwnedBeast.objects.filter(user=node.user, source_id=sid).exists():
            skipped += 1
            continue
        ivs = ind.get("ivs") or {}
        for k in list(ivs):
            try:
                ivs[k] = max(0, min(31, int(ivs[k])))
            except (TypeError, ValueError):
                ivs[k] = 0
        ind["ivs"] = ivs
        lvl = max(1, min(100, int(ind.get("level", 1) or 1)))
        OwnedBeast.objects.create(
            user=node.user, source_id=sid, species_id=sp.get("species_id", ""), id_version=sp.get("id_version", 1),
            name=sp.get("name", "?"), rarity=ind.get("rarity", "common"), shiny=bool(ind.get("shiny")),
            level=lvl, status="owned", verified=False, species_json=sp, individual_json=ind)
        imported += 1
    # verified=False: imported beasts carry client-claimed stats, so they're collection-only - never
    # tradeable or laddered. To get a legit tradeable copy, submit the scan via a node (site re-rolls it).
    return JsonResponse({"ok": True, "imported": imported, "skipped": skipped,
                         "note": "imported to your collection (unverified - not tradeable; submit scans via a node for verified beasts)"})


SYNC_COOLDOWN_SEC = 86400  # one whole-account sync run per day


@csrf_exempt
def api_sync(request):
    """Standardize older verified beasts to the current generation - backfill new fields (e.g. nature),
    bump their id_version - so they pick up updates we ship over time. Free tier; token auth; verified
    (non-modded) beasts only; each beast upgrades once per version; the whole run is once per day."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    w = _wallet(node.user)
    now = timezone.now()
    if w.last_sync and (now - w.last_sync).total_seconds() < SYNC_COOLDOWN_SEC:
        retry = int(SYNC_COOLDOWN_SEC - (now - w.last_sync).total_seconds())
        return JsonResponse({"error": "sync runs once per day", "retry_after": retry}, status=429)
    try:
        caps = resolver.capabilities()
    except Exception as e:
        return JsonResponse({"error": f"resolver unavailable: {e}"}, status=502)
    cur = int(caps.get("id_version", 1))
    natures = caps.get("natures", [])
    synced = 0
    for b in node.user.beasts.filter(verified=True):
        ind = b.individual_json or {}
        if b.id_version >= cur and ind.get("nature"):
            continue  # already current
        if not ind.get("nature") and natures:
            h = int(hashlib.sha256(f"{b.species_id}:{b.id}".encode()).hexdigest(), 16)
            ind["nature"] = natures[h % len(natures)]
        ind["id_version"] = cur
        b.individual_json = ind
        b.id_version = cur
        b.save(update_fields=["individual_json", "id_version"])
        synced += 1
    w.last_sync = now
    w.save(update_fields=["last_sync"])
    return JsonResponse({"ok": True, "synced": synced, "version": cur})


@csrf_exempt
def api_release(request):
    """Release a beast back to the waves - permanently removes it from the account (node-token auth,
    free). Can't release your slotted buddy; also clears it from your team and any open trade listing."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user).first()
    if not beast:
        return JsonResponse({"error": "no such beast"}, status=404)
    buddy = getattr(node.user, "buddy", None)
    if buddy and buddy.beast_id == beast.id:
        return JsonResponse({"error": "unslot your buddy before releasing it"}, status=409)
    in_offer = TradeOffer.objects.filter(status="pending").filter(Q(offered_beast=beast) | Q(offered_beasts=beast) | Q(listing__beast=beast)).exists()
    if in_offer or TradeListing.objects.filter(beast=beast, is_open=True).exists():
        return JsonResponse({"error": "Unlist this beast or withdraw its pending trade offer before releasing it."}, status=409)
    LadderTeam.objects.filter(user=node.user).update(fighters=[])
    w = _wallet(node.user)
    kept = [i for i in (w.team_ids or []) if str(i) != str(beast.id)]
    if kept != (w.team_ids or []):
        w.team_ids = kept
        w.save(update_fields=["team_ids"])
    name = beast.name
    beast.delete()
    return JsonResponse({"ok": True, "released": name})


@csrf_exempt
def api_shop(request):
    """The item catalog (node-token auth). Prices come from the engine so the site owns them."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        return JsonResponse(resolver.shop())
    except Exception as e:
        return JsonResponse({"error": f"resolver unavailable: {e}"}, status=502)


@csrf_exempt
def api_buy(request):
    """Buy an item with account currency (node-token auth). Server-authoritative: the price is read from
    the engine catalog and the balance is checked on the server, so nothing about the cost is client-set.
    Buying is part of the free base loop (drives to catch, food to train)."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    item_id = str(data.get("item_id") or "")
    try:
        qty = max(1, min(99, int(data.get("qty", 1))))
    except (TypeError, ValueError):
        qty = 1
    status, payload = _buy_item(node.user, item_id, qty)
    return JsonResponse(payload, status=status)


def _buy_item(user, item_id, qty):
    """Server-authoritative purchase from account currency. Price comes from the engine catalog and the
    balance is checked here, so nothing about the cost is client-set. Shared by the node API and the web
    shop. Buying (drives to catch, food to train) is part of the free base loop. Returns (status, payload)."""
    try:
        catalog = resolver.shop().get("items", [])
    except Exception as e:
        return 502, {"error": f"resolver unavailable: {e}"}
    item = next((i for i in catalog if i.get("id") == item_id), None)
    if not item:
        return 404, {"error": "unknown item"}
    kind = item.get("cost_kind", "shards")
    cost = int(item.get("cost_amt", 0)) * qty
    with transaction.atomic():
        w = Wallet.objects.select_for_update().get_or_create(user=user)[0]
        balance = w.cores if kind == "cores" else w.shards
        if balance < cost:
            return 409, {"error": f"not enough {kind}", "need": cost, "have": balance}
        if kind == "cores":
            w.cores -= cost
        else:
            w.shards -= cost
        w.save()
        inv, _ = InventoryItem.objects.get_or_create(user=user, item_id=item_id)
        inv.qty += qty
        inv.save()
    return 200, {"ok": True, "item_id": item_id, "qty": inv.qty, "spent": cost, "cost_kind": kind,
                 "name": item.get("name", item_id), "shards": w.shards, "cores": w.cores}


@login_required
def shop(request):
    """Web shop: spend your account shards/cores on drives, food and tools. Same wallet the app/nodes use,
    so purchases show up everywhere instantly. Free base loop - no subscription needed."""
    try:
        catalog = resolver.shop().get("items", [])
    except Exception:
        catalog = []
    w = _wallet(request.user)
    inv = {i.item_id: i.qty for i in request.user.items.filter(qty__gt=0)}
    cats = {}
    for it in catalog:
        it["owned"] = inv.get(it.get("id"), 0)
        cats.setdefault(it.get("category", "other"), []).append(it)
    order = ["drive", "food", "tool", "other"]
    grouped = [(c, cats[c]) for c in order if c in cats]
    return render(request, "shop.html", {
        "nav": "shop", "wallet": w, "grouped": grouped, "inv": inv,
        "shop_msg": request.session.pop("shop_msg", ""), "shop_err": request.session.pop("shop_err", ""),
    })


@login_required
def shop_buy(request):
    if request.method == "POST":
        item_id = str(request.POST.get("item_id") or "")
        try:
            qty = max(1, min(99, int(request.POST.get("qty", 1))))
        except (TypeError, ValueError):
            qty = 1
        status, payload = _buy_item(request.user, item_id, qty)
        if status == 200:
            request.session["shop_msg"] = f"Bought {qty}x {payload.get('name', item_id)} for {payload['spent']} {payload['cost_kind']}."
        else:
            request.session["shop_err"] = payload.get("error", "Purchase failed.")
    return redirect("shop")


@require_GET
def api_account(request):
    """Private linked-account summary. Available to free and paid devices."""
    node = Node.objects.select_related("user").filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    user = node.user
    # Existing Clerk accounts only cached a name. Backfill missing email without requiring a new login.
    if not user.email and user.username.startswith("user_") and cache.add(f"profile-backfill:{user.pk}", True, 300):
        clerkauth.sync_profile(user)
    w = _wallet(user)
    response = JsonResponse({"ok": True, "account": {
        "name": user.first_name or user.username, "email": user.email or None,
        "plan": "Premium" if w.subscribed else "Free", "subscribed": w.subscribed,
        "subscription_status": w.subscription_status or ("active" if w.subscribed else "free"),
        "shards": w.shards, "cores": w.cores,
        "beasts": user.beasts.filter(status="owned").count(), "nodes": user.nodes.count(),
        "node_limit": PAID_NODE_LIMIT if w.subscribed else FREE_NODE_LIMIT,
    }, "node": {"name": node.name, "kind": node.kind, "next_snapshot_in": node.seconds_until_ready()}})
    response["Cache-Control"] = "private, no-store"
    return response


@csrf_exempt
def api_beasts(request):
    """The account's beasts (owned + wild sightings), inventory and currency (node-token auth). Free to
    read - how a companion app shows your collection, bag, and picks a buddy. Sprites: /sprite/<id>.png."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    _cull_wilds(node.user)  # don't show expired/overflow sightings
    out = []
    for b in node.user.beasts.exclude(status="wild").order_by("-caught_at")[:500]:
        out.append(_beast_row(b))
    wild = [_beast_row(b) for b in node.user.beasts.filter(status="wild").order_by("-caught_at")[:MAX_UNSEEN_WILD]]
    inv = {i.item_id: i.qty for i in node.user.items.filter(qty__gt=0)}
    buddy = getattr(node.user, "buddy", None)
    w = _wallet(node.user)
    return JsonResponse({"ok": True, "account": node.user.first_name or node.user.username, "node": node.name,
                         "beasts": out, "wild": wild, "inventory": inv,
                         "buddy_beast_id": getattr(buddy, "beast_id", None),
                         "subscribed": w.subscribed, "shards": w.shards, "cores": w.cores})


def _beast_row(b):
    ind = b.individual_json or {}
    hp = _hp_now(ind)
    row = {"id": b.id, "name": b.name, "rarity": b.rarity, "shiny": b.shiny, "level": b.level,
           "species_id": b.species_id, "verified": b.verified, "status": b.status,
           "types": (b.species_json or {}).get("types", []), "nickname": ind.get("nickname", ""),
           "nature": ind.get("nature", ""), "hp": hp, "hp_max": HP_MAX, "fainted": hp <= 0}
    if b.status == "wild" and b.expires_at:
        row["expires_in"] = max(0, int((b.expires_at - timezone.now()).total_seconds()))
    return row


@csrf_exempt
def api_catch(request):
    """Catch a wild account sighting with a drive from your bag (node-token auth). Server rolls the
    chance and consumes the drive - outcome isn't client-controlled. Part of the free base loop."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user, status="wild").first()
    if not beast:
        return JsonResponse({"error": "no such wild sighting"}, status=404)
    if beast.expires_at and beast.expires_at < timezone.now():
        beast.delete()
        return JsonResponse({"error": "that sighting expired", "expired": True}, status=410)
    drive = str(data.get("drive") or "spark_drive")
    with transaction.atomic():
        inv = InventoryItem.objects.select_for_update().filter(user=node.user, item_id=drive, qty__gt=0).first()
        if not inv:
            return JsonResponse({"error": f"no {drive} in your bag"}, status=409)
        inv.qty -= 1
        inv.save()
        p = 0.4 * DRIVE_MULT.get(drive, 1.0) * (0.2 + 0.8 * 0.5) * RARITY_RESIST.get(beast.rarity, 1.0)
        chance = max(0.02, min(0.95, p))
        caught = random.random() < chance
        if caught:
            beast.status = "owned"
            beast.expires_at = None  # kept for good once caught
            beast.save(update_fields=["status", "expires_at"])
    pct = round(chance * 100)
    msg = (f"Caught it! ({pct}% with the {drive.replace('_', ' ')})" if caught
           else f"It broke free - {pct}% catch chance. Weaken it in battle or use a stronger drive.")
    return JsonResponse({"ok": True, "caught": caught, "chance": round(chance, 2), "drive": drive,
                         "remaining": inv.qty, "message": msg, "beast": _beast_row(beast)})


@csrf_exempt
def api_heal(request):
    """Heal a beast to full by spending a Potion from the bag (node-token auth). Health also regenerates
    over time on its own; this is the instant option."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user).first()
    if not beast:
        return JsonResponse({"error": "no such beast"}, status=404)
    if _hp_now(beast.individual_json or {}) >= HP_MAX:
        return JsonResponse({"error": "already at full health"}, status=409)
    with transaction.atomic():
        pot = InventoryItem.objects.select_for_update().filter(user=node.user, item_id="potion", qty__gt=0).first()
        if not pot:
            return JsonResponse({"error": "no potion in your bag"}, status=409)
        pot.qty -= 1
        pot.save()
        _set_hp(beast, HP_MAX)
    return JsonResponse({"ok": True, "beast": _beast_row(beast), "potions": pot.qty})


@csrf_exempt
def api_nickname(request):
    """Set (or clear) a beast's nickname on the account (node-token auth). Any node can rename; the account
    is the source of truth, so premium apps see it sync across devices immediately."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return JsonResponse({"error": "bad node token"}, status=403)
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user).first()
    if not beast:
        return JsonResponse({"error": "no such beast"}, status=404)
    nick = (data.get("nickname") or "").strip()[:24]
    ind = beast.individual_json or {}
    ind["nickname"] = nick
    beast.individual_json = ind
    beast.save(update_fields=["individual_json"])
    return JsonResponse({"ok": True, "beast": _beast_row(beast)})


# ---- Buddy API (paid) - the tamagotchi companion custom apps carry -------------------------------
# All state is server-authoritative and node-token authed. Care raises vitals/mood/relationship; while
# slotted, the buddy earns rate-limited away-events (resources/XP) - faster the more it loves you.

def _buddy_auth(request):
    """Returns (node, error_response). Node-token auth + subscription (paid) gate."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return None, JsonResponse({"error": "bad node token"}, status=403)
    if not _wallet(node.user).subscribed:
        return None, JsonResponse({"error": "the Buddy system is a paid feature", "code": "paywall"}, status=402)
    return node, None


@csrf_exempt
@require_GET
@transaction.atomic
def api_buddy(request):
    """GET the current buddy + any away-events accrued since the last poll (server-rolled, rate-limited)."""
    node, err = _buddy_auth(request)
    if err:
        return err
    Wallet.objects.select_for_update().get(user=node.user)
    b, _ = Buddy.objects.select_for_update().get_or_create(user=node.user)
    w = _wallet(node.user)
    buddymod.refresh(b)
    events = buddymod.accrue_events(b, w, b.beast) if b.beast_id else []
    if b.beast_id and b.beast:
        b.beast.save()
    w.save()
    b.save()
    return JsonResponse({"ok": True, "buddy": buddymod.state(b), "events": events,
                         "wallet": {"shards": w.shards, "cores": w.cores}})


@csrf_exempt
@require_POST
@transaction.atomic
def api_buddy_slot(request):
    """Slot an owned beast as the account's one buddy, or clear its slot."""
    node, err = _buddy_auth(request)
    if err:
        return err
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    Wallet.objects.select_for_update().get(user=node.user)
    if "beast_id" in data and data["beast_id"] is None:
        b, _ = Buddy.objects.select_for_update().get_or_create(user=node.user)
        b.beast = None
        b.carrier = None
        b.last_event_at = None
        b.save()
        return JsonResponse({"ok": True, "buddy": buddymod.state(b)})
    # Any owned beast can be a buddy - it's a personal companion (not traded or laddered), and away-events
    # don't scale with its stats, so there's no anti-cheat reason to require a verified beast here.
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user, status="owned").first()
    if not beast:
        return JsonResponse({"error": "no such owned beast"}, status=404)
    b, _ = Buddy.objects.select_for_update().get_or_create(user=node.user)
    b.beast = beast
    b.carrier = node  # this device is now carrying the buddy
    b.slotted_at = timezone.now()
    b.last_event_at = timezone.now()  # start the away-event clock fresh on slot
    b.save()
    return JsonResponse({"ok": True, "buddy": buddymod.state(b)})


@csrf_exempt
@require_POST
@transaction.atomic
def api_buddy_care(request):
    """Apply a care action (feed/play/rest/clean/train) to the slotted buddy."""
    node, err = _buddy_auth(request)
    if err:
        return err
    Wallet.objects.select_for_update().get(user=node.user)
    b, _ = Buddy.objects.select_for_update().get_or_create(user=node.user)
    if not b.beast_id:
        return JsonResponse({"error": "no buddy slotted"}, status=409)
    b.carrier = node  # caring for it from this device -> it's the carrier
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    res = buddymod.apply_care(b, (data.get("action") or "").lower())
    if res.get("error") == "cooldown":
        b.save()
        return JsonResponse({"error": "cooldown", "retry_after_sec": res["retry_after_sec"],
                             "buddy": buddymod.state(b)}, status=429)
    if res.get("error"):
        return JsonResponse({"error": res["error"]}, status=400)
    if b.beast:
        b.beast.save()
    b.save()
    return JsonResponse({"ok": True, "result": res, "buddy": buddymod.state(b)})


def _apply_resource(user, res):
    w = _wallet(user)
    amt = int(res.get("reward_amount", 0))
    if res.get("reward_kind") == "currency":
        if res.get("reward_id") == "cores":
            w.cores += amt
        else:
            w.shards += amt
        w.save()
    else:
        item, _ = InventoryItem.objects.get_or_create(user=user, item_id=res.get("reward_id", "spark_drive"))
        item.qty += amt
        item.save()


def _scan_party(user):
    """Your battle party for wild encounters: your set team if any, else your 3 highest verified beasts."""
    team = _team_for(user)
    if team:
        return team
    beasts = OwnedBeast.objects.filter(user=user, status="owned", verified=True).order_by("-level")[:3]
    return [_fighter(b) for b in beasts]


def _healthy_party_beasts(user):
    """Up to 3 party beasts that still have HP (your set team, else highest-level verified). A fainted
    roster means no scan-battles until something heals."""
    ids = _wallet(user).team_ids or []
    if ids:
        byid = {b.id: b for b in OwnedBeast.objects.filter(user=user, status="owned", verified=True, id__in=ids)}
        beasts = [byid[i] for i in ids if i in byid]
    else:
        beasts = list(OwnedBeast.objects.filter(user=user, status="owned", verified=True).order_by("-level")[:6])
    return [b for b in beasts if _hp_now(b.individual_json or {}) > 0][:3]


def _cull_wilds(user):
    """Expire timed-out wild sightings and keep only the newest MAX_UNSEEN_WILD pending ones."""
    now = timezone.now()
    OwnedBeast.objects.filter(user=user, status="wild", expires_at__lt=now).delete()
    extra = list(OwnedBeast.objects.filter(user=user, status="wild").order_by("-caught_at")
                 .values_list("id", flat=True)[MAX_UNSEEN_WILD:])
    if extra:
        OwnedBeast.objects.filter(id__in=extra).delete()


def _create_beast(node, sp, ind, status):
    expires = timezone.now() + timezone.timedelta(seconds=WILD_TTL_SEC) if status == "wild" else None
    return OwnedBeast.objects.create(
        user=node.user, node=node, species_id=sp.get("species_id", ""), id_version=sp.get("id_version", 1),
        name=sp.get("name", "?"), rarity=ind.get("rarity", "common"), shiny=bool(ind.get("shiny")),
        level=ind.get("level", 1), status=status, verified=True, species_json=sp, individual_json=ind,
        expires_at=expires)


def _apply_beast(node, res):
    """Create the server-rolled (verified) beast on the account. Returns a dict the snapshot response
    surfaces so a client can reveal it: {detail, beast, caught, fled, battled}."""
    user = node.user
    _cull_wilds(user)  # drop expired/overflow sightings before adding a new one
    sp, ind = res.get("species", {}), res.get("individual", {})
    if OwnedBeast.objects.filter(user=user, status="owned").count() == 0:
        b = _create_beast(node, sp, ind, "owned")  # first catch is free
        return {"detail": f"caught (free) {sp.get('name')} [{ind.get('rarity')}]",
                "beast": _beast_row(b), "caught": True, "free": True, "fled": False, "battled": False}
    # A wild sometimes challenges you to a battle first - but only if you have a HEALTHY party.
    party_beasts = _healthy_party_beasts(user)
    battled = bool(party_beasts) and random.random() < 0.35
    if battled:
        fighters = [_fighter(b) for b in party_beasts]
        try:
            won = resolver.battle_auto(fighters, [{"species": sp, "individual": ind}]).get("winner") == "a"
        except Exception:
            won = True  # don't punish the player if the resolver hiccups
        for b in party_beasts:  # a fight costs the whole party some health either way
            _set_hp(b, _hp_now(b.individual_json or {}) - HP_BATTLE_COST)
        if not won:
            return {"detail": f"{sp.get('name')} bested your team and fled",
                    "beast": None, "caught": False, "fled": True, "battled": True}
        b = _create_beast(node, sp, ind, "wild")
        return {"detail": f"battled & beat {sp.get('name')} [{ind.get('rarity')}] - catch it with a drive",
                "beast": _beast_row(b), "caught": False, "fled": False, "battled": True}
    b = _create_beast(node, sp, ind, "wild")
    return {"detail": f"sighted {sp.get('name')} [{ind.get('rarity')}]",
            "beast": _beast_row(b), "caught": False, "fled": False, "battled": False}
