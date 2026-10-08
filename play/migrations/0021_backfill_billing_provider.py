from django.db import migrations


def backfill(apps, schema_editor):
    """Wallets subscribed through Stripe before billing_provider existed were left at "". Mark them so
    the Play/Stripe exclusivity check sees them (a Play purchase on top would double-bill)."""
    Wallet = apps.get_model("play", "Wallet")
    Wallet.objects.filter(subscribed=True, billing_provider="").exclude(stripe_customer_id="").update(billing_provider="stripe")


class Migration(migrations.Migration):
    dependencies = [("play", "0020_wallet_play_billing")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
