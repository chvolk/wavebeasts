"""Player display names. Django usernames are Clerk subject ids (user_...), so anything shown to other
players goes through player_name, which prefers the synced Clerk name and never shows the raw id."""


def player_name(user):
    if user is None:
        return ""
    name = (user.first_name or "").strip()
    if name:
        return name
    if user.email:
        return user.email.split("@")[0]
    if user.username.startswith("user_"):
        return "Trainer " + user.username[-4:]
    return user.username
