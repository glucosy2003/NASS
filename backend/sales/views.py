"""
REST API views for the NASS central server.

Endpoints (all under /api/):
    auth      POST login, POST logout
    health    GET health
    categories  GET/POST list, GET/PATCH/DELETE detail
    items       GET/POST list, GET/PATCH/DELETE detail, POST stock adjust
    sales       GET list, POST create
    sync        POST pull, POST push
    users       GET/POST list, GET/PATCH detail   (admin only)
    auditlog    GET list                          (admin only)
"""

import secrets
from uuid import UUID, uuid4

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
    get_object_or_404,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from sales.admin_auth import AdminAuthManager
from sales.authentication import TokenAuthentication
from sales.models import (
    ROLE_ADMIN,
    AdminUser,
    ApiToken,
    AuditLog,
    Category,
    ConnectionCredential,
    Item,
    Sale,
    SaleItem,
    StockAdjustment,
    SyncLog,
    record_opening_stock,
    record_sale_restore,
    record_sale_stock,
)
from sales.permissions import IsAdmin, IsAuthenticatedUser, ReadOnlyBoth
from sales.serializers import (
    AdminUserCreateSerializer,
    AdminUserSerializer,
    AdminUserUpdateSerializer,
    CategorySerializer,
    ItemSerializer,
    ItemUpdateSerializer,
    LoginSerializer,
    SaleCreateSerializer,
)
from sales.sync import _iso, apply_changes, collect_changes, sale_to_dict


def _include_cost(user):
    """Cashiers never receive cost/profit data over the API."""
    return user.role == ROLE_ADMIN


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {"status": "ok", "service": "nass-api", "time": _iso(timezone.now())}
        )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = AdminAuthManager.authenticate_admin(
            data["username"], data["password"]
        )
        if user is None:
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if user.deleted:
            return Response(
                {"detail": "Account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        device_name = data.get("device_name") or ""
        api_token = ApiToken.objects.create(
            user=user, token=secrets.token_hex(32), device_name=device_name
        )
        SyncLog.objects.get_or_create(
            user=user,
            device_id=api_token.device_id,
            defaults={"device_name": device_name},
        )
        AuditLog.record(
            user=user,
            action="login",
            entity="user",
            entity_external_id=user.external_id,
            device_id=api_token.device_id,
            details=f"Device: {device_name or '-'}",
        )

        return Response(
            {
                "token": api_token.token,
                "device_id": str(api_token.device_id),
                "user": AdminAuthManager.get_admin_info(user),
            },
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        token = request.auth
        if token is not None:
            AuditLog.record(
                user=request.user,
                action="logout",
                entity="user",
                entity_external_id=request.user.external_id,
                device_id=token.device_id,
                details=f"Device: {token.device_name or '-'}",
            )
            token.revoked = True
            token.save(update_fields=["revoked"])
        return Response({"detail": "Logged out."})


# ---------------------------------------------------------------------------
# Pairing (server-issued connection credentials)
# ---------------------------------------------------------------------------


class PairView(APIView):
    """Bind a desktop to a server account using a connection hash printed by
    ``python manage.py generate_connection_hash``.

    Request body:
        hash            the connection hash from the console (required)
        username        the desktop's NASS admin username (required)
        password_hash   the desktop admin's current password hash so web
                        login accepts the same credentials as the desktop
        device_name     optional device label

    The hash is never consumed: it can be re-used to reconnect — even from
    another computer — and always resolves to the same AdminUser, so syncing
    continues seamlessly. Only revoked hashes are rejected.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        data = request.data or {}
        raw_hash = str(data.get("hash") or "").strip()
        username = (data.get("username") or "").strip()
        device_name = (data.get("device_name") or "").strip()
        password_hash = (data.get("password_hash") or "").strip()
        if not raw_hash or not username:
            return Response(
                {"detail": "Connection hash and username are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        credential = None
        for candidate in ConnectionCredential.objects.filter(revoked_at__isnull=True):
            if check_password(raw_hash, candidate.code_hash):
                credential = candidate
                break
        if credential is None:
            return Response(
                {"detail": "Invalid or revoked connection hash."},
                status=status.HTTP_403_FORBIDDEN,
            )

        admin = credential.admin_user
        if admin is None:
            if AdminUser.objects.filter(username=username).exists():
                return Response(
                    {"detail": f"Username '{username}' is already taken."},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                admin = AdminUser.objects.create(
                    username=username,
                    full_name=(
                        credential.label
                        if credential.label and credential.label != "Desktop"
                        else ""
                    ),
                    password_hash=password_hash or make_password(
                        secrets.token_urlsafe(24)
                    ),
                    role=ROLE_ADMIN,
                    is_active=True,
                )
            except Exception as exc:  # noqa: BLE001
                return Response(
                    {"detail": f"Could not create account: {exc}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            credential.admin_user = admin
            credential.save(update_fields=["admin_user"])
        else:
            # Reconnect (same or another computer): continue the SAME account.
            if password_hash:
                admin.password_hash = password_hash
            if admin.username != username and not AdminUser.objects.filter(
                username=username
            ).exclude(pk=admin.pk).exists():
                admin.username = username
            admin.is_active = True
            admin.deleted = False
            admin.role = ROLE_ADMIN
            admin.save()

        credential.used_at = timezone.now()
        credential.save(update_fields=["used_at"])

        api_token = ApiToken.objects.create(
            user=admin, token=secrets.token_hex(32), device_name=device_name
        )
        SyncLog.objects.get_or_create(
            user=admin,
            device_id=api_token.device_id,
            defaults={"device_name": device_name},
        )
        AuditLog.record(
            user=admin,
            action="pair",
            entity="user",
            entity_external_id=admin.external_id,
            device_id=api_token.device_id,
            details=f"Device: {device_name or '-'}",
        )

        return Response(
            {
                "detail": "Paired.",
                "token": api_token.token,
                "device_id": str(api_token.device_id),
                "username": admin.username,
            }
        )


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


class CategoryListCreateView(ListCreateAPIView):
    permission_classes = [ReadOnlyBoth]
    serializer_class = CategorySerializer

    def get_queryset(self):
        return Category.objects.filter(deleted=False).order_by("name")

    def perform_create(self, serializer):
        category = serializer.save()
        AuditLog.record(
            user=self.request.user,
            action="create",
            entity="category",
            entity_external_id=category.external_id,
            details=category.name,
        )


class CategoryDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [ReadOnlyBoth]
    serializer_class = CategorySerializer
    lookup_field = "external_id"
    lookup_url_kwarg = "external_id"

    def get_queryset(self):
        return Category.objects.all()

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save(update_fields=["deleted"])
        AuditLog.record(
            user=self.request.user,
            action="delete",
            entity="category",
            entity_external_id=instance.external_id,
            details=instance.name,
        )


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class ItemListCreateView(ListCreateAPIView):
    permission_classes = [ReadOnlyBoth]
    serializer_class = ItemSerializer

    def get_queryset(self):
        return Item.objects.filter(deleted=False).select_related("category")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_cost"] = _include_cost(self.request.user)
        return context

    def perform_create(self, serializer):
        with transaction.atomic():
            item = serializer.save()
            # Opening stock is recorded as a delta so it syncs as part of the
            # single stock ledger (never as an absolute quantity on the row).
            record_opening_stock(item)
        AuditLog.record(
            user=self.request.user,
            action="create",
            entity="item",
            entity_external_id=item.external_id,
            details=f"{item.name}",
        )


class ItemDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [ReadOnlyBoth]
    serializer_class = ItemSerializer
    lookup_field = "external_id"
    lookup_url_kwarg = "external_id"

    def get_queryset(self):
        return Item.objects.all()

    def get_serializer(self, *args, **kwargs):
        kwargs.setdefault("context", super().get_serializer_context())
        return ItemUpdateSerializer(*args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["include_cost"] = _include_cost(self.request.user)
        return context

    def perform_update(self, serializer):
        # Stock cannot be changed through a plain item update; use the stock
        # endpoint (deltas) or sales. This keeps the sync-safe invariant.
        serializer.validated_data.pop("quantity_in_stock", None)
        item = serializer.save()
        AuditLog.record(
            user=self.request.user,
            action="update",
            entity="item",
            entity_external_id=item.external_id,
            details=item.name,
        )

    def perform_destroy(self, instance):
        instance.deleted = True
        instance.save(update_fields=["deleted"])
        AuditLog.record(
            user=self.request.user,
            action="delete",
            entity="item",
            entity_external_id=instance.external_id,
            details=instance.name,
        )


class ItemStockAdjustView(APIView):
    """POST {delta} — admin-only, adjusts stock atomically (additive, safe)."""

    permission_classes = [IsAdmin]

    def post(self, request, external_id):
        item = get_object_or_404(Item, external_id=external_id)
        delta = request.data.get("delta")
        try:
            delta = str(delta).strip()
            from decimal import Decimal as D

            delta = D(delta)
        except Exception:
            return Response(
                {"detail": "delta must be a decimal number."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            Item.objects.filter(pk=item.pk).update(
                quantity_in_stock=F("quantity_in_stock") + delta
            )
            StockAdjustment.objects.create(
                item=item, delta=delta, details="API stock adjust"
            )
        item.refresh_from_db()

        AuditLog.record(
            user=request.user,
            action="stock_adjust",
            entity="item",
            entity_external_id=item.external_id,
            details=f"{item.name}: delta {delta}",
        )
        return Response({"detail": "ok", "quantity_in_stock": str(item.quantity_in_stock)})


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


class SaleListCreateView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def get(self, request):
        include_cost = _include_cost(request.user)
        sales = Sale.objects.order_by("-date")[:200]
        return Response(
            {"sales": [sale_to_dict(s, include_cost=include_cost) for s in sales]}
        )

    def post(self, request):
        # Always know the sale's external_id so we can record its stock deltas
        # here (the originator). The sync engine records sales only; stock
        # changes travel separately as StockAdjustment deltas.
        data = dict(request.data)
        if not str(data.get("external_id") or "").strip():
            data["external_id"] = str(uuid4())
        serializer = SaleCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        payload = {"sales": [serializer.validated_data]}
        report = apply_changes(payload, caller_user=request.user)

        if report["errors"] or report["sales_created"] == 0:
            return Response(
                {"detail": "Sale could not be applied.", "report": report},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sale_external = serializer.validated_data.get("external_id")
        with transaction.atomic():
            sale = Sale.objects.get(external_id=UUID(str(sale_external)))
            # This device is the origin: record the sale's stock deltas once,
            # as deterministic adjustments (identical ids are rebuilt by the
            # sync engine on every other device, so stock never double-counts).
            record_sale_stock(sale)

        AuditLog.record(
            user=request.user,
            action="sale",
            entity="sale",
            entity_external_id=sale_external,
            details="Sale recorded",
        )
        return Response({"detail": "ok", "report": report})


# ---------------------------------------------------------------------------
# Sale detail (delete only)
# ---------------------------------------------------------------------------


class SaleDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request, external_id):
        from sales.models import Sale
        try:
            sale = Sale.objects.get(external_id=UUID(str(external_id)))
        except (Sale.DoesNotExist, ValueError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "external_id": str(sale.external_id),
                "date": _iso(sale.date) if hasattr(sale, 'date') else None,
                "total_amount": str(sale.total_amount),
                "total_profit": str(sale.total_profit),
                "deleted": sale.deleted,
                "items": [
                    {
                        "external_id": str(si.external_id),
                        "item_name": si.item.name,
                        "quantity": str(si.quantity),
                        "selling_price": str(si.selling_price),
                        "cost_price": str(si.cost_price),
                        "profit": str(si.profit),
                    }
                    for si in sale.items.filter(deleted=False).all()
                ],
            }
        )

    def delete(self, request, external_id):
        from sales.models import Sale, SaleItem, StockAdjustment
        try:
            sale = Sale.objects.get(external_id=UUID(str(external_id)))
        except (Sale.DoesNotExist, ValueError):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if sale.deleted:
            return Response(
                {"detail": "Sale already deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            # Deterministic restore deltas (same ids on every device) so a
            # synced delete restores stock exactly once.
            record_sale_restore(sale)
            for si in sale.items.all():
                si.deleted = True
                si.save()
            sale.deleted = True
            sale.save()
        AuditLog.record(
            user=request.user,
            action="delete_sale",
            entity="sale",
            entity_external_id=sale.external_id,
            details=f"Sale #{sale.id} deleted; stock restored",
        )
        return Response({"detail": "Sale deleted. Stock restored."})


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _device_id_from(request):
    """Always use the ApiToken's device_id (UUID) — the request body may
    contain a human-readable name that isn't a valid UUID."""
    return str(request.auth.device_id)


class SyncPullView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        since = request.data.get("since")
        device_id = _device_id_from(request)

        changes = collect_changes(
            since, request.user, include_cost=_include_cost(request.user)
        )

        SyncLog.objects.filter(user=request.user, device_id=device_id).update(
            last_pulled_at=timezone.now()
        )
        return Response({"server_time": _iso(timezone.now()), **changes})


class SyncPushView(APIView):
    permission_classes = [IsAuthenticatedUser]

    def post(self, request):
        report = apply_changes(request.data, caller_user=request.user)
        device_id = _device_id_from(request)
        SyncLog.objects.filter(user=request.user, device_id=device_id).update(
            last_pushed_at=timezone.now()
        )
        return Response({"detail": "ok", "report": report, "server_time": _iso(timezone.now())})


# ---------------------------------------------------------------------------
# Users (admin only)
# ---------------------------------------------------------------------------


class UserListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        users = AdminUser.objects.filter(deleted=False).order_by("username")
        return Response({"users": AdminUserSerializer(users, many=True).data})

    def post(self, request):
        serializer = AdminUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ok, result = AdminAuthManager.create_admin_user(
            username=data["username"],
            full_name=data.get("full_name", ""),
            email=data.get("email") or "",
            password=data["password"],
            role=data["role"],
        )
        if not ok:
            return Response({"detail": result}, status=status.HTTP_400_BAD_REQUEST)
        AuditLog.record(
            user=request.user,
            action="create_user",
            entity="user",
            entity_external_id=result.external_id,
            details=f"{result.username} ({result.role})",
        )
        return Response(AdminUserSerializer(result).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    permission_classes = [IsAdmin]

    def _user(self, external_id):
        try:
            return AdminUser.objects.get(external_id=UUID(str(external_id)))
        except (AdminUser.DoesNotExist, ValueError):
            return None

    def get(self, request, external_id):
        user = self._user(external_id)
        if user is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AdminUserSerializer(user).data)

    def patch(self, request, external_id):
        user = self._user(external_id)
        if user is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = AdminUserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if request.user.pk == user.pk and data.get("is_active") is False:
            return Response(
                {"detail": "You cannot deactivate your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        for field in ("full_name", "email", "role", "is_active"):
            if field in data:
                setattr(user, field, data[field])
        if data.get("password"):
            user.set_password(data["password"])
        user.save()
        AuditLog.record(
            user=request.user,
            action="update_user",
            entity="user",
            entity_external_id=user.external_id,
            details=user.username,
        )
        return Response(AdminUserSerializer(user).data)


# ---------------------------------------------------------------------------
# Audit log (admin only)
# ---------------------------------------------------------------------------


class AuditLogView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        logs = AuditLog.objects.order_by("-created_at")[:200]
        return Response(
            {
                "logs": [
                    {
                        "id": log.id,
                        "time": _iso(log.created_at),
                        "user": log.user.username if log.user else None,
                        "action": log.action,
                        "entity": log.entity,
                        "entity_external_id": str(log.entity_external_id)
                        if log.entity_external_id
                        else None,
                        "device_id": str(log.device_id) if log.device_id else None,
                        "details": log.details,
                    }
                    for log in logs
                ]
            }
        )