from .models import Wallet


def wallet(request):
    """Expose the signed-in user's wallet to every template (nav balances)."""
    if request.user.is_authenticated:
        w, _ = Wallet.objects.get_or_create(user=request.user)
        return {"wb_wallet": w}
    return {}
