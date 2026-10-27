"""
Django signals for the sales app.
"""

import os

from django.db.models.signals import post_migrate
from django.dispatch import receiver

from sales.models import AdminUser


@receiver(post_migrate)
def create_default_admin(sender, **kwargs):
    """
    Optionally bootstrap one admin user after migrations.
    This only runs when bootstrap environment variables are provided.
    """
    if sender.name != "sales":
        return

    bootstrap_username = os.getenv("NASS_BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_password = os.getenv("NASS_BOOTSTRAP_ADMIN_PASSWORD")
    bootstrap_email = os.getenv("NASS_BOOTSTRAP_ADMIN_EMAIL", "admin@nasimango.local")

    if not bootstrap_username or not bootstrap_password:
        return

    if AdminUser.objects.filter(username=bootstrap_username).exists():
        print(f"Bootstrap admin user '{bootstrap_username}' already exists")
        return

    admin = AdminUser.objects.create(
        username=bootstrap_username,
        full_name="System Administrator",
        email=bootstrap_email,
        is_active=True,
    )
    admin.set_password(bootstrap_password)
    admin.save()
    print(f"Bootstrap admin user created: username='{bootstrap_username}'")
