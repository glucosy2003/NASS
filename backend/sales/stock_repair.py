"""Stock repair helpers, shared by the server management command
(``rebuild_stock``) and the desktop app's ``--rebuild-stock`` switch.

The invariant the repairs restore is simply:

    Item.quantity_in_stock == sum(StockAdjustment.delta)

sale deltas, manual deltas, opening balances all included.

- ``record_openings``  rebuilds each item's opening-balance delta so the ledger
  reconciles to the item's CURRENT quantity (the shop's real shelf count is
  treated as the truth). A rebuild, not an erase: items, categories, sales,
  payments, services and expenses are untouched.
- ``reset_ledger``     wipes the ledger and zeroes the counters. Used on the
  server right before the authoritative desktop pushes its full stock ledger.
- ``recompute_cache``  makes ``quantity_in_stock`` an exact mirror of the
  deltas (non-destructive, safe to run anytime).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from sales.models import (
    OPENING_STOCK_DETAILS,
    Item,
    StockAdjustment,
    opening_stock_external_id,
)


def record_openings():
    """Rewrite every item's opening balance so ``quantity == sum(deltas)``.

    Idempotent: the opening adjustment carries a stable external_id, so a
    second run only rewrites deltas that no longer reconcile.
    """
    items = 0
    created = 0
    updated = 0
    with transaction.atomic():
        for item in Item.objects.all():
            items += 1
            ext = opening_stock_external_id(item.external_id)
            others = (
                item.stock_adjustments.exclude(external_id=ext)
                .filter(deleted=False)
                .aggregate(total=Sum("delta"))["total"]
                or Decimal("0")
            )
            # current == opening + others  =>  opening == current - others
            opening_delta = item.quantity_in_stock - others
            existing = StockAdjustment.objects.filter(external_id=ext).first()
            if existing is None:
                StockAdjustment.objects.create(
                    external_id=ext,
                    item=item,
                    delta=opening_delta,
                    details=OPENING_STOCK_DETAILS,
                )
                created += 1
            elif existing.delta != opening_delta:
                existing.delta = opening_delta
                existing.save(update_fields=["delta"])
                updated += 1
    return {
        "items": items,
        "opening_created": created,
        "opening_updated": updated,
    }


def reset_ledger():
    """Delete every stock delta and zero every item's counter. Server-side."""
    with transaction.atomic():
        deleted = StockAdjustment.objects.count()
        StockAdjustment.objects.all().delete()
        zeroed = Item.objects.update(quantity_in_stock=Decimal("0"))
    return {"stock_adjustments_deleted": deleted, "items_zeroed": zeroed}


def recompute_cache():
    """Rebuild ``quantity_in_stock`` from the ledger deltas (non-destructive)."""
    with transaction.atomic():
        recomputed = 0
        for item in Item.objects.all():
            total = (
                item.stock_adjustments.filter(deleted=False)
                .aggregate(total=Sum("delta"))["total"]
                or Decimal("0")
            )
            if item.quantity_in_stock != total:
                Item.objects.filter(pk=item.pk).update(quantity_in_stock=total)
                recomputed += 1
    return {"items": Item.objects.count(), "recomputed": recomputed}


def verify_invariant():
    """Return the items whose cache disagrees with their ledger, plus a summary."""
    bad = []
    for item in Item.objects.select_related("category").all():
        total = (
            item.stock_adjustments.filter(deleted=False)
            .aggregate(total=Sum("delta"))["total"]
            or Decimal("0")
        )
        if item.quantity_in_stock != total:
            bad.append({"item": item, "cache": item.quantity_in_stock, "ledger": total})
    return {
        "checked": Item.objects.count(),
        "mismatches": bad,
    }