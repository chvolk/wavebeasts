from django.conf import settings

from .clerkauth import frontend_api_host
from .models import Wallet


def wallet(request):
    """Expose the signed-in user's wallet + Clerk frontend config to every template (nav, auth widgets)."""
    ctx = {"clerk_pk": settings.CLERK_PUBLISHABLE_KEY, "clerk_host": frontend_api_host(),
           "public_site_url": settings.SITE_URL.rstrip("/")}
    if request.user.is_authenticated:
        w, _ = Wallet.objects.get_or_create(user=request.user)
        ctx["wb_wallet"] = w
        from .client_updates import status
        updates=[status(node) for node in request.user.nodes.all()]
        ctx["wb_updates_required"]=sum(bool(u.get("update_required")) for u in updates)
        ctx["wb_updates_attention"]=sum(bool(u.get("update_available") or u.get("unknown")) for u in updates)
    return ctx
