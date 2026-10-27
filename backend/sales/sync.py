"""
Sync engine — the shared, single codebase used by BOTH the central server
(PythonAnywhere + MySQL) and each desktop's own SQLite copy.

Wire-format rule (kept tiny on purpose):
    - every syncable row carries: external_id, updated_at, deleted
    - decimal values travel as STRINGS ("100.50") so there is no float drift
    - all timestamps are ISO-8601 with timezone
    - conflict resolution is simple:
        * categories / items / users -> last-writer-wins by updated_at
        * sales                 -> idempotent by external_id (append-only)
        * stock quantity        -> only ever changes via explicit
                                   stock_adjustments (deltas) or sales
"""

import uuid
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from sales.models import (
    ROLE_ADMIN,
    AdminUser,
    Category,
    Expense,
    Item,
    PartialPayment,
    PaymentRecord,
    Sale,
    SaleItem,
    Service,
    ServiceEntry,
    StockAdjustment,
    record_sale_restore,
    record_sale_stock,
)

# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _dec(value, default=Decimal("0")):
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _now():
    return timezone.now()


# ---------------------------------------------------------------------------
# Serializers (model instance -> wire dict)
# ---------------------------------------------------------------------------


def category_to_dict(cat):
    return {
        "external_id": str(cat.external_id),
        "name": cat.name,
        "size_required": cat.size_required,
        "deleted": cat.deleted,
        "updated_at": _iso(cat.updated_at),
    }


def item_to_dict(item, include_cost=True):
    data = {
        "external_id": str(item.external_id),
        "name": item.name,
        "unit_price": str(item.unit_price),
        "category_external_id": str(item.category.external_id),
        "brand": item.brand or "",
        "size": item.size or "",
        "quantity_in_stock": str(item.quantity_in_stock),
        "deleted": item.deleted,
        "updated_at": _iso(item.updated_at),
    }
    if include_cost:
        data["cost_price"] = str(item.cost_price)
    return data


def saleitem_to_dict(line, include_cost=True):
    data = {
        "external_id": str(line.external_id),
        "item_external_id": str(line.item.external_id),
        "quantity": str(line.quantity),
        "selling_price": str(line.selling_price),
        "deleted": line.deleted,
        "updated_at": _iso(line.updated_at),
    }
    if include_cost:
        data["cost_price"] = str(line.cost_price)
        data["profit"] = str(line.profit)
    return data


def sale_to_dict(sale, include_cost=True):
    data = {
        "external_id": str(sale.external_id),
        "date": _iso(sale.date),
        "total_amount": str(sale.total_amount),
        "deleted": sale.deleted,
        "updated_at": _iso(sale.updated_at),
        "items": [saleitem_to_dict(i, include_cost) for i in sale.items.all()],
    }
    if include_cost:
        data["total_profit"] = str(sale.total_profit)
    return data


def adminuser_to_dict(user):
    return {
        "external_id": str(user.external_id),
        "username": user.username,
        "full_name": user.full_name or "",
        "email": user.email or "",
        "password_hash": user.password_hash,
        "role": user.role,
        "is_active": user.is_active,
        "deleted": user.deleted,
        "desktop_password_required": user.desktop_password_required,
        "updated_at": _iso(user.updated_at),
    }


def stock_adjustment_to_dict(adj):
    return {
        "external_id": str(adj.external_id),
        "item_external_id": str(adj.item.external_id),
        "delta": str(adj.delta),
        "details": adj.details or "",
        "deleted": adj.deleted,
        "updated_at": _iso(adj.updated_at),
    }


def partial_payment_to_dict(pp):
    return {
        "external_id": str(pp.external_id),
        "date": _iso(pp.date),
        "item_external_id": str(pp.item.external_id),
        "quantity": str(pp.quantity),
        "unit_price": str(pp.unit_price),
        "total_amount": str(pp.total_amount),
        "phone": pp.phone or "",
        "customer_name": pp.customer_name or "",
        "collected": pp.collected,
        "deleted": pp.deleted,
        "created_at": _iso(pp.created_at),
        "updated_at": _iso(pp.updated_at),
    }


def payment_record_to_dict(pr):
    return {
        "external_id": str(pr.external_id),
        "date": _iso(pr.date),
        "partial_payment_external_id": str(pr.partial_payment.external_id),
        "amount": str(pr.amount),
        "deleted": pr.deleted,
        "created_at": _iso(pr.created_at),
        "updated_at": _iso(pr.updated_at),
    }


def service_to_dict(service):
    return {
        "external_id": str(service.external_id),
        "name": service.name,
        "price": str(service.price),
        "deleted": service.deleted,
        "updated_at": _iso(service.updated_at),
    }


def service_entry_to_dict(entry):
    return {
        "external_id": str(entry.external_id),
        "service_external_id": str(entry.service.external_id),
        "date": _iso(entry.date),
        "quantity": str(entry.quantity),
        "unit_price": str(entry.unit_price),
        "total_amount": str(entry.total_amount),
        "customer_name": entry.customer_name or "",
        "notes": entry.notes or "",
        "deleted": entry.deleted,
        "updated_at": _iso(entry.updated_at),
    }


def expense_to_dict(expense):
    return {
        "external_id": str(expense.external_id),
        "date": _iso(expense.date),
        "description": expense.description,
        "amount": str(expense.amount),
        "deleted": expense.deleted,
        "updated_at": _iso(expense.updated_at),
    }


# ---------------------------------------------------------------------------
# Collect changes since a timestamp (used by the server for PULL, and by the
# desktop to build its PUSH payload).
# ---------------------------------------------------------------------------


def collect_changes(since, caller_user, include_cost=True):
    since = _parse_dt(since)

    categories = Category.objects.all()
    items = Item.objects.all()
    sales = Sale.objects.all()
    # Users are ALWAYS included (idempotent on the receiving side), so an
    # account whose local updated_at predates the sync cursor still reaches
    # the server. This keeps the website login mirror in step with the
    # desktop ("log in on web with my desktop admin/cashier account").
    users = AdminUser.objects.all()
    stock_adjustments = StockAdjustment.objects.all()
    partial_payments = PartialPayment.objects.all()
    payment_records = PaymentRecord.objects.all()
    services = Service.objects.all()
    service_entries = ServiceEntry.objects.all()
    expenses = Expense.objects.all()

    if since is not None:
        # `gte` (not `gt`): coarse clocks can give identical microsecond
        # timestamps, and re-fetching a row is harmless (push side uses strict
        # `>` LWW so echoes never over-write).
        categories = categories.filter(updated_at__gte=since)
        items = items.filter(updated_at__gte=since)
        sale_ids = set(
            Sale.objects.filter(updated_at__gte=since).values_list("id", flat=True)
        ) | set(
            SaleItem.objects.filter(updated_at__gte=since)
            .values_list("sale_id", flat=True)
        )
        sales = sales.filter(id__in=sale_ids)
        stock_adjustments = stock_adjustments.filter(updated_at__gte=since)
        partial_payment_ids = set(
            PartialPayment.objects.filter(updated_at__gte=since).values_list(
                "id", flat=True
            )
        ) | set(
            PaymentRecord.objects.filter(updated_at__gte=since)
            .values_list("partial_payment_id", flat=True)
        )
        partial_payments = partial_payments.filter(id__in=partial_payment_ids)
        payment_records = payment_records.filter(updated_at__gte=since)
        services = services.filter(updated_at__gte=since)
        service_entry_ids = set(
            ServiceEntry.objects.filter(updated_at__gte=since).values_list(
                "id", flat=True
            )
        ) | set(
            Service.objects.filter(updated_at__gte=since).values_list("id", flat=True)
        )
        service_entries = service_entries.filter(id__in=service_entry_ids)
        expenses = expenses.filter(updated_at__gte=since)

    return {
        "categories": [category_to_dict(c) for c in categories.order_by("updated_at")],
        "items": [item_to_dict(i, include_cost) for i in items.order_by("updated_at")],
        "sales": [sale_to_dict(s, include_cost) for s in sales.order_by("date")],
        "stock_adjustments": [
            stock_adjustment_to_dict(a)
            for a in stock_adjustments.order_by("updated_at")
        ],
        "partial_payments": [
            partial_payment_to_dict(p)
            for p in partial_payments.order_by("updated_at")
        ],
        "payment_records": [
            payment_record_to_dict(r)
            for r in payment_records.order_by("created_at")
        ],
        "services": [service_to_dict(s) for s in services.order_by("updated_at")],
        "service_entries": [
            service_entry_to_dict(e)
            for e in service_entries.order_by("updated_at")
        ],
        "expenses": [expense_to_dict(x) for x in expenses.order_by("updated_at")],
        "users": [adminuser_to_dict(u) for u in users.order_by("updated_at")],
    }


# ---------------------------------------------------------------------------
# Apply changes (used by the server on PUSH, and by the desktop to ingest a
# PULL payload into its local SQLite).
# ---------------------------------------------------------------------------


def _lww_update(instance, incoming_dt):
    """Return True if the incoming change is strictly newer and should apply."""
    existing = instance.updated_at
    if incoming_dt is None:
        return False
    # Reject rows that are not newer than our own copy (kills echoes).
    if existing is not None and incoming_dt <= existing:
        return False
    return True


def apply_changes(payload, caller_user=None):
    """
    Apply a push/pull payload. Returns a report dict of applied counts.
    """
    return _apply_changes(payload, caller_user)


def _apply_changes(payload, caller_user=None):
    """Raw implementation."""
    if caller_user is not None and caller_user.role != ROLE_ADMIN:
        payload = dict(payload)
        for restricted_key in (
            "categories",
            "items",
            "stock_adjustments",
            "services",
            "service_entries",
            "expenses",
            "users",
        ):
            payload[restricted_key] = []

    report = {
        "categories_created": 0,
        "categories_updated": 0,
        "categories_skipped": 0,
        "items_created": 0,
        "items_updated": 0,
        "items_skipped": 0,
        "stock_adjustments": 0,
        "stock_adjustments_skipped": 0,
        "sales_created": 0,
        "sales_skipped": 0,
        "sales_deleted": 0,
        "partial_payments_created": 0,
        "partial_payments_updated": 0,
        "partial_payments_skipped": 0,
        "payment_records_created": 0,
        "payment_records_skipped": 0,
        "services_created": 0,
        "services_updated": 0,
        "service_entries_created": 0,
        "service_entries_skipped": 0,
        "service_entries_deleted": 0,
        "expenses_created": 0,
        "expenses_skipped": 0,
        "users_created": 0,
        "users_updated": 0,
        "users_skipped": 0,
        "errors": [],
    }

    # ---- Categories -------------------------------------------------------
    for raw in payload.get("categories", []):
        try:
            ext_id = raw.get("external_id")
            incoming_dt = _parse_dt(raw.get("updated_at"))
            cat = (
                Category.objects.filter(external_id=ext_id).first()
                if ext_id
                else None
            )
            # A desktop and a server can hold the same category name under a
            # different external_id (each side seeds its own copy). Name is the
            # real key here, so absorb the colliding row instead of hitting the
            # unique constraint on every push forever.
            name_conflict = False
            raw_name = (raw.get("name") or "").strip()
            if cat is None and raw_name:
                cat = Category.objects.filter(name=raw_name).first()
                name_conflict = cat is not None
            if cat is not None and not name_conflict and not _lww_update(cat, incoming_dt):
                report["categories_skipped"] += 1
                continue
            values = {
                "name": raw.get("name", ""),
                "size_required": bool(raw.get("size_required", False)),
                "deleted": bool(raw.get("deleted", False)),
            }
            if cat is None:
                Category.objects.create(external_id=uuid.UUID(ext_id), **values)
                report["categories_created"] += 1
            else:
                for k, v in values.items():
                    setattr(cat, k, v)
                if name_conflict and ext_id:
                    cat.external_id = uuid.UUID(ext_id)
                cat.save()
                report["categories_updated"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"category:{e}")

    # ---- Items ------------------------------------------------------------
    for raw in payload.get("items", []):
        try:
            ext_id = raw.get("external_id")
            incoming_dt = _parse_dt(raw.get("updated_at"))
            item = Item.objects.filter(external_id=ext_id).first() if ext_id else None
            if item is not None and not _lww_update(item, incoming_dt):
                report["items_skipped"] += 1
                continue

            category = None
            cat_ext = raw.get("category_external_id")
            if cat_ext:
                category = Category.objects.filter(external_id=cat_ext).first()
            if category is None:
                report["errors"].append(f"item:{ext_id}: missing category {cat_ext}")
                continue

            values = {
                "category": category,
                "name": raw.get("name", ""),
                "unit_price": _dec(raw.get("unit_price")),
                "cost_price": _dec(raw.get("cost_price"), Decimal("0")),
                "brand": raw.get("brand") or "",
                "size": raw.get("size") or "",
                "deleted": bool(raw.get("deleted", False)),
            }
            if item is None:
                # A brand-new item starts EMPTY on every receiving device. Its
                # opening stock arrives as a StockAdjustment instead, so the
                # full stock ledger replays cleanly (item rows never carry an
                # absolute quantity that could double a delta).
                values["quantity_in_stock"] = Decimal("0")
                Item.objects.create(external_id=uuid.UUID(ext_id), **values)
                report["items_created"] += 1
            else:
                for k, v in values.items():
                    setattr(item, k, v)
                item.save()
                report["items_updated"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"item:{e}")

    # ---- Stock adjustments (immutable, idempotent by external_id) ----------
    with transaction.atomic():
        for adj in payload.get("stock_adjustments", []):
            try:
                ext_id = adj.get("external_id")
                if ext_id and StockAdjustment.objects.filter(
                    external_id=ext_id
                ).exists():
                    report["stock_adjustments_skipped"] += 1
                    continue
                item_ext = adj.get("item_external_id")
                item = (
                    Item.objects.select_for_update()
                    .filter(external_id=item_ext)
                    .first()
                    if item_ext
                    else None
                )
                if item is None:
                    report["errors"].append(f"stock_adjustment: missing item {item_ext}")
                    continue
                # Apply the delta atomically; the item's `updated_at` is left
                # alone on purpose — stock quantity travels via adjustment
                # rows, not item rows (see collect_changes LWW rules).
                delta = _dec(adj.get("delta"))
                Item.objects.filter(pk=item.pk).update(
                    quantity_in_stock=F("quantity_in_stock") + delta
                )
                StockAdjustment.objects.create(
                    external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(),
                    item=item,
                    delta=delta,
                    details=(adj.get("details") or "")[:255],
                    deleted=bool(adj.get("deleted", False)),
                )
                report["stock_adjustments"] += 1
            except Exception as e:  # noqa: BLE001
                report["errors"].append(f"stock_adjustment:{e}")

    # ---- Sales (immutable, idempotent by external_id) ---------------------
    for raw in payload.get("sales", []):
        try:
            ext_id = raw.get("external_id")
            raw_deleted = bool(raw.get("deleted", False))
            if ext_id and Sale.objects.filter(external_id=ext_id).exists():
                if not raw_deleted:
                    report["sales_skipped"] += 1
                    continue
                sale = Sale.objects.get(external_id=ext_id)
                if sale.deleted:
                    report["sales_skipped"] += 1
                    continue
                # Restore stock through the deterministic sale-restore deltas,
                # exactly as the deleting device did. record_sale_restore is
                # idempotent by external_id, so a deleted line is never
                # restored twice across devices.
                with transaction.atomic():
                    record_sale_restore(sale)
                    for si in sale.items.filter(deleted=False):
                        si.deleted = True
                        si.save(update_fields=["deleted", "updated_at"])
                    sale.deleted = True
                    sale.save(update_fields=["deleted", "updated_at"])
                report["sales_deleted"] += 1
                continue

            raw_items = raw.get("items", [])
            if not raw_items:
                report["errors"].append(f"sale:{ext_id}: no items")
                continue

            with transaction.atomic():
                sale = Sale.objects.create(
                    external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(),
                    date=_parse_dt(raw.get("date")) or _now(),
                    total_amount=Decimal("0"),
                    total_profit=Decimal("0"),
                )

                total_amount = Decimal("0")
                total_profit = Decimal("0")
                created_lines = []
                for line in raw_items:
                    item = Item.objects.select_for_update().filter(
                        external_id=line.get("item_external_id")
                    ).first()
                    if item is None:
                        raise ValueError(
                            f"sale {ext_id}: missing item {line.get('item_external_id')}"
                        )
                    quantity = _dec(line.get("quantity"))
                    selling_price = _dec(line.get("selling_price"))
                    # Cost is authoritative on the server: the client's cost is
                    # never trusted (cashier devices have no cost data).
                    cost_price = item.cost_price

                    created_lines.append(
                        SaleItem.objects.create(
                            external_id=(
                                uuid.UUID(line.get("external_id"))
                                if line.get("external_id")
                                else uuid.uuid4()
                            ),
                            sale=sale,
                            item=item,
                            quantity=quantity,
                            selling_price=selling_price,
                            cost_price=cost_price,
                        )
                    )
                    total_amount += selling_price * quantity
                    total_profit += (selling_price - cost_price) * quantity

                sale.total_amount = total_amount
                sale.total_profit = total_profit
                sale.save(update_fields=["total_amount", "total_profit"])
                # Materialize the sale's stock deltas as deterministic
                # adjustments. Idempotent by external_id: when this sale was
                # pushed by an admin, its adjustments arrived in the
                # stock_adjustments step of the same payload and record_sale_stock
                # applies nothing; when pushed by a cashier (whose adjustments
                # are stripped), the deltas are rebuilt here exactly once.
                record_sale_stock(sale, created_lines)
                report["sales_created"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"sale:{e}")

    # ---- Partial payments (LWW on the header, append-only money) ----------
    for raw in payload.get("partial_payments", []):
        try:
            ext_id = raw.get("external_id")
            incoming_dt = _parse_dt(raw.get("updated_at"))
            pp = (
                PartialPayment.objects.filter(external_id=ext_id).first()
                if ext_id
                else None
            )
            if pp is not None and not _lww_update(pp, incoming_dt):
                report["partial_payments_skipped"] += 1
                continue

            item_ext = raw.get("item_external_id")
            item = (
                Item.objects.filter(external_id=item_ext).first() if item_ext else None
            )
            if item is None:
                report["errors"].append(
                    f"partial_payment: missing item {item_ext}"
                )
                continue

            values = {
                "item": item,
                "quantity": _dec(raw.get("quantity"), Decimal("1")),
                "unit_price": _dec(raw.get("unit_price")),
                "total_amount": _dec(raw.get("total_amount")),
                "date": _parse_dt(raw.get("date")) or _now(),
                "phone": (raw.get("phone") or "")[:50],
                "customer_name": (raw.get("customer_name") or "")[:150],
                "collected": bool(raw.get("collected", False)),
                "deleted": bool(raw.get("deleted", False)),
            }
            if pp is None:
                PartialPayment.objects.create(
                    external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(), **values
                )
                report["partial_payments_created"] += 1
            else:
                for k, v in values.items():
                    setattr(pp, k, v)
                pp.save()
                report["partial_payments_updated"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"partial_payment:{e}")

    # ---- Payment records (append-only, idempotent by external_id) ---------
    for raw in payload.get("payment_records", []):
        try:
            ext_id = raw.get("external_id")
            if ext_id and PaymentRecord.objects.filter(external_id=ext_id).exists():
                report["payment_records_skipped"] += 1
                continue

            pp_ext = raw.get("partial_payment_external_id")
            pp = (
                PartialPayment.objects.filter(external_id=pp_ext).first()
                if pp_ext
                else None
            )
            if pp is None:
                report["errors"].append(
                    f"payment_record: missing partial payment {pp_ext}"
                )
                continue

            PaymentRecord.objects.create(
                external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(),
                date=_parse_dt(raw.get("date")) or _now(),
                partial_payment=pp,
                amount=_dec(raw.get("amount")),
                deleted=bool(raw.get("deleted", False)),
            )
            report["payment_records_created"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"payment_record:{e}")

    # ---- Services (catalog, LWW) ---------------------------------------------
    for raw in payload.get("services", []):
        try:
            ext_id = raw.get("external_id")
            incoming_dt = _parse_dt(raw.get("updated_at"))
            service = (
                Service.objects.filter(external_id=ext_id).first()
                if ext_id
                else None
            )
            if service is not None and not _lww_update(service, incoming_dt):
                report["services_skipped"] = report.get("services_skipped", 0) + 1
                continue

            values = {
                "name": (raw.get("name") or "")[:150],
                "price": _dec(raw.get("price"), Decimal("0")),
                "deleted": bool(raw.get("deleted", False)),
            }
            if service is None:
                Service.objects.create(
                    external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(), **values
                )
                report["services_created"] += 1
            else:
                for k, v in values.items():
                    setattr(service, k, v)
                service.save()
                report["services_updated"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"service:{e}")

    # ---- Service entries (income, idempotent) --------------------------------
    for raw in payload.get("service_entries", []):
        try:
            ext_id = raw.get("external_id")
            incoming_deleted = bool(raw.get("deleted", False))
            existing = (
                ServiceEntry.objects.filter(external_id=ext_id).first()
                if ext_id
                else None
            )
            if existing is not None:
                if incoming_deleted and not existing.deleted:
                    existing.deleted = True
                    existing.save(update_fields=["deleted", "updated_at"])
                    report["service_entries_deleted"] = (
                        report.get("service_entries_deleted", 0) + 1
                    )
                else:
                    report["service_entries_skipped"] = (
                        report.get("service_entries_skipped", 0) + 1
                    )
                continue

            service_ext = raw.get("service_external_id")
            service = (
                Service.objects.filter(external_id=service_ext).first()
                if service_ext
                else None
            )
            if service is None:
                report["errors"].append(f"service_entry: missing service {service_ext}")
                continue

            ServiceEntry.objects.create(
                external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(),
                service=service,
                date=_parse_dt(raw.get("date")) or timezone.now(),
                quantity=_dec(raw.get("quantity"), Decimal("1")),
                unit_price=_dec(raw.get("unit_price"), Decimal("0")),
                total_amount=_dec(raw.get("total_amount"), Decimal("0")),
                customer_name=(raw.get("customer_name") or "")[:150],
                notes=(raw.get("notes") or "")[:255],
                deleted=incoming_deleted,
            )
            report["service_entries_created"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"service_entry:{e}")

    # ---- Expenses (append-only, idempotent) ------------------------------------
    for raw in payload.get("expenses", []):
        try:
            ext_id = raw.get("external_id")
            if ext_id and Expense.objects.filter(external_id=ext_id).exists():
                report["expenses_skipped"] = report.get("expenses_skipped", 0) + 1
                continue

            Expense.objects.create(
                external_id=uuid.UUID(ext_id) if ext_id else uuid.uuid4(),
                date=_parse_dt(raw.get("date")) or timezone.now(),
                description=(raw.get("description") or "")[:255],
                amount=_dec(raw.get("amount"), Decimal("0")),
                deleted=bool(raw.get("deleted", False)),
            )
            report["expenses_created"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"expense:{e}")

    # ---- Users (admin-only) -----------------------------------------------
    can_manage_users = caller_user is not None and caller_user.role == ROLE_ADMIN
    for raw in payload.get("users", []):
        try:
            if not can_manage_users:
                report["users_skipped"] += 1
                continue
            ext_id = raw.get("external_id")
            incoming_dt = _parse_dt(raw.get("updated_at"))
            username_key = (raw.get("username") or "").strip()
            user = AdminUser.objects.filter(external_id=ext_id).first() if ext_id else None
            # Identity conflict made simple: the username is a person's real
            # login identity, and only the desktop pushes users (the desktop
            # never ingests user rows), so a username match under a different
            # external_id means the same account is mirrored twice. Absorb it —
            # the incoming (desktop) copy wins and the two converge into one
            # account instead of raising a unique-constraint error forever.
            identity_conflict = False
            if user is None and username_key:
                user = AdminUser.objects.filter(username=username_key).first()
                identity_conflict = user is not None
            if user is not None and not identity_conflict and not _lww_update(user, incoming_dt):
                report["users_skipped"] += 1
                continue

            values = {
                "username": username_key or raw.get("username", ""),
                "full_name": raw.get("full_name") or "",
                "email": raw.get("email") or None,
                "role": raw.get("role", ROLE_ADMIN),
                "is_active": bool(raw.get("is_active", True)),
                "deleted": bool(raw.get("deleted", False)),
                "desktop_password_required": bool(raw.get("desktop_password_required", False)),
            }
            password_hash = (raw.get("password_hash") or "").strip()
            if user is None:
                if password_hash:
                    values["password_hash"] = password_hash
                AdminUser.objects.create(external_id=uuid.UUID(ext_id), **values)
                report["users_created"] += 1
            else:
                for k, v in values.items():
                    setattr(user, k, v)
                new_hash = raw.get("password_hash")
                if new_hash and new_hash.strip():
                    user.password_hash = new_hash.strip()
                if identity_conflict and ext_id:
                    user.external_id = uuid.UUID(ext_id)
                user.save()
                report["users_updated"] += 1
        except Exception as e:  # noqa: BLE001
            report["errors"].append(f"user:{e}")

    return report


# Back-compat alias used by tests/imports.
apply = apply_changes