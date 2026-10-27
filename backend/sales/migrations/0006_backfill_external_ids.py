"""
Backfill unique UUIDs for the new `external_id` columns added in 0005,
then enforce the UNIQUE constraint.

Needed because a callable default (uuid.uuid4) cannot be guaranteed unique
for pre-existing rows added via a plain AddField migration.
"""

import uuid

from django.db import migrations, models

TABLES = ["adminuser", "category", "item", "sale", "saleitem"]


def backfill_external_ids(apps, schema_editor):
    # Overwrite external_id for EVERY row. 0005's callable SQL default may have
    # assigned one shared value to all existing rows, and nothing references
    # these UUIDs yet, so regenerating them is safe and guarantees uniqueness.
    for table in TABLES:
        model = apps.get_model("sales", model_name_switch(table))
        for pk in model.objects.values_list("pk", flat=True):
            model.objects.filter(pk=pk).update(external_id=uuid.uuid4())


def model_name_switch(table):
    names = {
        "adminuser": "AdminUser",
        "saleitem": "SaleItem",
    }
    return names.get(table, table[:1].upper() + table[1:])


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0005_rename_last_updated_at_item_updated_at_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_external_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="adminuser",
            name="external_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="category",
            name="external_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="item",
            name="external_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="sale",
            name="external_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name="saleitem",
            name="external_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]