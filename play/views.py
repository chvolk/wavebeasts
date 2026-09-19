import json
import random

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import resolver
from .models import (BattleRecord, InventoryItem, Node, OwnedBeast, Snapshot,
                     TradeListing, TradeOffer, Wallet)

DRIVE_MULT = {"spark_drive": 1.0, "pulse_drive": 1.5, "surge_drive": 2.5, "nova_drive": 4.0}
RARITY_RESIST = {"common": 1.0, "uncommon": 0.85, "rare": 0.65, "epic": 0.45, "legendary": 0.28}
BOOST_COST_CORES = 1
BOOST_DURATION_SEC = 600
GYM_CODES = ["wb-gym-ember", "wb-gym-tide", "wb-gym-stone"]


def _wallet(user):
    w, _ = Wallet.objects.get_or_create(user=user)
    return w


# ---- public / auth -------------------------------------------------------------------------------

def landing(request):
    return render(request, "landing.html")


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
        if name:
            Node.objects.create(user=request.user, name=name)
    return redirect("nodes")


@login_required
def node_boost(request, node_id):
    node = get_object_or_404(Node, id=node_id, user=request.user)
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
        beast = get_object_or_404(OwnedBeast, id=request.POST.get("beast_id"), user=request.user, status="owned")
        if not TradeListing.objects.filter(beast=beast, is_open=True).exists():
            TradeListing.objects.create(user=request.user, beast=beast, note=(request.POST.get("note") or "")[:200])
    return redirect("trade")


@login_required
def trade_unlist(request, listing_id):
    TradeListing.objects.filter(id=listing_id, user=request.user).update(is_open=False)
    return redirect("trade")


@login_required
def trade_offer(request, listing_id):
    listing = get_object_or_404(TradeListing, id=listing_id, is_open=True)
    beast = get_object_or_404(OwnedBeast, id=request.POST.get("beast_id"), user=request.user, status="owned")
    if listing.user_id != request.user.id:
        TradeOffer.objects.create(listing=listing, from_user=request.user, offered_beast=beast)
    return redirect("trade")


@login_required
def trade_accept(request, offer_id):
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
    return render(request, "battle.html", {
        "owned": owned, "team_ids": team_ids, "result": result,
        "records": list(request.user.battles.all()[:8]), "nav": "battle",
    })


@login_required
def set_team(request):
    if request.method == "POST":
        ids = request.POST.getlist("beast_ids")[:3]
        valid = list(OwnedBeast.objects.filter(user=request.user, status="owned", id__in=ids).values_list("id", flat=True))
        w = _wallet(request.user)
        w.team_ids = [str(i) for i in valid]
        w.save(update_fields=["team_ids"])
    return redirect("battle")


@login_required
def battle_fight(request):
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
        res = resolver.generate(bundle)
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
        level=ind.get("level", 1), status=status, species_json=sp, individual_json=ind)
    return f"{'caught (free)' if status == 'owned' else 'sighted'} {sp.get('name')} [{ind.get('rarity')}]"
