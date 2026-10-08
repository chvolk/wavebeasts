import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.db import transaction
from .models import Node, OwnedBeast, Wallet
from . import journals, node_health


def account(request):
    token = request.headers.get("X-WB-Node-Token", "")
    if token:
        node = Node.objects.select_related("user").filter(token=token).first()
        return node.user if node else None
    return request.user if request.user.is_authenticated else None


def private(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@require_GET
def health(request):
    user = account(request)
    if not user:
        return private({"error": "Sign in or supply a valid node token"}, 403)
    return private({"nodes": [node_health.row(n) for n in user.nodes.all()]})


def entries(user, query):
    rows = user.activity_entries.all()
    try:
        before = max(0, int(query.get("before", 0)))
    except (ValueError, TypeError):
        before = 0
    if before:
        rows = rows.filter(id__lt=before)
    kind = query.get("kind", "")
    if kind:
        rows = rows.filter(kind=kind[:32])
    rows = list(rows[:21])
    more = len(rows) > 20
    rows = rows[:20]
    return {
        "entries": [
            {
                "id": e.id,
                "at": e.at.isoformat(),
                "kind": e.kind,
                "summary": e.summary,
                "source": e.source,
                "changes": e.changes,
                "balances": e.balances,
            }
            for e in rows
        ],
        "next_before": rows[-1].id if rows and more else None,
    }


@require_GET
def api_activity(request):
    user = account(request)
    if not user:
        return private({"error": "Sign in or supply a valid node token"}, 403)
    return private(entries(user, request.GET))


@login_required
def activity(request):
    return render(request, "activity.html", {"nav": "activity"})


@login_required
@transaction.atomic
def journal(request, beast_id):
    if request.method == "POST":
        Wallet.objects.select_for_update().filter(user=request.user).first()
    beast = get_object_or_404(
        OwnedBeast, user=request.user, pk=beast_id, status="owned"
    )
    if request.method == "POST":
        beast.favorite = request.POST.get("favorite") == "on"
        beast.field_notes = request.POST.get("notes", "")[:280]
        beast.save(update_fields=["favorite", "field_notes"])
        return redirect("beast_journal", beast_id=beast.pk)
    return render(
        request,
        "journal.html",
        {"beast": beast, "journal": journals.profile(beast), "nav": "beastiary"},
    )


@csrf_exempt
@require_POST
@transaction.atomic
def api_profile(request):
    # Token-only writes: browser forms use CSRF-protected journal view.
    node = Node.objects.filter(token=request.headers.get("X-WB-Node-Token", "")).first()
    if not node:
        return private({"error": "bad node token"}, 403)
    try:
        data = json.loads(request.body)
        beast_id = int(data["beast_id"])
        if "nickname" in data and (
            not isinstance(data["nickname"], str) or len(data["nickname"]) > 24
        ):
            raise ValueError()
        if "favorite" in data and not isinstance(data["favorite"], bool):
            raise ValueError()
        if "notes" in data and (
            not isinstance(data["notes"], str) or len(data["notes"]) > 280
        ):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        return private(
            {
                "error": "Provide beast_id, boolean favorite and notes up to 280 characters"
            },
            400,
        )
    Wallet.objects.select_for_update().filter(user=node.user).first()
    beast = get_object_or_404(
        OwnedBeast.objects.select_for_update(),
        user=node.user,
        pk=beast_id,
        status="owned",
    )
    if "favorite" in data:
        beast.favorite = data["favorite"]
    if "notes" in data:
        beast.field_notes = data["notes"]
    if "nickname" in data:
        beast.individual_json = dict(beast.individual_json or {})
        beast.individual_json["nickname"] = data["nickname"].strip()
    beast.save(update_fields=["favorite", "field_notes", "individual_json"])
    return private({"ok": True, "journal": journals.profile(beast)})
