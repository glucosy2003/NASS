"""Generate / inspect server connection hashes for the desktop app.

Usage on the server (PythonAnywhere Bash console):

    python manage.py generate_connection_hash --label "Shop PC"
    python manage.py generate_connection_hash --list
    python manage.py generate_connection_hash --revoke <id>

The raw hash is printed exactly once. Only a salted hash is stored in the
database, so the raw value can never be recovered. The hash is NOT consumed on
first use — it can be pasted into another desktop later and will reconnect to
the same account so syncing continues seamlessly. Revoke stops it for good.
"""

import secrets

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.utils import timezone

from sales.models import ConnectionCredential


class Command(BaseCommand):
    help = "Generate or manage desktop connection hashes."

    def add_arguments(self, parser):
        parser.add_argument("--label", type=str, default="Desktop")
        parser.add_argument("--list", action="store_true", help="List all hashes")
        parser.add_argument(
            "--revoke", type=int, metavar="ID", help="Revoke a hash by id"
        )

    def handle(self, *args, **options):
        if options["revoke"]:
            self._revoke(options["revoke"])
            return
        if options["list"]:
            self._list()
            return
        self._generate(options["label"])

    def _generate(self, label):
        raw = f"NASS-{secrets.token_hex(9).upper()}"
        ConnectionCredential.objects.create(
            label=(label or "Desktop").strip()[:150], code_hash=make_password(raw)
        )
        self.stdout.write(self.style.SUCCESS("New connection hash created:"))
        self.stdout.write("")
        self.stdout.write(f"    {raw}")
        self.stdout.write("")
        self.stdout.write(
            "Shown ONCE. Copy it now — it is NOT stored again. Paste it into "
            "the desktop's Sync Settings > Connection Hash."
        )

    def _list(self):
        rows = ConnectionCredential.objects.order_by("-created_at")
        if not rows:
            self.stdout.write("No connection hashes yet.")
            return
        self.stdout.write("ID  Label        Status      Used               Created")
        for c in rows:
            used = (c.used_at or "").strftime("%Y-%m-%d %H:%M") if c.used_at else "-"
            created = timezone.localtime(c.created_at).strftime(
                "%Y-%m-%d %H:%M"
            )
            self.stdout.write(
                f"{c.pk:<4}{c.label[:12]:<14}{c.status:<13}{used:<20}{created}"
            )
        self.stdout.write("")
        self.stdout.write(
            "Reuse a hash by pasting it into another desktop — it always "
            "reconnects to the same account."
        )

    def _revoke(self, credential_id):
        credential = ConnectionCredential.objects.filter(pk=credential_id).first()
        if credential is None:
            self.stderr.write(f"No hash with id {credential_id}.")
            return
        if credential.revoked_at:
            self.stdout.write(f"Hash {credential_id} already revoked.")
            return
        credential.revoked_at = timezone.now()
        credential.save(update_fields=["revoked_at"])
        self.stdout.write(
            self.style.WARNING(f"Hash {credential_id} revoked ({credential.label}).")
        )