from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cash_management.models import BankAccount, Transaction


def _norm(s: object) -> str:
    return ("" if s is None else str(s)).strip().lower()


def _parse_decimal(s: object) -> Optional[Decimal]:
    if s is None:
        return None
    t = str(s).strip()
    if t == "":
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        try:
            return Decimal(t.replace(",", ""))
        except Exception:
            return None


def _parse_date(s: object):
    if s is None:
        return None
    # Excel may give datetime/date object already
    if hasattr(s, "year") and hasattr(s, "month") and hasattr(s, "day"):
        try:
            return s.date() if hasattr(s, "date") else s
        except Exception:
            return None
    txt = str(s).strip()
    if not txt:
        return None
    try:
        from dateutil import parser as dateparser  # type: ignore
    except Exception as exc:
        raise CommandError("python-dateutil is required") from exc
    # Try both day-first and month-first
    for dayfirst in (True, False):
        try:
            return dateparser.parse(txt, dayfirst=dayfirst, fuzzy=True).date()
        except Exception:
            continue
    return None


def _is_header_row(vals: List[object]) -> bool:
    h = [_norm(v) for v in vals]
    if not h:
        return False
    # Allow variants of L/I or ID
    # Looking for date + purpose + debit + credit + balance
    required = {"date", "debit", "credit", "balance"}
    has_required = required.issubset(set(h))
    if not has_required:
        return False
    # Purpose column appears as misspelled "purpose of paymnet" or similar
    return any("purpose" in x for x in h)


def _header_map(vals: List[object]) -> Dict[str, int]:
    mp: Dict[str, int] = {}
    for i, v in enumerate(vals):
        if v is None:
            continue
        k = _norm(v)
        if not k:
            continue
        mp[k] = i
    return mp


def _is_bank_title(vals: List[object]) -> Optional[str]:
    # A bank title row is typically a single non-empty string cell
    non_empty = [v for v in vals if str(v).strip() != ""]
    if len(non_empty) != 1:
        return None
    title = str(non_empty[0]).strip()
    tnorm = title.lower()
    if "bank" in tnorm or "/" in tnorm or "acc" in tnorm or "account" in tnorm:
        # Avoid header lines like "L/I DATE ..."
        if not _is_header_row(vals):
            return title
    return None


def _is_opening(vals: List[object]) -> bool:
    text = " ".join(_norm(v) for v in vals if isinstance(v, str))
    return ("open" in text and "bal" in text)


def _currency_from_bank(name: str) -> str:
    n = name.lower()
    if "dollar" in n or "usd" in n or "forex" in n or "retantion" in n:
        return "USD"
    return "ETB"


class Command(BaseCommand):
    help = "Scan an Excel ledger (like 'CASH BALANCE') with multiple bank sections and import to BankAccount/Transaction."

    def add_arguments(self, parser):
        parser.add_argument("file", type=str, help="Path to Excel .xlsx file")
        parser.add_argument("--sheet", type=str, default=None, help="Sheet name; defaults to active sheet")
        parser.add_argument("--user", type=str, default=None, help="Username to attribute as creator")
        parser.add_argument("--preview", action="store_true", help="Show mappings only; do not write")

    def handle(self, *args, **opts):
        path = Path(opts["file"]).expanduser()
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        try:
            import openpyxl  # type: ignore
        except Exception as exc:
            raise CommandError("openpyxl not installed. Run: pip install openpyxl") from exc

        wb = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
        ws = wb[opts["sheet"]] if opts.get("sheet") else wb.active

        # Load all rows (values only)
        rows = list(ws.iter_rows(values_only=True))

        User = get_user_model()
        user = None
        if opts.get("user"):
            user = User.objects.filter(username=opts["user"]).first()

        current_bank: Optional[str] = None
        current_bank_opening_done = False
        header_idx: Dict[str, int] = {}
        created_txn = 0
        created_accts = 0

        def get_col(*names: str) -> Optional[int]:
            for nm in names:
                i = header_idx.get(nm)
                if i is not None:
                    return i
            return None

        # For preview
        preview_lines: List[str] = []

        i = 0
        while i < len(rows):
            vals = list(rows[i])
            # Detect bank title
            title = _is_bank_title(vals)
            if title:
                current_bank = title.strip()
                current_bank_opening_done = False
                header_idx = {}
                preview_lines.append(f"Bank: {current_bank}")
                i += 1
                continue

            # Detect header row
            if _is_header_row(vals):
                header_idx = _header_map(vals)
                preview_lines.append(f"  Header OK: {header_idx}")
                i += 1
                continue

            # If no active bank or header, skip lines until we find them
            if not current_bank or not header_idx:
                # Stop at all bank summary
                if "all bank cash summary" in " ".join(_norm(v) for v in vals):
                    break
                i += 1
                continue

            # Opening balance row
            if _is_opening(vals) and not current_bank_opening_done:
                b_idx = get_col("balance")
                if b_idx is not None and b_idx < len(vals):
                    obal = _parse_decimal(vals[b_idx])
                    if obal is not None and obal != 0:
                        if opts.get("preview"):
                            preview_lines.append(f"    Opening balance {current_bank}: {obal}")
                        else:
                            # Ensure account exists
                            account, new = self._get_or_create_account(current_bank)
                            if new:
                                created_accts += 1
                            # Opening as credit if positive, debit if negative
                            debit = Decimal(0)
                            credit = Decimal(0)
                            if obal < 0:
                                debit = -obal
                            else:
                                credit = obal
                            txn = Transaction(
                                account=account,
                                date=_parse_date("2025-07-01") or None,
                                description="Opening balance",
                                reference="OPN-2025",
                                debit=debit,
                                credit=credit,
                                created_by=user,
                            )
                            if txn.date is not None:
                                txn.save()
                                created_txn += 1
                current_bank_opening_done = True
                i += 1
                continue

            # Regular ledger row
            didx = get_col("date")
            pidx = get_col("purpose of payment", "purpose of paymnet", "purpose of payments")
            cidx = get_col("credit")
            dridx = get_col("debit")
            ridx = get_col("reference")
            # If there's no date and no numbers, skip
            date_val = vals[didx] if (didx is not None and didx < len(vals)) else None
            debit_val = vals[dridx] if (dridx is not None and dridx < len(vals)) else None
            credit_val = vals[cidx] if (cidx is not None and cidx < len(vals)) else None
            purpose_val = vals[pidx] if (pidx is not None and pidx < len(vals)) else ""
            ref_val = vals[ridx] if (ridx is not None and ridx < len(vals)) else ""

            # Determine if the row is empty
            if (date_val in (None, "")) and _parse_decimal(debit_val) in (None, Decimal(0)) and _parse_decimal(credit_val) in (None, Decimal(0)):
                i += 1
                continue

            dt = _parse_date(date_val)
            if dt is None:
                i += 1
                continue

            debit = _parse_decimal(debit_val) or Decimal(0)
            credit = _parse_decimal(credit_val) or Decimal(0)
            if debit == 0 and credit == 0:
                i += 1
                continue

            if opts.get("preview"):
                preview_lines.append(
                    f"    row: {dt} {purpose_val} DR={debit} CR={credit} REF={ref_val}"
                )
            else:
                account, new = self._get_or_create_account(current_bank)
                if new:
                    created_accts += 1
                txn = Transaction(
                    account=account,
                    date=dt,
                    description=str(purpose_val),
                    reference=str(ref_val)[:100],
                    debit=debit,
                    credit=credit,
                    created_by=user,
                )
                txn.save()
                created_txn += 1

            i += 1

        if opts.get("preview"):
            for line in preview_lines:
                self.stdout.write(line)
            self.stdout.write("(preview mode: no writes)")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Imported {created_txn} transactions across accounts (created {created_accts} new accounts)."
            ))

    def _get_or_create_account(self, name: str):
        base = name.split("/")[0].strip() if "/" in name else name
        currency = _currency_from_bank(name)
        acc, created = BankAccount.objects.get_or_create(
            name=name,
            defaults={"bank_name": base, "currency": currency},
        )
        # Backfill
        changed = False
        if not acc.bank_name:
            acc.bank_name = base
            changed = True
        if not acc.currency:
            acc.currency = currency
            changed = True
        if changed:
            acc.save(update_fields=["bank_name", "currency"])
        return acc, created

