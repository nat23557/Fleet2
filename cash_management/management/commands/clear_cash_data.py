from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from cash_management.models import BankAccount, Transaction, AuditLog


class Command(BaseCommand):
    help = "Delete cash management data (transactions and optionally accounts). Use --dry-run to preview."

    def add_arguments(self, parser):
        parser.add_argument("--only-transactions", action="store_true", help="Delete only transactions; keep bank accounts.")
        parser.add_argument("--bank-contains", type=str, default=None, help="Filter by bank name substring (case-insensitive).")
        parser.add_argument("--account-contains", type=str, default=None, help="Filter by account name substring (case-insensitive).")
        parser.add_argument("--also-audit", action="store_true", help="Also delete AuditLog rows related to cash models.")
        parser.add_argument("--yes", action="store_true", help="Confirm deletion without interactive prompt.")
        parser.add_argument("--dry-run", action="store_true", help="Preview counts; perform no deletes.")

    def handle(self, *args, **opts):
        bank_contains = opts.get("bank_contains")
        account_contains = opts.get("account_contains")
        only_txn = opts.get("only_transactions")
        dry = opts.get("dry_run")
        confirm = opts.get("yes")
        also_audit = opts.get("also_audit")

        accounts = BankAccount.objects.all()
        if bank_contains:
            accounts = accounts.filter(bank_name__icontains=bank_contains)
        if account_contains:
            accounts = accounts.filter(name__icontains=account_contains)

        acc_ids = list(accounts.values_list("id", flat=True))
        txn_qs = Transaction.objects.filter(account_id__in=acc_ids)

        tx_count = txn_qs.count()
        acc_count = accounts.count()

        self.stdout.write("Selection summary:")
        self.stdout.write(f"  Accounts: {acc_count}")
        self.stdout.write(f"  Transactions: {tx_count}")

        audit_count = 0
        if also_audit:
            audit_count = AuditLog.objects.filter(
                Q(model__icontains="cash_management.bankaccount") | Q(model__icontains="cash_management.transaction")
            ).count()
            self.stdout.write(f"  AuditLog rows: {audit_count}")

        if dry:
            self.stdout.write(self.style.WARNING("Dry-run mode: no records deleted."))
            return

        if not confirm:
            self.stderr.write("Refusing to delete without --yes. Re-run with --yes to confirm.")
            return

        if only_txn:
            deleted = txn_qs.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {tx_count} transactions."))
        else:
            # Deleting accounts cascades to transactions
            accounts.delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {acc_count} accounts and {tx_count} related transactions."))

        if also_audit and audit_count:
            AuditLog.objects.filter(
                Q(model__icontains="cash_management.bankaccount") | Q(model__icontains="cash_management.transaction")
            ).delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {audit_count} AuditLog rows."))

