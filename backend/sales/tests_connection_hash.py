"""Connection-hash tests: server-issued hashes, pairing, rebinding, revocation.

Single server, single shop. The operator generates a hash from a Bash console;
a desktop pairs with server URL + hash (plus its own auto-sent admin identity).
The hash is reusable — reconnecting (even from another computer) always
resolves to the same AdminUser — and only revoked hashes stop working.
"""

import io

from django.contrib.auth.hashers import check_password, make_password
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from sales.models import ROLE_ADMIN, AdminUser, ApiToken, AuditLog, ConnectionCredential


def _issue(label="Desktop"):
    out = io.StringIO()
    call_command("generate_connection_hash", label=label, stdout=out)
    raw = out.getvalue()
    return "NASS-" + raw.split(f"    NASS-")[1].split()[0]


def _pair(self, raw, username="desk-admin", password_hash="", device_name=""):
    body = {"hash": raw, "username": username, "device_name": device_name}
    if password_hash:
        body["password_hash"] = password_hash
    return self.client.post(reverse("api-pair"), body, format="json")


class GenerateConnectionHashCommandTests(TestCase):
    def test_command_prints_raw_hash_once_and_stores_hash(self):
        out = io.StringIO()
        call_command("generate_connection_hash", label="My Shop", stdout=out)
        raw = "NASS-" + out.getvalue().split(f"    NASS-")[1].split()[0]

        self.assertTrue(raw.startswith("NASS-"))
        self.assertEqual(len(raw), len("NASS-") + 18)

        credential = ConnectionCredential.objects.get()
        self.assertEqual(credential.label, "My Shop")
        self.assertTrue(check_password(raw, credential.code_hash))
        self.assertFalse(credential.used_at)
        self.assertFalse(credential.revoked_at)
        self.assertEqual(credential.status, "available")
        self.assertTrue(credential.is_valid)

    def test_command_list_and_revoke(self):
        out = io.StringIO()
        call_command("generate_connection_hash", label="A", stdout=out)
        cred = ConnectionCredential.objects.get()
        call_command("generate_connection_hash", "--list", stdout=out)
        self.assertIn("A", out.getvalue())

        err = io.StringIO()
        call_command("generate_connection_hash", "--revoke", cred.pk, stdout=err)
        cred.refresh_from_db()
        self.assertTrue(cred.revoked_at)
        self.assertFalse(cred.is_valid)
        self.assertEqual(cred.status, "revoked")


class PairViewTests(APITestCase):
    def test_first_pair_creates_account_and_token(self):
        raw = _issue()
        resp = _pair(self, raw, username="desktop-pc", device_name="POS-1")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.data["token"])
        self.assertTrue(resp.data["device_id"])

        credential = ConnectionCredential.objects.get()
        admin = credential.admin_user
        self.assertIsNotNone(admin)
        self.assertEqual(admin.username, "desktop-pc")
        self.assertEqual(admin.role, ROLE_ADMIN)
        self.assertTrue(admin.is_active)
        self.assertTrue(admin.password_hash)
        self.assertFalse(admin.password_hash.startswith("desktop-pc"))
        self.assertTrue(credential.used_at)
        self.assertEqual(credential.status, "paired")
        self.assertEqual(ApiToken.objects.filter(user=admin).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="pair", user=admin).exists())

    def test_pair_is_anonymous(self):
        raw = _issue()
        resp = _pair(self, raw)
        self.assertEqual(resp.status_code, 200)

    def test_bad_hash_rejected(self):
        resp = _pair(self, "NASS-NOTAREALHASH")
        self.assertEqual(resp.status_code, 403)

    def test_reuse_binds_same_account_and_rotates_token(self):
        raw = _issue()
        first = _pair(self, raw, username="main-pc", password_hash="hashA")
        self.assertEqual(first.status_code, 200)
        admin = ConnectionCredential.objects.get().admin_user

        second = _pair(self, raw, username="main-pc", password_hash="hashB", device_name="POS-2")
        self.assertEqual(second.status_code, 200)
        admin.refresh_from_db()
        self.assertEqual(admin.password_hash, "hashB")
        self.assertEqual(ApiToken.objects.filter(user=admin).count(), 2)

    def test_reuse_from_other_computer_continues_same_account(self):
        raw = _issue()
        first = _pair(self, raw, username="shared-pc", device_name="Front desk")
        admin = ConnectionCredential.objects.get().admin_user

        second = _pair(self, raw, username="shared-pc", device_name="Store room")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ConnectionCredential.objects.get().admin_user.pk, admin.pk)

    def test_new_hash_is_a_new_account(self):
        raw1 = _issue()
        raw2 = _issue()
        r1 = _pair(self, raw1, username="pc-one")
        r2 = _pair(self, raw2, username="pc-two")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        users = AdminUser.objects.filter(username__in=["pc-one", "pc-two"])
        self.assertEqual(users.count(), 2)

    def test_first_pair_with_taken_username_conflicts(self):
        AdminUser.objects.create(username="taken", is_active=True)
        raw = _issue()
        resp = _pair(self, raw, username="taken")
        self.assertEqual(resp.status_code, 409)

    def test_reuse_renames_username_if_free(self):
        raw = _issue()
        first = _pair(self, raw, username="old-name")
        self.assertEqual(first.status_code, 200)
        second = _pair(self, raw, username="new-name")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ConnectionCredential.objects.get().admin_user.username, "new-name")

    def test_revoked_hash_rejected(self):
        raw = _issue()
        cred = ConnectionCredential.objects.get()
        cred.revoked_at = "2026-01-01T00:00:00Z"
        cred.save()
        resp = _pair(self, raw)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(ConnectionCredential.objects.get().is_valid)

    def test_pair_requires_hash_and_username(self):
        resp = self.client.post(reverse("api-pair"), {}, format="json")
        self.assertEqual(resp.status_code, 400)


class PairedAccountFlowTests(TestCase):
    """After pairing, the created account must work with the normal website
    login and pull endpoint."""

    def setUp(self):
        from django.utils import timezone

        self.admin = AdminUser.objects.create(
            username="paired-user",
            full_name="Paired Admin",
            is_active=True,
            role=ROLE_ADMIN,
        )
        self.admin.set_password("topsecret")
        self.admin.save(update_fields=["password_hash", "last_password_changed"])
        self.credential = ConnectionCredential.objects.create(
            label="Desktop",
            code_hash=make_password("NASS-K"),
            admin_user=self.admin,
            used_at=timezone.now(),
        )

    def test_paired_account_can_log_in_on_website(self):
        from sales.admin_auth import AdminAuthManager

        user = AdminAuthManager.authenticate_admin("paired-user", "topsecret")
        self.assertIsNotNone(user)
        self.assertEqual(user, self.admin)

    def test_pull_with_issued_token_works(self):
        import secrets

        token = ApiToken.objects.create(
            user=self.admin, token=secrets.token_hex(32)
        )
        resp = self.client.post(
            reverse("api-sync-pull"),
            {"device_name": "Desk-1"},
            HTTP_AUTHORIZATION=f"Token {token.token}",
        )
        self.assertEqual(resp.status_code, 200)