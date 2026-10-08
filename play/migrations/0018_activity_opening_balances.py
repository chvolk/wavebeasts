from django.db import migrations


def opening(apps, schema_editor):
    Wallet = apps.get_model("play", "Wallet")
    Item = apps.get_model("play", "InventoryItem")
    Entry = apps.get_model("play", "ActivityEntry")
    for wallet in Wallet.objects.all().iterator():
        balances = {"shards": wallet.shards, "cores": wallet.cores}
        balances.update(
            {
                "item:" + item.item_id: item.qty
                for item in Item.objects.filter(user_id=wallet.user_id)
            }
        )
        Entry.objects.create(
            user_id=wallet.user_id,
            kind="opening",
            summary="History started — existing balances",
            source="Account",
            balances=balances,
            changes={},
        )


class Migration(migrations.Migration):
    dependencies = [("play", "0017_node_failures_node_heartbeat_sec_and_more")]
    operations = [migrations.RunPython(opening, migrations.RunPython.noop)]
