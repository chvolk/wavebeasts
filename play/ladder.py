"""Async-PvP ladder resolution, shared by the on-demand view and the passive matchmaker worker."""
import random

from . import resolver
from .models import AsyncBattle, LadderTeam, Wallet

WIN_SHARDS = 10
ELO_K = 24


def _wallet(user):
    w, _ = Wallet.objects.get_or_create(user=user)
    return w


def resolve_match(a, b, initiator=None):
    """Resolve one ladder match between two LadderTeams via the Go resolver: update Elo + W/L, log an
    AsyncBattle for each side (seen only for the initiator, so passive matches show up "while you were
    away"), and pay the winner shards. Returns team a's result ('win'/'loss'/'draw') or None on error."""
    try:
        res = resolver.battle_auto(a.fighters, b.fighters)
    except Exception:
        return None
    winner = res.get("winner")
    a_res = "win" if winner == "a" else ("draw" if winner == "draw" else "loss")
    b_res = {"win": "loss", "loss": "win", "draw": "draw"}[a_res]
    expected = 1.0 / (1.0 + 10 ** ((b.mmr - a.mmr) / 400.0))
    score = 1.0 if a_res == "win" else (0.5 if a_res == "draw" else 0.0)
    delta = round(ELO_K * (score - expected))
    a.mmr += delta
    b.mmr -= delta
    for lt, r in ((a, a_res), (b, b_res)):
        if r == "win":
            lt.wins += 1
        elif r == "loss":
            lt.losses += 1
    a.save(update_fields=["mmr", "wins", "losses", "updated"])
    b.save(update_fields=["mmr", "wins", "losses", "updated"])
    turns = res.get("turns", 0)
    AsyncBattle.objects.create(user=a.user, opponent=b.user.username, result=a_res, mmr_delta=delta, turns=turns, seen=(a.user_id == getattr(initiator, "id", None)))
    AsyncBattle.objects.create(user=b.user, opponent=a.user.username, result=b_res, mmr_delta=-delta, turns=turns, seen=(b.user_id == getattr(initiator, "id", None)))
    winner_user = a.user if a_res == "win" else (b.user if b_res == "win" else None)
    if winner_user:
        w = _wallet(winner_user)
        w.shards += WIN_SHARDS
        w.save(update_fields=["shards"])
    return a_res


def run_round(limit=40):
    """Pair up ladder teams at random and resolve one match per pair. Returns matches played."""
    teams = list(LadderTeam.objects.exclude(fighters=[]).select_related("user"))
    if len(teams) < 2:
        return 0
    random.shuffle(teams)
    played = 0
    for i in range(0, len(teams) - 1, 2):
        if played >= limit:
            break
        if resolve_match(teams[i], teams[i + 1]) is not None:
            played += 1
    return played
