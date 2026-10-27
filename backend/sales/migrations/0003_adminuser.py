# Generated migration for AdminUser model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0002_remove_saleitem_price_category_size_required_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminUser",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("username", models.CharField(max_length=100, unique=True)),
                ("full_name", models.CharField(blank=True, max_length=150)),
                (
                    "email",
                    models.EmailField(
                        blank=True, max_length=254, null=True, unique=True
                    ),
                ),
                ("password_hash", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
                ("last_password_changed", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Admin User",
                "verbose_name_plural": "Admin Users",
            },
        ),
    ]
