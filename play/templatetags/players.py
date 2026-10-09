from django import template

from play.names import player_name as _player_name

register = template.Library()


@register.filter
def player_name(user):
    return _player_name(user)
