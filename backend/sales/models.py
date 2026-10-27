import uuid
from decimal import Decimal

from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.db.models import F
from django.utils import timezone


DEFAULT_CATEGORIES = [
    ("Car Tyres", True),
    ("Car Tubes and Valves", True),
    ("Car Batteries", True),
    ("Oil", False),
    ("Acids", False),
    ("Motorcycle Tyres", True),
    ("Motorcycle Tubes", True),
    ("MotorBikes", False),
    ("Others", False),
]


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_CASHIER = "cashier"
ROLE_CHOICES = [
    (ROLE_ADMIN, "Admin"),
    (ROLE_CASHIER, "Cashier / Seller"),
]


# Stock below this quantity is reported as "low stock".
LOW_STOCK_THRESHOLD = 5


class ConnectionCredential(models.Model):
    """A server-issued connection hash for a desktop.

    The raw hash is printed ONCE by the management command
    ``generate_connection_hash``; only a hash is stored here, so the database
    holds no recoverable secret. A hash is never consumed: it can be re-used
    to reconnect (even from another computer) and always resolves to the same
    AdminUser, giving the desktop a seamless continuation of its existing data.
    """

    label = models.CharField(max_length=150, blank=True, default="Desktop")
    code_hash = models.CharField(max_length=255)
    admin_user = models.ForeignKey(
        "AdminUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_valid(self):
        return not self.revoked_at

    @property
    def status(self):
        if self.revoked_at:
            return "revoked"
        if self.admin_user_id:
            return "paired"
        return "available"

    def __str__(self):
        return f"Hash: {self.label or 'Desktop'} ({self.status})"


class Category(models.Model):
    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)
    size_required = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    @staticmethod
    def create_default_categories():
        for name, size_required in DEFAULT_CATEGORIES:
            Category.objects.get_or_create(
                name=name, defaults={"size_required": size_required}
            )


class Item(models.Model):
    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=100)

    # Selling price
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    # 🔥 Cost price (added safely with default)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    quantity_in_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="items"
    )

    brand = models.CharField(max_length=50, blank=True, null=True)
    size = models.CharField(max_length=50, blank=True, null=True)

    

    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        extra = []
        if self.brand:
            extra.append(self.brand)
        if self.size:
            extra.append(self.size)
        extras = f" ({', '.join(extra)})" if extra else ""
        return f"{self.name} - {self.category.name}{extras}"


class StockAdjustment(models.Model):
    """An additive stock change (delta). Immutable + idempotent by external_id,
    exactly like sales, so stock transferred between devices never double-counts."""

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="stock_adjustments"
    )
    delta = models.DecimalField(max_digits=12, decimal_places=3)
    details = models.CharField(max_length=255, blank=True, default="")
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.item}: {self.delta:+.3f}"


class Sale(models.Model):
    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateTimeField(default=timezone.now)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # 🔥 Store total profit
    total_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    

    deleted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Sale {self.id} - {timezone.localtime(self.date).strftime('%Y-%m-%d %H:%M')}"


class SaleItem(models.Model):
    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")

    item = models.ForeignKey(Item, on_delete=models.CASCADE)

    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)

    # 🔥 Selling price locked at sale time
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # 🔥 Cost price locked at sale time
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # 🔥 Profit stored safely
    profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    

    deleted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.profit = (self.selling_price - self.cost_price) * self.quantity
        super().save(*args, **kwargs)

    @property
    def item_total(self):
        return self.selling_price * self.quantity

    def __str__(self):
        return f"{self.item.name} x {self.quantity}"


class PartialPayment(models.Model):
    """A layaway: the customer pays part and the rest stays outstanding.

    Money never travels on this row (it can, and does, change); it lives in
    the append-only PaymentRecord rows, so multi-device sync can never
    double-count or clobber a payment.
    """


    STATUS_OUTSTANDING = "outstanding"
    STATUS_SETTLED = "settled"

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateTimeField(default=timezone.now)
    item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="partial_payments"
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    phone = models.CharField(max_length=50, blank=True, default="")
    customer_name = models.CharField(max_length=150, default="")
    collected = models.BooleanField(default=False)
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.item} - {self.total_amount}"

    @property
    def paid(self):
        return self.payments.filter(deleted=False).aggregate(
            total=models.Sum("amount")
        )["total"] or Decimal("0")

    @property
    def balance(self):
        return self.total_amount - self.paid

    @property
    def status(self):
        return (
            self.STATUS_SETTLED
            if self.balance <= Decimal("0")
            else self.STATUS_OUTSTANDING
        )

    @property
    def is_outstanding(self):
        return self.status == self.STATUS_OUTSTANDING

class PaymentRecord(models.Model):
    """Append-only: one row per amount paid against a PartialPayment."""

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateTimeField(default=timezone.now)
    partial_payment = models.ForeignKey(
        PartialPayment, on_delete=models.CASCADE, related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.partial_payment}: +{self.amount}"


class Service(models.Model):
    """A shop service (work/income) that can be sold, e.g. tyre fitting.

    This is the catalog row (price + name), managed by admins; each time the
    service is provided, a ServiceEntry is appended (sync-safe, like sales).
    """

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=150)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ServiceEntry(models.Model):
    """Append-only record of one service transaction (income)."""

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="entries"
    )
    date = models.DateTimeField(default=timezone.now)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_name = models.CharField(max_length=150, blank=True, default="")
    notes = models.CharField(max_length=255, blank=True, default="")
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.service} x {self.quantity}"


class Expense(models.Model):
    """Append-only record of money spent by the shop."""

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateTimeField(default=timezone.now)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.description} - {self.amount}"


class AdminUser(models.Model):
    """Model to store admin user information and credentials"""

    

    external_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    username = models.CharField(max_length=100, unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True, blank=True, null=True, default=None)
    password_hash = models.CharField(max_length=255)  # Stores hashed password
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ADMIN)
    is_active = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)
    desktop_password_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)
    last_password_changed = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin User"
        verbose_name_plural = "Admin Users"

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_cashier(self):
        return self.role == ROLE_CASHIER

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def set_password(self, raw_password):
        """Hash and set the password"""
        self.password_hash = make_password(raw_password)
        self.last_password_changed = timezone.now()

    def check_password(self, raw_password):
        """Verify the given password against the stored hash"""
        return check_password(raw_password, self.password_hash)

    def __str__(self):
        return f"Admin: {self.username} ({self.full_name})"


class ApiToken(models.Model):
    """A login session bound to one device. Sent with every API call."""

    user = models.ForeignKey(
        AdminUser, on_delete=models.CASCADE, related_name="tokens"
    )
    token = models.CharField(max_length=64, unique=True)
    device_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    device_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    @property
    def is_valid(self):
        return not self.revoked and self.user is not None and self.user.is_active

    def __str__(self):
        return f"Token: {self.user.username} ({self.device_name or self.device_id})"


class SyncLog(models.Model):
    """Per-device sync tracking, so pulls only send changed rows."""

    user = models.ForeignKey(
        AdminUser, on_delete=models.CASCADE, related_name="sync_logs"
    )
    device_id = models.UUIDField(default=uuid.uuid4, editable=False)
    device_name = models.CharField(max_length=255, blank=True, default="")
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    last_pushed_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "device_id")

    def __str__(self):
        return f"Sync: {self.user.username} / {self.device_name or self.device_id}"


class AuditLog(models.Model):
    """Security trail: who did what, from which device, when."""

    user = models.ForeignKey(
        AdminUser, on_delete=models.SET_NULL, null=True, related_name="audit_logs"
    )
    action = models.CharField(max_length=100)
    entity = models.CharField(max_length=50, blank=True, default="")
    entity_external_id = models.UUIDField(null=True, blank=True)
    device_id = models.UUIDField(null=True, blank=True)
    details = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} by {self.user}"

    @classmethod
    def record(cls, user, action, entity="", entity_external_id=None, device_id=None, details=""):
        cls.objects.create(
            user=user,
            action=action,
            entity=entity,
            entity_external_id=entity_external_id,
            device_id=device_id,
            details=details,
        )


# ---------------------------------------------------------------------------
# Stock ledger helpers
#
# `Item.quantity_in_stock` is a cache. The single source of truth for stock is
# the sum of that item's StockAdjustment deltas (opening balance included).
# Sales, partial-payment collections and manual edits each record exactly one
# adjustment on the device that performed them; those deltas are what travel
# to every other device, so stock can never be applied twice.
# ---------------------------------------------------------------------------

OPENING_STOCK_DETAILS = "Opening balance"


def opening_stock_external_id(item_external_id):
    """Stable external id for an item's opening-balance adjustment.

    Deterministic so the repair command and normal item creation always refer
    to the same row (idempotent and re-runnable).
    """
    return uuid.uuid5(uuid.UUID(str(item_external_id)), "nass-opening-stock")


def record_opening_stock(item, delta=None):
    """Ensure an opening-balance StockAdjustment exists for ``item``.

    ``delta`` defaults to the item's current quantity (used when an item is
    first created). Returns ``(adjustment, created)``.
    """
    ext = opening_stock_external_id(item.external_id)
    if delta is None:
        delta = item.quantity_in_stock
    return StockAdjustment.objects.get_or_create(
        external_id=ext,
        defaults={
            "item": item,
            "delta": delta,
            "details": OPENING_STOCK_DETAILS,
        },
    )


# ---------------------------------------------------------------------------
# Deterministic stock deltas for sales
#
# A sale's stock effect is a StockAdjustment whose external_id is derived from
# the SaleItem id, so the device that performed the sale and every device that
# later receives it produce the SAME adjustment row. A delta therefore applies
# exactly once per device — even when a :class:`StockAdjustment` is stripped
# from a non-admin push (see ``sales.sync``) the receiving sale row rebuilds
# the identical adjustment, and an echo is skipped by external_id.
# ---------------------------------------------------------------------------

def sale_stock_external_id(sale_item_external_id):
    return uuid.uuid5(uuid.UUID(str(sale_item_external_id)), "nass-sale-stock")


def sale_restore_external_id(sale_item_external_id):
    return uuid.uuid5(uuid.UUID(str(sale_item_external_id)), "nass-sale-delete-stock")


def record_stock_delta(item, delta, external_id, details=""):
    """Apply one stock delta exactly once (idempotent by ``external_id``).

    Returns True when the delta was applied, False when the adjustment already
    existed (echo). ``Item.quantity_in_stock`` moves in lockstep with the row.
    """
    if StockAdjustment.objects.filter(external_id=external_id).exists():
        return False
    StockAdjustment.objects.create(
        external_id=external_id,
        item=item,
        delta=delta,
        details=(details or "")[:255],
    )
    Item.objects.filter(pk=item.pk).update(
        quantity_in_stock=F("quantity_in_stock") + delta
    )
    return True


def record_sale_stock(sale, lines=None):
    """Apply a sale's stock deltas via deterministic adjustments (idempotent).

    Called by the originating device right after the sale is created and by
    the sync engine when a sale first lands on another device.
    """
    applied = 0
    if lines is None:
        lines = sale.items.select_related("item").filter(deleted=False)
    for si in lines:
        if record_stock_delta(
            si.item,
            -si.quantity,
            sale_stock_external_id(si.external_id),
            details=f"Sale #{sale.id}",
        ):
            applied += 1
    return applied


def record_sale_restore(sale, lines=None):
    """Restore stock when a sale is deleted (same determinism as
    ``record_sale_stock``, separate namespace so reuse is impossible)."""
    applied = 0
    if lines is None:
        lines = sale.items.select_related("item").filter(deleted=False)
    for si in lines:
        if record_stock_delta(
            si.item,
            si.quantity,
            sale_restore_external_id(si.external_id),
            details=f"Sale #{sale.id} deleted",
        ):
            applied += 1
    return applied