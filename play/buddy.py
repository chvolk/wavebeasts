"""Server-authoritative Buddy logic: care effects, vital decay, relationship, and rate-limited away-events.

Everything here mutates the Buddy (and, for training/combat, the beast + wallet) on the server. The client
never sends stats - it calls an action and renders whatever comes back - so the whole system is cheat-proof.
"""
import math
import random
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

# action -> (cooldown minutes, vital/mood effects, relationship gain). Cooldowns keep care from being
# spammed to max instantly, so relationship (and its faster away-events) is earned over real time.
CARE = {
    "feed":  (30, {"hunger": 35, "mood": 8}, 2),
    "play":  (20, {"mood": 18, "energy": -4}, 3),
    "rest":  (45, {"energy": 40, "mood": 6}, 1),
    "clean": (40, {"cleanliness": 45, "mood": 6}, 1),
    "train": (60, {"energy": -10, "mood": 5}, 3),   # also grants XP to the beast (see apply_care)
}
ACTIVITY_MINUTES = {"feed": 2, "play": 5, "rest": 20, "clean": 2, "train": 10}
REST_DECAY_MULTIPLIER = 0.25
VITAL_DECAY_PER_HOUR = {"hunger": 8, "energy": 6, "cleanliness": 5, "mood": 2}

TRAIN_XP = 40           # XP granted per training session
EVENT_CAP = 6           # most away-events handed out in a single poll (bounds long absences)
XP_CURVE_K = 15         # next-level XP = level**3 * K (matches the engine's train curve)


def activity(buddy):
    """The account's current exclusive activity, retained across devices and slot changes."""
    now = timezone.now()
    for action, minutes in ACTIVITY_MINUTES.items():
        started = parse_datetime(buddy.last_care.get(action, "") or "")
        if started:
            ends = started + timedelta(minutes=minutes)
            if ends > now:
                return {"action": action, "ends_at": ends.isoformat(),
                        "remaining_sec": math.ceil((ends - now).total_seconds())}
    return None


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, int(round(v))))


def relationship_label(r):
    return ("loves you" if r >= 100 else "devoted" if r >= 80 else "close" if r >= 60
            else "friendly" if r >= 40 else "warming up" if r >= 20 else "wary")


def event_interval_min(relationship):
    """10 min between away-events at max love, stretching to 60 min at zero relationship."""
    return 10 + (100 - clamp(relationship)) * 0.5


def refresh(buddy):
    """Integrate fractional decay over awake/resting time, independently of polling frequency."""
    now = timezone.now()
    seconds = max(0.0, (now - buddy.refreshed_at).total_seconds())
    if not seconds:
        return
    rest = parse_datetime(buddy.last_care.get("rest", "") or "")
    resting = 0
    if rest:
        resting = max(0, (min(now, rest + timedelta(minutes=ACTIVITY_MINUTES["rest"]))
                          - max(buddy.refreshed_at, rest)).total_seconds())
    hours = (seconds - resting * (1 - REST_DECAY_MULTIPLIER)) / 3600
    for key, rate in VITAL_DECAY_PER_HOUR.items():
        setattr(buddy, key, max(0.0, getattr(buddy, key) - rate * hours))
    buddy.refreshed_at = now


def care_cooldowns(buddy):
    """Effective waits include both each action's cadence and the shared activity lock."""
    now = timezone.now()
    active = activity(buddy)
    shared = active["remaining_sec"] if active else 0
    out = {}
    for action, (cd_min, _, _) in CARE.items():
        last = parse_datetime(buddy.last_care.get(action, "") or "")
        remaining = math.ceil(cd_min * 60 - (now - last).total_seconds()) if last else 0
        out[action] = max(0, shared, remaining)
    return out


def _level_up(ind):
    """Consume XP into levels on an individual dict (in place). Returns levels gained."""
    gained = 0
    while ind.get("level", 1) < 100:
        need = (ind.get("level", 1) ** 3) * XP_CURVE_K
        if ind.get("xp", 0) < need:
            break
        ind["xp"] = ind.get("xp", 0) - need
        ind["level"] = ind.get("level", 1) + 1
        gained += 1
    return gained


def apply_care(buddy, action):
    """Apply a care action. For 'train', pass the beast in via buddy.beast (caller saves it). Returns a
    result dict; on cooldown returns {'error': 'cooldown', 'retry_after_sec': N}."""
    cfg = CARE.get(action)
    if not cfg:
        return {"error": "unknown_action"}
    refresh(buddy)
    _, effects, rel = cfg
    now = timezone.now()
    remaining = care_cooldowns(buddy)[action]
    if remaining:
        return {"error": "cooldown", "retry_after_sec": remaining}
    for k, dv in effects.items():
        setattr(buddy, k, max(0.0, min(100.0, getattr(buddy, k) + dv)))
    buddy.relationship = clamp(buddy.relationship + rel)
    buddy.last_care[action] = now.isoformat()
    result = {"ok": True, "action": action}
    if action == "train" and buddy.beast is not None:
        ind = buddy.beast.individual_json or {}
        ind["xp"] = ind.get("xp", 0) + TRAIN_XP
        levels = _level_up(ind)
        buddy.beast.individual_json = ind
        buddy.beast.level = ind.get("level", buddy.beast.level)
        result["xp_gained"] = TRAIN_XP
        result["levels_gained"] = levels
    return result


# --- away events: server rolls resources / off-screen combat, rate-limited by relationship ------------

def _roll_event(buddy, wallet, beast):
    r = random.random()
    if r < 0.50:
        amt = random.randint(3, 15)
        wallet.shards += amt
        return {"type": "resource", "reward": "shards", "amount": amt,
                "detail": f"{buddy_name(beast)} scavenged {amt} shards while you were away."}
    if r < 0.65:
        wallet.cores += 1
        return {"type": "resource", "reward": "cores", "amount": 1,
                "detail": f"{buddy_name(beast)} turned up a rare core!"}
    if r < 0.90 and beast is not None:
        xp = random.randint(15, 45)
        ind = beast.individual_json or {}
        ind["xp"] = ind.get("xp", 0) + xp
        levels = _level_up(ind)
        beast.individual_json = ind
        beast.level = ind.get("level", beast.level)
        foe = random.choice(["a wild Snapling", "a feral drone", "a rogue signal", "a cave lurker", "a static wisp"])
        d = f"{buddy_name(beast)} defeated {foe} and gained {xp} XP."
        if levels:
            d += f" Reached level {beast.level}!"
        return {"type": "combat", "reward": "xp", "amount": xp, "levels": levels, "detail": d}
    return {"type": "flavor", "detail": f"{buddy_name(beast)} napped in the sun and feels content."}


def buddy_name(beast):
    if beast is None:
        return "Your buddy"
    ind = beast.individual_json or {}
    return ind.get("nickname") or beast.name or "Your buddy"


def accrue_events(buddy, wallet, beast):
    """Grant away-events for time elapsed since the last one, spaced by the relationship-scaled interval
    and capped at EVENT_CAP. Advances last_event_at by whole intervals (partial time carries over)."""
    now = timezone.now()
    if not buddy.last_event_at:
        buddy.last_event_at = now
        return []
    if beast is not None and beast_hp(beast.individual_json or {}) <= 0:
        return []  # a fainted buddy can't scout until it heals
    interval = timedelta(minutes=event_interval_min(buddy.relationship))
    events, n = [], 0
    while now - buddy.last_event_at >= interval and n < EVENT_CAP:
        events.append(_roll_event(buddy, wallet, beast))
        buddy.last_event_at += interval
        buddy.relationship = clamp(buddy.relationship + 1)  # bonding while carried
        interval = timedelta(minutes=event_interval_min(buddy.relationship))
        n += 1
    return events


HP_MAX = 100
HP_REGEN_PER_HOUR = 20.0


def beast_hp(ind):
    """Current health with time-regen (mirrors views._hp_now). A fainted buddy can't scout."""
    base = ind.get("hp")
    base = HP_MAX if base is None else base
    at = parse_datetime(ind.get("hp_at", "") or "")
    if at:
        hrs = max(0.0, (timezone.now() - at).total_seconds() / 3600.0)
        base = min(HP_MAX, base + hrs * HP_REGEN_PER_HOUR)
    return max(0, min(HP_MAX, int(round(base))))


def beast_summary(beast):
    if beast is None:
        return None
    sp = beast.species_json or {}
    ind = beast.individual_json or {}
    hp = beast_hp(ind)
    return {"id": beast.id, "name": beast.name, "rarity": beast.rarity, "shiny": beast.shiny,
            "level": beast.level, "species_id": beast.species_id, "types": sp.get("types", []),
            "nickname": ind.get("nickname", ""), "nature": ind.get("nature", ""),
            "hp": hp, "hp_max": HP_MAX, "fainted": hp <= 0}


def state(buddy):
    return {
        "beast": beast_summary(buddy.beast),
        "carrier": ({"id": buddy.carrier_id, "name": buddy.carrier.name} if buddy.carrier_id else None),
        "mood": clamp(buddy.mood),
        "relationship": buddy.relationship,
        "relationship_label": relationship_label(buddy.relationship),
        "hunger": clamp(buddy.hunger),
        "energy": clamp(buddy.energy),
        "cleanliness": clamp(buddy.cleanliness),
        "event_interval_min": round(event_interval_min(buddy.relationship)),
        "cooldowns": care_cooldowns(buddy),
        "activity": activity(buddy),
        "care_options": {
            action: {"duration_sec": ACTIVITY_MINUTES[action] * 60,
                     "cooldown_sec": cfg[0] * 60, "effects": cfg[1],
                     "relationship_gain": cfg[2],
                     "xp_gain": TRAIN_XP if action == "train" else 0,
                     "decay_multiplier": REST_DECAY_MULTIPLIER if action == "rest" else 1}
            for action, cfg in CARE.items()
        },
    }
