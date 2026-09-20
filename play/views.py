import json
import random
import secrets

import requests

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import buddy as buddymod, ladder, resolver
from .models import (AsyncBattle, Buddy, BattleRecord, InventoryItem, LadderTeam, Node,
                     OwnedBeast, Snapshot, TradeListing, TradeOffer, Wallet)

DRIVE_MULT = {"spark_drive": 1.0, "pulse_drive": 1.5, "surge_drive": 2.5, "nova_drive": 4.0}
RARITY_RESIST = {"common": 1.0, "uncommon": 0.85, "rare": 0.65, "epic": 0.45, "legendary": 0.28}
BOOST_COST_CORES = 1
BOOST_DURATION_SEC = 600
GYM_CODES = ["wb-gym-ember", "wb-gym-tide", "wb-gym-stone"]
FREE_NODE_LIMIT = 1     # a free account can feed itself from one external sensor rig
PAID_NODE_LIMIT = 12    # a paid account's sensor fleet cap


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


def app_version(request):
    """Version manifest the Android app polls to prompt for updates."""
    from . import appversion
    return JsonResponse({
        "version_code": appversion.VERSION_CODE,
        "version_name": appversion.VERSION_NAME,
        "notes": appversion.NOTES,
        "apk_url": request.build_absolute_uri("/download/app.apk"),
    })


def app_apk(request):
    """Serve the APK from wavebeasts.com by streaming the current GitHub release asset through the site.
    A same-origin download with a clean Content-Length avoids the cross-origin signed-URL redirect chain
    that stalls some Android browsers (download 'starts but never finishes')."""
    from django.http import HttpResponse, StreamingHttpResponse
    url = "https://github.com/chvolk/wavebeast/releases/latest/download/wavebeast.apk"
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


def signup(request):
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
def dashboard(request):
    beasts = list(request.user.beasts.all())
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
    return render(request, "nodes.html", {"nodes": list(request.user.nodes.all()), "nav": "nodes"})


@login_required
def node_create(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:256]
        limit = PAID_NODE_LIMIT if _paid(request.user) else FREE_NODE_LIMIT
        if request.user.nodes.count() >= limit:
            request.session["nodes_msg"] = (
                f"Node limit reached ({limit}). Upgrade for up to {PAID_NODE_LIMIT} nodes."
                if not _paid(request.user) else f"Node limit reached ({PAID_NODE_LIMIT}).")
        elif name:
            Node.objects.create(user=request.user, name=name)
    return redirect("nodes")


@login_required
def node_boost(request, node_id):
    node = get_object_or_404(Node, id=node_id, user=request.user)
    if not _paid(request.user):
        request.session["nodes_msg"] = "Node boosts are a paid feature."
        return redirect("nodes")
    w = _wallet(request.user)
    if w.cores >= BOOST_COST_CORES:
        w.cores -= BOOST_COST_CORES
        w.save()
        node.boosted_until = timezone.now() + timezone.timedelta(seconds=BOOST_DURATION_SEC)
        node.save()
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
    incoming = list(TradeOffer.objects.filter(listing__user=request.user, status="pending").select_related("listing__beast", "offered_beast", "from_user"))
    tradeable = [b for b in request.user.beasts.filter(status="owned")
                 if not TradeListing.objects.filter(beast=b, is_open=True).exists()]
    return render(request, "trade.html", {
        "my_listings": my_listings, "market": market, "incoming": incoming,
        "tradeable": tradeable, "nav": "trade",
    })


@login_required
def trade_list_beast(request):
    if request.method == "POST":
        if not _paid(request.user):
            request.session["trade_msg"] = "Trading is a paid feature."
            return redirect("trade")
        beast = get_object_or_404(OwnedBeast, id=request.POST.get("beast_id"), user=request.user, status="owned")
        if not beast.verified:
            request.session["trade_msg"] = "Only verified beasts (caught through a node) can be traded."
        elif not TradeListing.objects.filter(beast=beast, is_open=True).exists():
            TradeListing.objects.create(user=request.user, beast=beast, note=(request.POST.get("note") or "")[:200])
    return redirect("trade")


@login_required
def trade_unlist(request, listing_id):
    TradeListing.objects.filter(id=listing_id, user=request.user).update(is_open=False)
    return redirect("trade")


@login_required
def trade_offer(request, listing_id):
    if not _paid(request.user):
        request.session["trade_msg"] = "Trading is a paid feature."
        return redirect("trade")
    listing = get_object_or_404(TradeListing, id=listing_id, is_open=True)
    beast = get_object_or_404(OwnedBeast, id=request.POST.get("beast_id"), user=request.user, status="owned")
    if not beast.verified:
        request.session["trade_msg"] = "Only verified beasts (caught through a node) can be offered in trade."
    elif listing.user_id != request.user.id:
        TradeOffer.objects.create(listing=listing, from_user=request.user, offered_beast=beast)
    return redirect("trade")


@login_required
def trade_accept(request, offer_id):
    if not _paid(request.user):
        request.session["trade_msg"] = "Trading is a paid feature."
        return redirect("trade")
    offer = get_object_or_404(TradeOffer, id=offer_id, listing__user=request.user, status="pending")
    with transaction.atomic():
        listing = offer.listing
        my_beast = OwnedBeast.objects.select_for_update().get(id=listing.beast_id)
        their_beast = OwnedBeast.objects.select_for_update().get(id=offer.offered_beast_id)
        # swap ownership
        my_beast.user, their_beast.user = offer.from_user, request.user
        my_beast.status = their_beast.status = "owned"
        my_beast.save(update_fields=["user", "status"])
        their_beast.save(update_fields=["user", "status"])
        listing.is_open = False
        listing.save(update_fields=["is_open"])
        offer.status = "accepted"
        offer.save(update_fields=["status"])
        # decline the rest
        listing.offers.filter(status="pending").update(status="declined")
    return redirect("trade")


@login_required
def trade_decline(request, offer_id):
    TradeOffer.objects.filter(id=offer_id, listing__user=request.user, status="pending").update(status="declined")
    return redirect("trade")


# ---- battle --------------------------------------------------------------------------------------

def _fighter(b):
    return {"species": b.species_json, "individual": b.individual_json}


def _team_for(user):
    ids = _wallet(user).team_ids or []
    byid = {str(b.id): b for b in OwnedBeast.objects.filter(user=user, id__in=ids)}
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
        request.session["ladder_msg"] = "On the ladder — other trainers will battle your team while you're away."
    return redirect("battle")


@login_required
def ladder_run(request):
    if not _paid(request.user):
        request.session["ladder_msg"] = "The async ladder is a paid feature."
        return redirect("battle")
    lt = LadderTeam.objects.filter(user=request.user).first()
    if not lt or not lt.fighters:
        request.session["ladder_msg"] = "Enter the ladder first."
        return redirect("battle")
    opponents = list(LadderTeam.objects.exclude(user=request.user).exclude(fighters=[]).select_related("user"))
    if not opponents:
        request.session["ladder_msg"] = "No opponents yet — check back once others join the ladder."
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
        # Only verified beasts fight on the ladder/gyms — no modded stats in competitive play.
        valid = list(OwnedBeast.objects.filter(user=request.user, status="owned", verified=True, id__in=ids).values_list("id", flat=True))
        w = _wallet(request.user)
        w.team_ids = [str(i) for i in valid]
        w.save(update_fields=["team_ids"])
    return redirect("battle")


@login_required
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
    others = list(Wallet.objects.exclude(user=request.user).exclude(team_ids=[]).select_related("user"))
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
    if outcome == "resource":
        _apply_resource(node.user, res)
        detail = res.get("reward_label", "")
    elif outcome == "beast":
        detail = _apply_beast(node, res)
    else:
        detail = res.get("message", "")
    Snapshot.objects.create(node=node, outcome=outcome or "nothing", entropy=res.get("entropy", 0), detail=detail[:200])
    return JsonResponse({"accepted": True, "outcome": outcome, "detail": detail,
                         "entropy": res.get("entropy", 0), "next_snapshot_in": node.min_interval()})


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
    # verified=False: imported beasts carry client-claimed stats, so they're collection-only — never
    # tradeable or laddered. To get a legit tradeable copy, submit the scan via a node (site re-rolls it).
    return JsonResponse({"ok": True, "imported": imported, "skipped": skipped,
                         "note": "imported to your collection (unverified — not tradeable; submit scans via a node for verified beasts)"})


# ---- Buddy API (paid) — the tamagotchi companion custom apps carry -------------------------------
# All state is server-authoritative and node-token authed. Care raises vitals/mood/relationship; while
# slotted, the buddy earns rate-limited away-events (resources/XP) — faster the more it loves you.

def _buddy_auth(request):
    """Returns (node, error_response). Node-token auth + subscription (paid) gate."""
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return None, JsonResponse({"error": "bad node token"}, status=403)
    if not _wallet(node.user).subscribed:
        return None, JsonResponse({"error": "the Buddy system is a paid feature", "code": "paywall"}, status=402)
    return node, None


@csrf_exempt
def api_buddy(request):
    """GET the current buddy + any away-events accrued since the last poll (server-rolled, rate-limited)."""
    node, err = _buddy_auth(request)
    if err:
        return err
    b, _ = Buddy.objects.get_or_create(user=node.user)
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
def api_buddy_slot(request):
    """Slot a verified owned beast as the account's one buddy."""
    node, err = _buddy_auth(request)
    if err:
        return err
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "bad json"}, status=400)
    beast = OwnedBeast.objects.filter(id=data.get("beast_id"), user=node.user, status="owned").first()
    if not beast:
        return JsonResponse({"error": "no such owned beast"}, status=404)
    if not beast.verified:
        return JsonResponse({"error": "a buddy must be a verified beast (caught through a node)"}, status=403)
    b, _ = Buddy.objects.get_or_create(user=node.user)
    b.beast = beast
    b.carrier = node  # this device is now carrying the buddy
    b.slotted_at = timezone.now()
    b.last_event_at = timezone.now()  # start the away-event clock fresh on slot
    b.save()
    return JsonResponse({"ok": True, "buddy": buddymod.state(b)})


@csrf_exempt
def api_buddy_care(request):
    """Apply a care action (feed/play/rest/clean/train) to the slotted buddy."""
    node, err = _buddy_auth(request)
    if err:
        return err
    b, _ = Buddy.objects.get_or_create(user=node.user)
    if not b.beast_id:
        return JsonResponse({"error": "no buddy slotted"}, status=409)
    b.carrier = node  # caring for it from this device → it's the carrier
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


def _apply_beast(node, res):
    user = node.user
    sp, ind = res.get("species", {}), res.get("individual", {})
    owned = OwnedBeast.objects.filter(user=user, status="owned").count()
    status = "owned" if owned == 0 else "wild"
    OwnedBeast.objects.create(
        user=user, node=node, species_id=sp.get("species_id", ""), id_version=sp.get("id_version", 1),
        name=sp.get("name", "?"), rarity=ind.get("rarity", "common"), shiny=bool(ind.get("shiny")),
        level=ind.get("level", 1), status=status, verified=True, species_json=sp, individual_json=ind)
    return f"{'caught (free)' if status == 'owned' else 'sighted'} {sp.get('name')} [{ind.get('rarity')}]"
