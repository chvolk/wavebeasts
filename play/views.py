import json
import random

from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import resolver
from .models import InventoryItem, Node, OwnedBeast, Snapshot, Wallet

DRIVE_MULT = {"spark_drive": 1.0, "pulse_drive": 1.5, "surge_drive": 2.5, "nova_drive": 4.0}
RARITY_RESIST = {"common": 1.0, "uncommon": 0.85, "rare": 0.65, "epic": 0.45, "legendary": 0.28}
BOOST_COST_CORES = 1
BOOST_DURATION_SEC = 600


def _wallet(user):
    w, _ = Wallet.objects.get_or_create(user=user)
    return w


# ---- public / auth -------------------------------------------------------------------------------

def landing(request):
    return render(request, "landing.html")


def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            Wallet.objects.get_or_create(user=user)
            InventoryItem.objects.get_or_create(user=user, item_id="spark_drive", defaults={"qty": 3})
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "signup.html", {"form": form})


# ---- account dashboard ---------------------------------------------------------------------------

@login_required
def dashboard(request):
    nodes = list(request.user.nodes.all())
    beasts = list(request.user.beasts.all())
    return render(request, "dashboard.html", {
        "nodes": nodes,
        "owned": [b for b in beasts if b.status == "owned"],
        "wild": [b for b in beasts if b.status == "wild"],
        "wallet": _wallet(request.user),
        "items": list(request.user.items.filter(qty__gt=0)),
    })


@login_required
def node_create(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "node").strip()[:64]
        kind = request.POST.get("kind") or "pc"
        Node.objects.create(user=request.user, name=name, kind=kind)
    return redirect("dashboard")


@login_required
def node_boost(request, node_id):
    node = get_object_or_404(Node, id=node_id, user=request.user)
    w = _wallet(request.user)
    if w.cores >= BOOST_COST_CORES:
        w.cores -= BOOST_COST_CORES
        w.save()
        node.boosted_until = timezone.now() + timezone.timedelta(seconds=BOOST_DURATION_SEC)
        node.save()
    return redirect("dashboard")


@login_required
def catch(request, beast_id):
    beast = get_object_or_404(OwnedBeast, id=beast_id, user=request.user, status="wild")
    drive = request.POST.get("drive", "spark_drive")
    inv = InventoryItem.objects.filter(user=request.user, item_id=drive, qty__gt=0).first()
    if not inv:
        return redirect("dashboard")
    inv.qty -= 1
    inv.save()
    p = 0.4 * DRIVE_MULT.get(drive, 1.0) * (0.2 + 0.8 * 0.5) * RARITY_RESIST.get(beast.rarity, 1.0)
    p = max(0.02, min(0.95, p))
    if random.random() < p:
        beast.status = "owned"
        beast.save()
    return redirect("dashboard")


def sprite(request, beast_id):
    beast = get_object_or_404(OwnedBeast, id=beast_id)
    ind = beast.individual_json
    sp = beast.species_json
    try:
        png = resolver.render(ind.get("palette") or sp.get("sprite_recipe", {}).get("base_palette"),
                              sp.get("sprite_recipe"), bool(ind.get("shiny")))
    except Exception:
        return HttpResponse(status=502)
    resp = HttpResponse(png, content_type="image/png")
    resp["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


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
    detail = ""
    if outcome == "resource":
        _apply_resource(node.user, res)
        detail = res.get("reward_label", "")
    elif outcome == "beast":
        detail = _apply_beast(node, res)
    else:
        detail = res.get("message", "")

    Snapshot.objects.create(node=node, outcome=outcome or "nothing",
                            entropy=res.get("entropy", 0), detail=detail[:200])
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
    sp = res.get("species", {})
    ind = res.get("individual", {})
    owned = OwnedBeast.objects.filter(user=user, status="owned").count()
    status = "owned" if owned == 0 else "wild"  # first ever is free; others must be caught
    OwnedBeast.objects.create(
        user=user, node=node, species_id=sp.get("species_id", ""), id_version=sp.get("id_version", 1),
        name=sp.get("name", "?"), rarity=ind.get("rarity", "common"), shiny=bool(ind.get("shiny")),
        level=ind.get("level", 1), status=status, species_json=sp, individual_json=ind,
    )
    return f"{'caught (free!)' if status == 'owned' else 'sighted'} {sp.get('name')} [{ind.get('rarity')}]"
