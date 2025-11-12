from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional, Tuple

import csv
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cash_management.models import BankAccount, Transaction


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _parse_decimal(s: str | None) -> Optional[Decimal]:
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


def _parse_date(s: str | None):
    if not s:
        return None
    from dateutil import parser as dateparser  # type: ignore

    txt = str(s).strip()
    if not txt:
        return None
    for dayfirst in (True, False):
        try:
            dt = dateparser.parse(txt, dayfirst=dayfirst, yearfirst=False, fuzzy=True)
            return dt.date()
        except Exception:
            continue
    return None


@dataclass
class _BankSummary:
    name: str
    balance: Optional[Decimal]


@dataclass
class _LedgerBlock:
    header: List[str]
    rows: List[List[str]]
    last_balance: Optional[Decimal]


def _is_ledger_header(cols: List[str]) -> bool:
    if not cols:
        return False
    header = [_norm(c) for c in cols]
    if header[:8] == [
        "id",
        "date",
        "purpose of payment",
        "check no.",
        "reference",
        "debit",
        "credit",
        "balance",
    ]:
        return True
    if header[:8] == [
        "l/i",
        "date",
        "purpose of paymnet",
        "check no.",
        "reference",
        "debit",
        "credit",
        "balance",
    ]:
        return True
    if header[:7] == [
        "l/i",
        "date",
        "purpose of payments",
        "debit",
        "credit",
        "balance",
        "remark",
    ]:
        return True
    return False


def _is_bank_summary_header(cols: List[str]) -> bool:
    if not cols:
        return False
    header = [_norm(c) for c in cols]
    return (
        len(header) >= 5
        and header[0] in {"l/i", "id"}
        and "bank name" in header[1]
        and "current balance" in header[4]
    )


def _tidy_row_to_out(header: List[str], row: List[str]) -> List[str]:
    # Return: [ID, Date, Purpose, Check No., Reference, Debit, Credit, Balance]
    hmap = {_norm(h): i for i, h in enumerate(header)}

    def get(*names: str) -> str:
        for k in names:
            i = hmap.get(_norm(k))
            if i is not None and i < len(row):
                return row[i] if row[i] is not None else ""
        return ""

    idv = get("id", "l/i").strip()
    date = get("date").strip()
    purpose = get("purpose of payment", "purpose of paymnet", "purpose of payments").strip()
    checkno = get("check no.").strip()
    ref = get("reference").strip()
    debit = get("debit").strip()
    credit = get("credit").strip()
    balance = get("balance").strip()
    return [idv, date, purpose, checkno, ref, debit, credit, balance]


def _looks_like_opening(row: List[str]) -> bool:
    try:
        text = " ".join((str(c) for c in row if isinstance(c, str))).lower()
    except Exception:
        return False
    return ("open" in text) and ("bal" in text)


def _load_csv_rows(path: Path) -> List[List[str]]:
    rows: List[List[str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            rows.append([c if c is not None else "" for c in r])
    return rows


def _extract_bank_summaries(rows: List[List[str]]) -> List[_BankSummary]:
    banks: List[_BankSummary] = []
    i = 0
    while i < len(rows):
        cols = rows[i]
        if _is_bank_summary_header(cols):
            i += 1
            while i < len(rows):
                r = rows[i]
                if not any(r):
                    break
                if _is_ledger_header(r) or _is_bank_summary_header(r):
                    break
                bank_name = (r[1] or "").strip()
                bal_cell = r[4] if len(r) >= 5 else None
                bal = _parse_decimal(bal_cell) if bal_cell is not None else None
                if bank_name:
                    banks.append(_BankSummary(bank_name, bal))
                i += 1
            continue
        i += 1
    return banks


def _extract_ledger_blocks(rows: List[List[str]]) -> List[_LedgerBlock]:
    blocks: List[_LedgerBlock] = []
    i = 0
    while i < len(rows):
        cols = rows[i]
        if _is_ledger_header(cols):
            header = cols
            body: List[List[str]] = []
            i += 1
            while i < len(rows):
                r = rows[i]
                if _is_ledger_header(r) or _is_bank_summary_header(r):
                    break
                if not any(r):
                    i += 1
                    continue
                body.append(r)
                i += 1
            # Find last usable balance
            last_balance: Optional[Decimal] = None
            b_idx = None
            try:
                b_idx = [_norm(h) for h in header].index("balance")
            except ValueError:
                b_idx = None
            if b_idx is not None:
                for rr in reversed(body):
                    if b_idx < len(rr):
                        last_balance = _parse_decimal(rr[b_idx])
                    if last_balance is not None:
                        break
            blocks.append(_LedgerBlock(header=header, rows=body, last_balance=last_balance))
            continue
        i += 1
    return blocks


def _map_blocks_to_banks(blocks: List[_LedgerBlock], banks: List[_BankSummary]) -> List[Tuple[str, _LedgerBlock]]:
    result: List[Tuple[str, _LedgerBlock]] = []
    used: set[int] = set()

    def is_synth(name: str) -> bool:
        n = name.lower()
        return ("total" in n and "incl" in n)

    # First pass: exact balance match
    for block in blocks:
        match_idx = None
        if block.last_balance is not None:
            for j, b in enumerate(banks):
                if j in used:
                    continue
                if b.balance is not None and b.balance == block.last_balance:
                    match_idx = j
                    break
        if match_idx is not None:
            used.add(match_idx)
            result.append((banks[match_idx].name, block))
        else:
            result.append(("", block))

    # Second pass: fill unmatched sequentially with non-synthetic banks
    remaining = [i for i, b in enumerate(banks) if i not in used and not is_synth(b.name)]
    rem_iter = iter(remaining)
    filled: List[Tuple[str, _LedgerBlock]] = []
    for name, block in result:
        if name:
            filled.append((name, block))
        else:
            try:
                idx = next(rem_iter)
                filled.append((banks[idx].name, block))
                used.add(idx)
            except StopIteration:
                filled.append(("UNKNOWN", block))
    return filled


def _currency_from_bank(name: str) -> str:
    n = name.lower()
    if "dollar" in n or "usd" in n or "forex" in n:
        return "USD"
    return "ETB"


class Command(BaseCommand):
    help = "Import cash-balance CSV (concatenated ledgers + bank summary) into BankAccount and Transaction."

    def add_arguments(self, parser):
        parser.add_argument("file", type=str, help="Path to the combined cash balance CSV export")
        parser.add_argument("--user", type=str, default=None, help="Username to attribute as creator")
        parser.add_argument("--preview", action="store_true", help="Show mapping and first rows; do not write")

    def handle(self, *args, **opts):
        path = Path(opts["file"]).expanduser()
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        rows = _load_csv_rows(path)
        banks = _extract_bank_summaries(rows)
        if not banks:
            self.stdout.write(self.style.WARNING("Bank summary section not found. Mapping ledgers to banks by order only."))
        blocks = _extract_ledger_blocks(rows)
        if not blocks:
            raise CommandError("No ledger blocks detected. Ensure the CSV contains headers like 'ID,Date,Purpose of Payment,...'.")

        mapped = _map_blocks_to_banks(blocks, banks)

        if opts.get("preview"):
            self.stdout.write("Detected banks (summary):")
            for b in banks:
                self.stdout.write(f"  - {b.name}  balance={b.balance}")
            self.stdout.write("\nLedger mappings:")
            for name, block in mapped:
                self.stdout.write(f"  -> {name or 'UNKNOWN'}: rows={len(block.rows)} last_balance={block.last_balance}")
            # Show a couple of sample rows per block
            for name, block in mapped[:3]:
                self.stdout.write(f"\nSample rows for {name or 'UNKNOWN'}:")
                hdr = block.header
                for r in block.rows[:5]:
                    self.stdout.write("    " + str(_tidy_row_to_out(hdr, r)))
            return

        User = get_user_model()
        user = None
        if opts.get("user"):
            user = User.objects.filter(username=opts["user"]).first()

        created_txn = 0
        created_accts = 0
        for bank_name_full, block in mapped:
            # Prepare/normalize BankAccount fields
            name_str = bank_name_full or "UNKNOWN"
            base_bank = name_str.split("/")[0].strip() if "/" in name_str else name_str
            currency = _currency_from_bank(name_str)
            account, acc_created = BankAccount.objects.get_or_create(
                name=name_str,
                defaults={"bank_name": base_bank, "currency": currency},
            )
            if acc_created:
                created_accts += 1
            else:
                # Update missing attrs if blank
                changed = False
                if not account.bank_name:
                    account.bank_name = base_bank
                    changed = True
                if not account.currency:
                    account.currency = currency
                    changed = True
                if changed:
                    account.save(update_fields=["bank_name", "currency"])

            # Import transactions for this block
            hdr = block.header

            # Optional opening balance row support
            # Find opening balance and earliest date
            open_posted = False
            # compute header index for balance if present
            try:
                bal_idx = [_norm(h) for h in hdr].index("balance")
            except ValueError:
                bal_idx = None
            first_dt = None
            for r0 in block.rows:
                if first_dt is None:
                    idv0, dts, *_ = _tidy_row_to_out(hdr, r0)
                    dt0 = _parse_date(dts)
                    if dt0 is not None:
                        first_dt = dt0
                if (not open_posted) and _looks_like_opening(r0) and bal_idx is not None and bal_idx < len(r0):
                    obal = _parse_decimal(r0[bal_idx])
                    if obal is not None:
                        debit = Decimal(0)
                        credit = Decimal(0)
                        if obal < 0:
                            debit = -obal
                        else:
                            credit = obal
                        dt = first_dt
                        if dt is None:
                            # fallback to start of year
                            from datetime import date as _date
                            dt = _date.today().replace(month=1, day=1)
                        txn = Transaction(
                            account=account,
                            date=dt,
                            description="Opening balance",
                            reference="OPENING",
                            debit=debit,
                            credit=credit,
                            created_by=user,
                        )
                        try:
                            txn.save()
                            created_txn += 1
                            open_posted = True
                        except Exception:
                            pass

            for r in block.rows:
                idv, date_s, purpose, _checkno, ref, debit_s, credit_s, balance_s = _tidy_row_to_out(hdr, r)

                dt = _parse_date(date_s)
                if dt is None:
                    # Skip rows without a valid date
                    continue
                try:
                    debit = _parse_decimal(debit_s) or Decimal(0)
                    credit = _parse_decimal(credit_s) or Decimal(0)
                except Exception:
                    debit = Decimal(0)
                    credit = Decimal(0)
                if debit == 0 and credit == 0:
                    # Nothing to post
                    continue

                txn = Transaction(
                    account=account,
                    date=dt,
                    description=str(purpose),
                    reference=str(ref)[:100],
                    debit=debit,
                    credit=credit,
                    created_by=user,
                )
                try:
                    txn.save()
                    created_txn += 1
                except Exception as exc:
                    self.stderr.write(f"Failed to save transaction for {name_str}: {exc}")

        self.stdout.write(self.style.SUCCESS(f"Imported {created_txn} transactions into {created_accts} new accounts (existing accounts reused)."))
