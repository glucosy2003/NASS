"""Rebuild / inspect the stock ledger.

The stock ledger invariant is:

    Item.quantity_in_stock == sum(StockAdjustment.delta)

Usage on the server (PythonAnywhere Bash console, from backend/):

    python manage.py rebuild_stock                show status only
    python manage.py rebuild_stock --openings     reconcile ledger to quantities
    python manage.py rebuild_stock --reset        wipe server ledger + counters
    python manage.py rebuild_stock --recompute    recompute quantities from ledger

Deployment order for the mismatch fix:
    1. ship the fixed desktop app, run it with --rebuild-stock (this records
       the authoritative opening balances on the shop PC),
    2. run `rebuild_stock --reset` here so the server has a blank ledger,
    3. sync the desktop once (full push), then verify with no flags.
"""

from django.core.management.base import BaseCommand, CommandError

from sales.stock_repair import record_openings, recompute_cache, reset_ledger, verify_invariant


class Command(BaseCommand):
    help = "Rebuild / inspect the stock ledger (StockAdjustment is the single stock channel)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--openings",
            action="store_true",
            help="Rewrite opening balances so quantity == sum(deltas).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all stock deltas and zero every quantity (use before a full push).",
        )
        parser.add_argument(
            "--recompute",
            action="store_true",
            help="Rebuild quantity_in_stock from the deltas.",
        )

    def handle(self, *args, **options):
        if options["reset"] and options["openings"]:
            raise CommandError("--reset and --openings are mutually exclusive.")

        if options["reset"]:
            result = reset_ledger()
            self.stdout.write(
                self.style.WARNING(
                    f"Reset: deleted {result['stock_adjustments_deleted']} deltas, "
                    f"zeroed {result['items_zeroed']} items."
                )
            )
            return

        if options["openings"]:
            result = record_openings()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Openings recorded: {result['items']} items, "
                    f"{result['opening_created']} created, "
                    f"{result['opening_updated']} updated."
                )
            )

        if options["recompute"]:
            result = recompute_cache()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Recomputed: {result['recomputed']} of "
                    f"{result['items']} items needed fixing."
                )
            )

        self._report()

    def _report(self):
        check = verify_invariant()
        self.stdout.write("")
        if not check["mismatches"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"OK: all {check['checked']} items satisfy "
                    "quantity == sum(stock deltas)."
                )
            )
            return
        self.stdout.write(
            self.style.ERROR(
                f"{len(check['mismatches'])} of {check['checked']} items MISMATCH "
                "(quantity_in_stock != sum of deltas):"
            )
        )
        self.stdout.write("")
        self.stdout.write("  item                   cache       ledger")
        for entry in check["mismatches"]:
            item = entry["item"]
            label = f"{item.name[:22]}".ljust(24)
            self.stdout.write(
                f"  {label}{entry['cache']!s:<12}{entry['ledger']!s}"
            )
        self.stdout.write("")
        self.stdout.write(
            "Fix: run `rebuild_stock --openings` (keeps current quantities as "
            "the truth), or --recompute (trusts the deltas)."
        )