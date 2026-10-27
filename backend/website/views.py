from datetime import datetime, timedelta
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.db.models import Sum, F, Q
from django.utils import timezone
from django.views.decorators.http import require_POST
import json
import csv
from uuid import UUID
from decimal import Decimal

from sales.models import (
    ROLE_ADMIN,
    AdminUser,
    Category,
    Item,
    LOW_STOCK_THRESHOLD,
    Sale,
    SaleItem,
    StockAdjustment,
    PartialPayment,
    PaymentRecord,
    Service,
    ServiceEntry,
    Expense,
    record_opening_stock,
    record_sale_restore,
    record_stock_delta,
    sale_stock_external_id,
)
from sales.admin_auth import AdminAuthManager
from .forms import (
    LoginForm,
    ExpenseForm,
    CategoryForm,
    ServiceForm,
    ServiceEntryForm,
    DateRangeForm,
    StockUpdateForm,
    PartialPaymentCreateForm,
    PartialPaymentRecordForm,
    ChangePasswordForm,
    ItemForm,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _local_now():
    return timezone.localtime()


def _today_start():
    now = _local_now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _tomorrow_start():
    return _today_start() + timedelta(days=1)


def _day_range_bounds(date_from=None, date_to=None):
    """Convert inclusive 'YYYY-MM-DD' strings into aware [start, end) bounds.

    Keeps the full day in Africa/Lusaka: date_from 00:00 local to the next-day
    00:00 local, so near-midnight records are not shifted a day by the naive
    UTC cast that ``__date__`` lookups apply.
    """
    start = None
    end = None
    if date_from:
        d = datetime.strptime(str(date_from)[:10], "%Y-%m-%d").date()
        start = timezone.make_aware(datetime.combine(d, datetime.min.time()))
    if date_to:
        d = datetime.strptime(str(date_to)[:10], "%Y-%m-%d").date()
        end = timezone.make_aware(
            datetime.combine(d, datetime.min.time()) + timedelta(days=1)
        )
    return start, end


def _fmt_qty(qty):
    text = format(qty, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _fmt_money(amount):
    return f"MK {amount:,.2f}"


def _sale_items_text(sale):
    names = []
    for si in sale.items.select_related("item").all():
        label = si.item.name if si.item else "(unknown)"
        if si.item and si.item.size:
            label = f"{label} ({si.item.size})"
        names.append(label)
    return ", ".join(names) if names else "(no items)"


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------


def root_view(request):
    if request.user.is_authenticated:
        if request.user.is_admin:
            return redirect("web:admin_dashboard")
        return redirect("web:sales_entry")
    return redirect("web:login-alt")


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------


def setup_view(request):
    """First-time setup: create the owner admin account."""
    if AdminUser.objects.exists():
        return redirect("web:login-alt")

    error = None
    if request.method == "POST":
        full_name = request.POST.get("full_name", "").strip()
        email = request.POST.get("email", "").strip() or None
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")

        if not full_name:
            error = "Full name is required."
        elif len(password) < 4:
            error = "Password must be at least 4 characters."
        elif password != confirm:
            error = "Passwords do not match."
        elif email and AdminUser.objects.filter(email=email).exists():
            error = "Email is already in use."
        else:
            try:
                user = AdminUser(
                    username="admin",
                    full_name=full_name,
                    email=email,
                    is_active=True,
                )
                user.set_password(password)
                user.save()
                return redirect("web:login-alt")
            except Exception as e:
                error = f"Failed to create account: {e}"

    return render(request, "website/setup.html", {"error": error})


def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_admin:
            return redirect("web:admin_dashboard")
        return redirect("web:sales_entry")

    has_admin = AdminUser.objects.exists()

    error = None
    if request.method == "POST":
        form = LoginForm(request.POST)
        login_role = request.POST.get("login_role", "admin")
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            if user is None:
                error = "Invalid username or password."
            elif user.deleted:
                error = "Account is disabled."
            elif login_role == "admin" and not user.is_admin:
                error = "This account is a cashier. Please select 'Cashier' to log in."
            elif login_role == "cashier" and not user.is_cashier:
                error = "This account is an admin. Please select 'Admin' to log in."
            else:
                login(request, user)
                if user.is_admin:
                    return redirect("web:admin_dashboard")
                return redirect("web:sales_entry")
    else:
        form = LoginForm()

    return render(
        request,
        "website/login.html",
        {"form": form, "error": error, "has_admin": has_admin},
    )


@login_required
def logout_view(request):
    logout(request)
    return redirect("web:login-alt")


@login_required
def about_view(request):
    return render(request, "website/about.html")


# ---------------------------------------------------------------------------
# Dashboard (landing page)
# ---------------------------------------------------------------------------


@login_required
def dashboard_view(request):
    return render(
        request,
        "website/dashboard.html",
        {"shop_name": getattr(settings, "SHOP_NAME", "My Shop")},
    )


# ---------------------------------------------------------------------------
# Sales entry
# ---------------------------------------------------------------------------


@login_required
def sales_entry_view(request):
    categories = Category.objects.filter(deleted=False).order_by("name")
    items = (
        Item.objects.filter(deleted=False).select_related("category").order_by("name")
    )
    return render(
        request,
        "website/sales/entry.html",
        {
            "categories": categories,
            "items_json": json.dumps(
                [
                    {
                        "id": item.id,
                        "name": item.name,
                        "size": item.size or "",
                        "brand": item.brand or "",
                        "unit_price": str(item.unit_price),
                        "quantity_in_stock": str(item.quantity_in_stock),
                        "category": item.category.name,
                    }
                    for item in items
                ]
            ),
        },
    )


@login_required
@require_POST
def sales_complete_view(request):
    try:
        data = json.loads(request.body)
        items = data.get("items", [])
        sale_date = data.get("date")
        parsed_date = None
        if sale_date:
            try:
                parsed_date = datetime.fromisoformat(sale_date)
                if parsed_date.tzinfo is None:
                    parsed_date = timezone.make_aware(parsed_date)
            except (ValueError, TypeError):
                pass
        parsed_date = parsed_date or timezone.now()

        if not items:
            return JsonResponse({"error": "No items in sale."}, status=400)

        with transaction.atomic():
            sale = Sale.objects.create(
                date=parsed_date,
                total_amount=Decimal("0"),
                total_profit=Decimal("0"),
            )

            total_amount = Decimal("0")
            total_profit = Decimal("0")

            for line in items:
                item = Item.objects.select_for_update().get(id=line["item_id"])
                quantity = Decimal(str(line["quantity"]))
                selling_price = Decimal(str(line["unit_price"]))
                if quantity <= 0 or selling_price < 0:
                    raise ValueError("Quantity must be positive and price cannot be negative.")
                cost_price = item.cost_price

                si = SaleItem.objects.create(
                    sale=sale,
                    item=item,
                    quantity=quantity,
                    selling_price=selling_price,
                    cost_price=cost_price,
                )

                # Deterministic sale delta: the SAME adjustment id is derived
                # on every device from the SaleItem id, so stock can never be
                # double-applied when this sale is synced to the desktop.
                record_stock_delta(
                    item,
                    -quantity,
                    sale_stock_external_id(si.external_id),
                    details=f"Sale #{sale.id}",
                )

                total_amount += selling_price * quantity
                total_profit += (selling_price - cost_price) * quantity

            sale.total_amount = total_amount
            sale.total_profit = total_profit
            sale.save(update_fields=["total_amount", "total_profit"])

        return JsonResponse({"ok": True, "sale_id": sale.id})
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def sales_api_items(request):
    """Return all active items as JSON for the sales search."""
    items = (
        Item.objects.filter(deleted=False).select_related("category").order_by("name")
    )
    return JsonResponse(
        [
            {
                "id": item.id,
                "name": item.name,
                "size": item.size or "",
                "brand": item.brand or "",
                "unit_price": str(item.unit_price),
                "quantity_in_stock": str(item.quantity_in_stock),
                "category": item.category.name,
            }
            for item in items
        ],
        safe=False,
    )


# ---------------------------------------------------------------------------
# Partial payments
# ---------------------------------------------------------------------------


@login_required
def partial_payments_view(request):
    partials = (
        PartialPayment.objects.filter(deleted=False)
        .select_related("item")
        .order_by("-created_at")
    )

    outstanding = [pp for pp in partials if pp.is_outstanding]

    return render(
        request,
        "website/sales/partial.html",
        {
            "partial_payments": partials,
            "outstanding": outstanding,
            "items_json": json.dumps(
                [
                    {
                        "id": item.id,
                        "name": item.name,
                        "size": item.size or "",
                        "unit_price": str(item.unit_price),
                        "quantity_in_stock": str(item.quantity_in_stock),
                    }
                    for item in Item.objects.filter(deleted=False).select_related(
                        "category"
                    )
                ]
            ),
        },
    )


@login_required
@require_POST
def partial_payment_create_view(request):
    try:
        data = json.loads(request.body)
        item = Item.objects.get(id=data["item_id"], deleted=False)
        payment_date_str = data.get("date")
        payment_date = timezone.now()
        if payment_date_str:
            try:
                payment_date = datetime.fromisoformat(payment_date_str)
                if payment_date.tzinfo is None:
                    payment_date = timezone.make_aware(payment_date)
            except (ValueError, TypeError):
                pass

        with transaction.atomic():
            quantity = Decimal(str(data.get("quantity", 1)))
            unit_price = Decimal(str(data["unit_price"]))
            total_amount = Decimal(str(data["total_amount"]))
            customer_name = (data.get("customer_name") or "").strip()
            amount_paid = Decimal(str(data.get("amount_paid", 0)))
            if not customer_name:
                return JsonResponse({"error": "Customer name is required."}, status=400)
            if quantity <= 0 or unit_price < 0 or total_amount < 0:
                return JsonResponse({"error": "Quantity and amounts must be valid."}, status=400)
            if total_amount != unit_price * quantity:
                return JsonResponse({"error": "Total amount does not match quantity and price."}, status=400)
            if amount_paid < 0 or amount_paid > total_amount:
                return JsonResponse({"error": "Amount paid must be between zero and the total."}, status=400)
            pp = PartialPayment.objects.create(
                item=item,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                date=payment_date,
                customer_name=customer_name,
                phone=data.get("phone", ""),
                collected=bool(data.get("collected", False)),
            )

            if amount_paid > 0:
                PaymentRecord.objects.create(
                    date=timezone.now(),
                    partial_payment=pp,
                    amount=amount_paid,
                )

            if pp.collected:
                Item.objects.filter(pk=item.pk).update(
                    quantity_in_stock=F("quantity_in_stock") - pp.quantity
                )
                StockAdjustment.objects.create(
                    item=item,
                    delta=-pp.quantity,
                    details=f"Partial payment collected #{pp.id}",
                )

        return JsonResponse({"ok": True, "id": pp.id})
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def partial_payment_record_view(request):
    try:
        data = json.loads(request.body)
        pp = PartialPayment.objects.get(id=data["partial_payment_id"], deleted=False)
        amount = Decimal(str(data["amount"]))
        if amount <= 0 or amount > pp.balance:
            return JsonResponse(
                {"error": "Payment must be positive and no more than the balance."},
                status=400,
            )

        with transaction.atomic():
            PaymentRecord.objects.create(
                date=timezone.now(),
                partial_payment=pp,
                amount=amount,
            )

        return JsonResponse({"ok": True})
    except PartialPayment.DoesNotExist:
        return JsonResponse({"error": "Partial payment not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def partial_payment_collect_view(request):
    try:
        data = json.loads(request.body)
        pp = PartialPayment.objects.get(id=data["partial_payment_id"], deleted=False)

        if pp.collected:
            return JsonResponse({"error": "Already collected."}, status=400)

        with transaction.atomic():
            pp.collected = True
            pp.save(update_fields=["collected"])

            Item.objects.filter(pk=pp.item_id).update(
                quantity_in_stock=F("quantity_in_stock") - pp.quantity
            )
            StockAdjustment.objects.create(
                item=pp.item,
                delta=-pp.quantity,
                details=f"Partial payment collected #{pp.id}",
            )

        return JsonResponse({"ok": True})
    except PartialPayment.DoesNotExist:
        return JsonResponse({"error": "Partial payment not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def partial_payment_settle_view(request):
    try:
        data = json.loads(request.body)
        pp = PartialPayment.objects.get(id=data["partial_payment_id"], deleted=False)

        balance = pp.balance
        if balance <= 0:
            return JsonResponse({"error": "Already settled."}, status=400)

        with transaction.atomic():
            PaymentRecord.objects.create(
                date=timezone.now(),
                partial_payment=pp,
                amount=balance,
            )

        return JsonResponse({"ok": True})
    except PartialPayment.DoesNotExist:
        return JsonResponse({"error": "Partial payment not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------


@login_required
def admin_dashboard_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    today_start = _today_start()
    tomorrow_start = _tomorrow_start()

    total_products = Item.objects.filter(deleted=False).count()
    low_stock_items = Item.objects.filter(
        deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
    ).count()

    today_sales = (
        Sale.objects.filter(
            deleted=False, date__gte=today_start, date__lt=tomorrow_start
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    today_service_income = (
        ServiceEntry.objects.filter(
            deleted=False, date__gte=today_start, date__lt=tomorrow_start
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    # Today's partial-payment cash is rolled into today's sales, matching the
    # desktop dashboard (which shows a single "Today's Sales" figure).
    today_partial_cash = (
        PaymentRecord.objects.filter(
            deleted=False,
            partial_payment__deleted=False,
            date__gte=today_start,
            date__lt=tomorrow_start,
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )
    today_sales += today_partial_cash

    low_stock_list = Item.objects.filter(
        deleted=False, quantity_in_stock__lt=LOW_STOCK_THRESHOLD
    ).order_by("quantity_in_stock")[:5]

    outstanding_pps = [
        pp
        for pp in PartialPayment.objects.filter(deleted=False)
        .select_related("item")
        .order_by("-date")
        if pp.is_outstanding
    ]

    recent_sales = Sale.objects.filter(deleted=False).order_by("-date")[:5]

    recent_sales_data = []
    for sale in recent_sales:
        recent_sales_data.append(
            {
                "sale": sale,
                "items_text": _sale_items_text(sale),
            }
        )

    return render(
        request,
        "website/admin/dashboard.html",
        {
            "total_products": total_products,
            "low_stock_count": low_stock_items,
            "today_sales": today_sales,
            "today_service_income": today_service_income,
            "today_partial_cash": today_partial_cash,
            "low_stock_list": low_stock_list,
            "outstanding_pps": outstanding_pps[:5],
            "outstanding_total": sum(pp.balance for pp in outstanding_pps),
            "recent_sales_data": recent_sales_data,
            "fmt_qty": _fmt_qty,
            "fmt_money": _fmt_money,
        },
    )


# ---------------------------------------------------------------------------
# Stock management
# ---------------------------------------------------------------------------


@login_required
def stock_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    categories = Category.objects.filter(deleted=False).order_by("name")
    active_category = request.GET.get("category")

    items_by_category = {}
    for cat in categories:
        items = (
            Item.objects.filter(deleted=False, category=cat)
            .select_related("category")
            .order_by("name")
        )
        items_by_category[cat] = items

    return render(
        request,
        "website/admin/stock.html",
        {
            "categories": categories,
            "items_by_category": items_by_category,
            "active_category": active_category,
        },
    )


@login_required
@require_POST
def stock_add_item_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        category = Category.objects.get(id=data["category_id"], deleted=False)

        with transaction.atomic():
            item = Item.objects.create(
                name=data["name"],
                category=category,
                unit_price=Decimal(str(data["unit_price"])),
                cost_price=Decimal(str(data.get("cost_price", 0))),
                quantity_in_stock=Decimal(str(data.get("quantity", 0))),
                brand=data.get("brand", ""),
                size=data.get("size", ""),
            )
            # Opening stock travels as a delta (single stock ledger).
            record_opening_stock(item)

        return JsonResponse({"ok": True, "id": item.id})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def stock_update_item_view(request, item_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        item = Item.objects.get(id=item_id, deleted=False)

        item.name = data.get("name", item.name)
        item.unit_price = Decimal(str(data.get("unit_price", item.unit_price)))
        item.cost_price = Decimal(str(data.get("cost_price", item.cost_price)))
        item.brand = data.get("brand", item.brand)
        item.size = data.get("size", item.size)
        item.save()

        return JsonResponse({"ok": True})
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def stock_delete_item_view(request, item_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        item = Item.objects.get(id=item_id, deleted=False)
        item.deleted = True
        item.save(update_fields=["deleted"])
        return JsonResponse({"ok": True})
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found."}, status=400)


@login_required
@require_POST
def stock_adjust_view(request, item_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        item = Item.objects.get(id=item_id, deleted=False)
        delta = Decimal(str(data["delta"]))

        with transaction.atomic():
            Item.objects.filter(pk=item.pk).update(
                quantity_in_stock=F("quantity_in_stock") + delta
            )
            StockAdjustment.objects.create(
                item=item,
                delta=delta,
                details=data.get("details", "Stock adjustment"),
            )

        return JsonResponse({"ok": True})
    except Item.DoesNotExist:
        return JsonResponse({"error": "Item not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


@login_required
def categories_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    categories = Category.objects.filter(deleted=False).order_by("name")
    return render(request, "website/admin/categories.html", {"categories": categories})


@login_required
@require_POST
def category_create_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        cat = Category.objects.create(
            name=data["name"],
            size_required=bool(data.get("size_required", False)),
        )
        return JsonResponse({"ok": True, "id": cat.id, "name": cat.name})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def category_update_view(request, cat_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        cat = Category.objects.get(id=cat_id, deleted=False)
        cat.name = data.get("name", cat.name)
        cat.size_required = bool(data.get("size_required", cat.size_required))
        cat.save()
        return JsonResponse({"ok": True})
    except Category.DoesNotExist:
        return JsonResponse({"error": "Category not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def category_delete_view(request, cat_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        cat = Category.objects.get(id=cat_id, deleted=False)
        if cat.items.filter(deleted=False).exists():
            return JsonResponse(
                {"error": "Cannot delete category with active items."}, status=400
            )
        cat.deleted = True
        cat.save(update_fields=["deleted"])
        return JsonResponse({"ok": True})
    except Category.DoesNotExist:
        return JsonResponse({"error": "Category not found."}, status=400)


# ---------------------------------------------------------------------------
# Service management
# ---------------------------------------------------------------------------


@login_required
def services_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    today = _local_now().date()
    services = Service.objects.filter(deleted=False).order_by("name")
    entries = (
        ServiceEntry.objects.filter(deleted=False)
        .select_related("service")
        .order_by("-date")
    )

    today_start = _today_start()
    total_income = (
        entries.filter(
            date__gte=today_start, date__lt=_tomorrow_start()
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )
    total_all = entries.aggregate(total=Sum("total_amount"))["total"] or 0

    return render(
        request,
        "website/admin/services.html",
        {
            "services": services,
            "entries": entries[:50],
            "today_income": total_income,
            "total_income": total_all,
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
            "fmt_money": _fmt_money,
        },
    )


@login_required
@require_POST
def service_create_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        service = Service.objects.create(
            name=data["name"],
            price=Decimal(str(data["price"])),
        )
        return JsonResponse(
            {
                "ok": True,
                "id": service.id,
                "name": service.name,
                "price": str(service.price),
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def service_update_view(request, service_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        service = Service.objects.get(id=service_id, deleted=False)
        service.name = data.get("name", service.name)
        service.price = Decimal(str(data.get("price", service.price)))
        service.save()
        return JsonResponse({"ok": True})
    except Service.DoesNotExist:
        return JsonResponse({"error": "Service not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def service_delete_view(request, service_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        service = Service.objects.get(id=service_id, deleted=False)
        service.deleted = True
        service.save(update_fields=["deleted"])
        return JsonResponse({"ok": True})
    except Service.DoesNotExist:
        return JsonResponse({"error": "Service not found."}, status=400)


@login_required
@require_POST
def service_entry_create_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        service = Service.objects.get(id=data["service_id"], deleted=False)
        quantity = Decimal(str(data.get("quantity", 1)))
        unit_price = Decimal(str(data.get("unit_price", service.price)))
        entry_date = timezone.now()
        date_value = data.get("date")
        if date_value:
            try:
                entry_date = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
                if timezone.is_naive(entry_date):
                    entry_date = timezone.make_aware(entry_date)
            except (TypeError, ValueError):
                return JsonResponse({"error": "Invalid service entry date."}, status=400)
        if quantity <= 0 or unit_price < 0:
            return JsonResponse({"error": "Quantity must be positive and price cannot be negative."}, status=400)

        entry = ServiceEntry.objects.create(
            service=service,
            date=entry_date,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=quantity * unit_price,
            customer_name=data.get("customer_name", ""),
            notes=data.get("notes", ""),
        )
        return JsonResponse({"ok": True, "id": entry.id})
    except Service.DoesNotExist:
        return JsonResponse({"error": "Service not found."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def service_entries_filter_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    entries = (
        ServiceEntry.objects.filter(deleted=False)
        .select_related("service")
        .order_by("-date")
    )

    start, end = _day_range_bounds(date_from, date_to)
    if start:
        entries = entries.filter(date__gte=start)
    if end:
        entries = entries.filter(date__lt=end)

    today = _local_now().date()
    total_income = (
        ServiceEntry.objects.filter(deleted=False).aggregate(total=Sum("total_amount"))[
            "total"
        ]
        or 0
    )
    today_income = (
        ServiceEntry.objects.filter(
            deleted=False,
            date__gte=_today_start(),
            date__lt=_tomorrow_start(),
        ).aggregate(total=Sum("total_amount"))["total"]
        or 0
    )

    return JsonResponse(
        {
            "entries": [
                {
                    "date": e.date.strftime("%Y-%m-%d %H:%M"),
                    "service_name": e.service.name if e.service else "",
                    "unit_price": str(e.unit_price),
                    "quantity": str(e.quantity),
                    "total_amount": str(e.total_amount),
                }
                for e in entries[:200]
            ],
            "total_income": str(total_income),
            "today_income": str(today_income),
        }
    )


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------


@login_required
def expenses_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    today = _local_now().date()

    from_param = request.GET.get("from", "")
    to_param = request.GET.get("to", "")
    if from_param:
        try:
            date_from = timezone.datetime.strptime(from_param, "%Y-%m-%d").date()
        except ValueError:
            date_from = today - timezone.timedelta(days=30)
    else:
        date_from = today - timezone.timedelta(days=30)

    if to_param:
        try:
            date_to = timezone.datetime.strptime(to_param, "%Y-%m-%d").date()
        except ValueError:
            date_to = today
    else:
        date_to = today

    start, end = _day_range_bounds(
        date_from.isoformat() if date_from else None,
        date_to.isoformat() if date_to else None,
    )
    range_q = {"deleted": False}
    if start:
        range_q["date__gte"] = start
    if end:
        range_q["date__lt"] = end

    expenses = Expense.objects.filter(**range_q).order_by("-date")

    service_income = (
        ServiceEntry.objects.filter(**range_q).aggregate(total=Sum("total_amount"))[
            "total"
        ]
        or 0
    )
    total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or 0

    return render(
        request,
        "website/admin/expenses.html",
        {
            "expenses": expenses,
            "service_income": service_income,
            "total_expenses": total_expenses,
            "net": service_income - total_expenses,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "fmt_money": _fmt_money,
        },
    )


@login_required
@require_POST
def expense_create_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        data = json.loads(request.body)
        date_str = data.get("date", "")
        if "T" in date_str:
            dt = timezone.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = timezone.datetime.strptime(date_str, "%Y-%m-%d")
            dt = timezone.make_aware(dt)
        amount = Decimal(str(data["amount"]))
        if amount <= 0:
            return JsonResponse({"error": "Expense amount must be greater than zero."}, status=400)
        expense = Expense.objects.create(
            date=dt,
            description=data["description"],
            amount=amount,
        )
        return JsonResponse({"ok": True, "id": expense.id})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_POST
def expense_delete_view(request, expense_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        expense = Expense.objects.get(id=expense_id, deleted=False)
        expense.deleted = True
        expense.save(update_fields=["deleted"])
        return JsonResponse({"ok": True})
    except Expense.DoesNotExist:
        return JsonResponse({"error": "Expense not found."}, status=400)


@login_required
def expense_filter_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    start, end = _day_range_bounds(date_from, date_to)
    expenses = Expense.objects.filter(deleted=False).order_by("-date")
    service_income = ServiceEntry.objects.filter(deleted=False)
    if start:
        expenses = expenses.filter(date__gte=start)
        service_income = service_income.filter(date__gte=start)
    if end:
        expenses = expenses.filter(date__lt=end)
        service_income = service_income.filter(date__lt=end)
    service_income = service_income.aggregate(total=Sum("total_amount"))["total"] or 0

    total_expenses = expenses.aggregate(total=Sum("amount"))["total"] or 0

    return JsonResponse(
        {
            "expenses": [
                {
                    "id": e.id,
                    "date": e.date.strftime("%Y-%m-%d"),
                    "description": e.description,
                    "amount": str(e.amount),
                }
                for e in expenses
            ],
            "service_income": str(service_income),
            "total_expenses": str(total_expenses),
            "net": str(service_income - total_expenses),
        }
    )


# ---------------------------------------------------------------------------
# Reports (Profit/Loss)
# ---------------------------------------------------------------------------


@login_required
def reports_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    today = _local_now().date()
    start, end = _day_range_bounds(today.isoformat(), today.isoformat())
    sale_items = (
        SaleItem.objects.filter(deleted=False, sale__deleted=False)
        .select_related("item", "sale")
        .order_by("-sale__date")
    )
    sale_items = sale_items.filter(sale__date__gte=start, sale__date__lt=end)

    total_qty = sale_items.aggregate(total=Sum("quantity"))["total"] or 0
    total_amount = (
        sale_items.aggregate(total=Sum(F("selling_price") * F("quantity")))["total"]
        or 0
    )
    total_profit = sale_items.aggregate(total=Sum("profit"))["total"] or 0
    total_loss = abs(
        sale_items.filter(profit__lt=0).aggregate(total=Sum("profit"))["total"] or 0
    )

    return render(
        request,
        "website/admin/reports.html",
        {
            "sale_items": sale_items[:100],
            "total_qty": total_qty,
            "total_amount": total_amount,
            "total_profit": total_profit,
            "total_loss": total_loss,
            "date_from": today.isoformat(),
            "date_to": today.isoformat(),
            "fmt_qty": _fmt_qty,
            "fmt_money": _fmt_money,
        },
    )


@login_required
def reports_filter_view(request):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    sale_items = (
        SaleItem.objects.filter(deleted=False, sale__deleted=False)
        .select_related("item", "sale")
        .order_by("-sale__date")
    )

    start, end = _day_range_bounds(date_from, date_to)
    if start:
        sale_items = sale_items.filter(sale__date__gte=start)
    if end:
        sale_items = sale_items.filter(sale__date__lt=end)

    total_qty = sale_items.aggregate(total=Sum("quantity"))["total"] or 0
    total_amount = (
        sale_items.aggregate(total=Sum(F("selling_price") * F("quantity")))["total"]
        or 0
    )
    total_profit = sale_items.aggregate(total=Sum("profit"))["total"] or 0
    total_loss = abs(
        sale_items.filter(profit__lt=0).aggregate(total=Sum("profit"))["total"] or 0
    )

    return JsonResponse(
        {
            "sale_items": [
                {
                    "id": si.id,
                    "sale_id": si.sale.id,
                    "date": si.sale.date.strftime("%Y-%m-%d %H:%M"),
                    "item_name": si.item.name if si.item else "",
                    "item_size": si.item.size if si.item and si.item.size else "",
                    "quantity": str(si.quantity),
                    "unit_price": str(si.selling_price),
                    "item_total": str(si.selling_price * si.quantity),
                    "profit": str(si.profit),
                }
                for si in sale_items[:200]
            ],
            "total_qty": str(total_qty),
            "total_amount": str(total_amount),
            "total_profit": str(total_profit),
            "total_loss": str(total_loss),
        }
    )


@login_required
@require_POST
def report_sale_delete_view(request, sale_id):
    if not request.user.is_admin:
        return JsonResponse({"error": "Permission denied."}, status=403)

    try:
        with transaction.atomic():
            sale = Sale.objects.select_for_update().get(id=sale_id, deleted=False)
            # Deterministic restore deltas (same ids on every device) so a
            # synced delete restores stock exactly once.
            record_sale_restore(sale)
            for sale_item in sale.items.filter(deleted=False):
                sale_item.deleted = True
                sale_item.save(update_fields=["deleted", "updated_at"])
            sale.deleted = True
            sale.save(update_fields=["deleted", "updated_at"])
        return JsonResponse({"ok": True})
    except Sale.DoesNotExist:
        return JsonResponse({"error": "Sale not found or already deleted."}, status=400)


# ---------------------------------------------------------------------------
# Partial payments history
# ---------------------------------------------------------------------------


@login_required
def partial_history_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    partials = (
        PartialPayment.objects.filter(deleted=False)
        .select_related("item")
        .order_by("-date")
    )

    outstanding_count = sum(1 for pp in partials if pp.is_outstanding)
    outstanding = [pp for pp in partials if pp.is_outstanding]
    settled = [pp for pp in partials if not pp.is_outstanding]
    total_owed = sum(pp.balance for pp in partials if pp.is_outstanding)

    return render(
        request,
        "website/admin/history.html",
        {
            "partial_payments": partials,
            "outstanding_payments": outstanding,
            "settled_payments": settled,
            "outstanding_count": outstanding_count,
            "total_owed": total_owed,
            "fmt_qty": _fmt_qty,
            "fmt_money": _fmt_money,
        },
    )


# ---------------------------------------------------------------------------
# Export views (CSV)
# ---------------------------------------------------------------------------


@login_required
def reports_export_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    sale_items = (
        SaleItem.objects.filter(deleted=False, sale__deleted=False)
        .select_related("item", "sale")
        .order_by("-sale__date")
    )

    start, end = _day_range_bounds(date_from, date_to)
    if start:
        sale_items = sale_items.filter(sale__date__gte=start)
    if end:
        sale_items = sale_items.filter(sale__date__lt=end)

    from datetime import date as _date

    today_str = _local_now().strftime("%Y-%m-%d")
    period_from = date_from or "All Time"
    period_to = date_to or today_str

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"profit_loss_report_{_local_now().strftime('%Y%m%d_%H%M%S')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header section
    writer.writerow(["REAL GENERAL SUPPLIERS"])
    writer.writerow(["NASS - Profit / Loss Report"])
    writer.writerow([f"Period: {period_from} to {period_to}"])
    writer.writerow([f"Generated: {today_str}"])
    writer.writerow([])

    # Column headers
    writer.writerow(
        ["Date", "Item", "Size", "Qty", "Total (MK)", "Profit (MK)", "Loss (MK)"]
    )

    total_qty = 0
    total_amount = Decimal("0")
    total_profit = Decimal("0")
    total_loss = Decimal("0")

    for si in sale_items:
        profit = si.profit
        item_total = si.selling_price * si.quantity
        total_qty += si.quantity
        total_amount += item_total
        if profit >= 0:
            total_profit += profit
        else:
            total_loss += abs(profit)

        writer.writerow(
            [
                si.sale.date.strftime("%Y-%m-%d %H:%M"),
                si.item.name if si.item else "",
                si.item.size if si.item and si.item.size else "",
                f"{si.quantity:,.3f}",
                f"{item_total:,.2f}",
                f"{profit:,.2f}" if profit >= 0 else "",
                f"{abs(profit):,.2f}" if profit < 0 else "",
            ]
        )

    # Summary section
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Items Sold:", f"{total_qty:,.3f}"])
    writer.writerow(["Total Amount:", f"MK {total_amount:,.2f}"])
    writer.writerow(["Total Profit:", f"MK {total_profit:,.2f}"])
    writer.writerow(["Total Loss:", f"MK {total_loss:,.2f}"])

    return response


@login_required
def expenses_export_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    expenses = Expense.objects.filter(deleted=False).order_by("-date")
    start, end = _day_range_bounds(date_from, date_to)
    if start:
        expenses = expenses.filter(date__gte=start)
    if end:
        expenses = expenses.filter(date__lt=end)

    from datetime import date as _date

    today_str = _local_now().strftime("%Y-%m-%d")
    period_from = date_from or "All Time"
    period_to = date_to or today_str

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"expenses_report_{_local_now().strftime('%Y%m%d_%H%M%S')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header section
    writer.writerow(["REAL GENERAL SUPPLIERS"])
    writer.writerow(["NASS - Expenses Report"])
    writer.writerow([f"Period: {period_from} to {period_to}"])
    writer.writerow([f"Generated: {today_str}"])
    writer.writerow([])

    # Column headers
    writer.writerow(["Date", "Description", "Amount (MK)"])

    total = Decimal("0")
    for e in expenses:
        total += e.amount
        writer.writerow(
            [
                e.date.strftime("%Y-%m-%d %H:%M"),
                e.description,
                f"{e.amount:,.2f}",
            ]
        )

    # Summary section
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Expenses:", f"MK {total:,.2f}"])

    return response


@login_required
def services_export_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    date_from = request.GET.get("from")
    date_to = request.GET.get("to")

    entries = (
        ServiceEntry.objects.filter(deleted=False)
        .select_related("service")
        .order_by("-date")
    )
    start, end = _day_range_bounds(date_from, date_to)
    if start:
        entries = entries.filter(date__gte=start)
    if end:
        entries = entries.filter(date__lt=end)

    from datetime import date as _date

    today_str = _local_now().strftime("%Y-%m-%d")
    period_from = date_from or "All Time"
    period_to = date_to or today_str

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    filename = f"service_records_{_local_now().strftime('%Y%m%d_%H%M%S')}.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header section
    writer.writerow(["REAL GENERAL SUPPLIERS"])
    writer.writerow(["NASS - Service Records"])
    writer.writerow([f"Period: {period_from} to {period_to}"])
    writer.writerow([f"Generated: {today_str}"])
    writer.writerow([])

    # Column headers
    writer.writerow(["Date", "Service", "Price (MK)"])

    total = Decimal("0")
    count = 0
    for e in entries:
        total += e.total_amount
        count += 1
        writer.writerow(
            [
                e.date.strftime("%Y-%m-%d %H:%M"),
                e.service.name if e.service else "",
                f"{e.total_amount:,.2f}",
            ]
        )

    # Summary section
    writer.writerow([])
    writer.writerow(["SUMMARY"])
    writer.writerow(["Total Records:", f"{count}"])
    writer.writerow(["Total Service Income:", f"MK {total:,.2f}"])

    return response


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------


@login_required
def change_password_view(request):
    error = None
    success = False

    if request.method == "POST":
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            user = request.user
            if user.check_password(form.cleaned_data["old_password"]):
                user.set_password(form.cleaned_data["new_password"])
                user.save()
                success = True
            else:
                error = "Current password is incorrect."
    else:
        form = ChangePasswordForm()

    return render(
        request,
        "website/change_password.html",
        {
            "form": form,
            "error": error,
            "success": success,
        },
    )


@login_required
def account_info_view(request):
    return render(
        request,
        "website/account.html",
        {
            "user": request.user,
        },
    )


@login_required
def account_update_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method."}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON."}, status=400)

    request.user.full_name = data.get("full_name", request.user.full_name)
    request.user.email = data.get("email", request.user.email)
    request.user.save(update_fields=["full_name", "email"])

    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# User Management (admin only)
# ---------------------------------------------------------------------------


@login_required
def users_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    users = AdminUser.objects.filter(deleted=False).order_by("-created_at")
    return render(request, "website/admin/users.html", {"users": users})


@login_required
def user_create_view(request):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    from website.forms import UserCreateForm

    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            if AdminUser.objects.filter(username=cd["username"]).exists():
                return render(
                    request,
                    "website/admin/user_form.html",
                    {
                        "form": form,
                        "error": "Username already exists.",
                        "editing": False,
                    },
                )
            if cd.get("email") and AdminUser.objects.filter(email=cd["email"]).exists():
                return render(
                    request,
                    "website/admin/user_form.html",
                    {
                        "form": form,
                        "error": "Email already in use.",
                        "editing": False,
                    },
                )
            user = AdminUser(
                username=cd["username"],
                full_name=cd["full_name"],
                email=cd.get("email") or None,
                role=cd["role"],
                is_active=True,
            )
            user.set_password(cd["password"])
            user.save()
            return redirect("web:users")
    else:
        form = UserCreateForm(initial={"role": "cashier"})

    return render(
        request,
        "website/admin/user_form.html",
        {
            "form": form,
            "editing": False,
        },
    )


@login_required
def user_edit_view(request, user_id):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    from website.forms import UserEditForm

    try:
        user = AdminUser.objects.get(id=user_id, deleted=False)
    except AdminUser.DoesNotExist:
        return redirect("web:users")

    if request.method == "POST":
        form = UserEditForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            if (
                cd.get("email")
                and AdminUser.objects.filter(email=cd["email"])
                .exclude(id=user.id)
                .exists()
            ):
                return render(
                    request,
                    "website/admin/user_form.html",
                    {
                        "form": form,
                        "user": user,
                        "error": "Email already in use.",
                        "editing": True,
                    },
                )
            user.full_name = cd["full_name"]
            user.email = cd.get("email") or None
            user.role = cd["role"]
            if cd.get("new_password"):
                user.set_password(cd["new_password"])
            user.save()
            return redirect("web:users")
    else:
        form = UserEditForm(
            initial={
                "full_name": user.full_name,
                "email": user.email or "",
                "role": user.role,
            }
        )

    return render(
        request,
        "website/admin/user_form.html",
        {
            "form": form,
            "user": user,
            "editing": True,
        },
    )


@login_required
def user_toggle_active_view(request, user_id):
    if not request.user.is_admin:
        return redirect("web:sales_entry")

    if request.method != "POST":
        return redirect("web:users")

    try:
        user = AdminUser.objects.get(id=user_id, deleted=False)
    except AdminUser.DoesNotExist:
        return redirect("web:users")

    if user.id == request.user.id:
        return redirect("web:users")

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return redirect("web:users")
