from django import template

from play.names import player_name as _player_name

register = template.Library()


@register.filter
def player_name(user):
    return _player_name(user)


@register.filter
def opponent_label(value):
    """AsyncBattle.opponent is a stored string; rows written before player names were used hold a raw
    Clerk id, so resolve those to the current display name."""
    if isinstance(value, str) and value.startswith("user_"):
        from django.contrib.auth.models import User
        u = User.objects.filter(username=value).only("username", "first_name", "email").first()
        return _player_name(u) if u else "Trainer " + value[-4:]
    return value
