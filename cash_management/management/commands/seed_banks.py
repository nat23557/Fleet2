from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, List, Set

from django.core.management.base import BaseCommand, CommandError

from cash_management.models import BankAccount

# Reuse naming helpers from seed_bank_types if available
try:
    from cash_management.management.commands.seed_bank_types import (
        canonical_bank,
        account_name,
        currency_for_type,
    )
except Exception:
    # Lightweight fallbacks if the other command moves/changes
    def canonical_bank(raw: str) -> str:
        return (raw or '').strip().upper()

    def account_name(bank_name: str, acc_type: str) -> str:
        b = (bank_name or '').strip()
        t = (acc_type or '').strip().lower()
        if t in ('', 'main', 'primary'):
            return b
        if t in ('usd', 'dollar', 'forex', 'retention', 'retantion'):
            return f"{b}/DOLLAR ACC."
        if t == 'ecx':
            return f"{b}/ECX"
        if t == 'current':
            return f"{b}/CURRENT"
        return f"{b}/{t.upper()}"

    def currency_for_type(acc_type: str) -> str:
        t = (acc_type or '').strip().lower()
        return 'USD' if t in ('usd', 'dollar', 'forex', 'retention', 'retantion') else 'ETB'


# A modest default list of common Ethiopian banks in canonical form
DEFAULT_BANKS: List[str] = [
    'COMMERCIAL BANK OF ETHIOPIA',
    'ABAY BANK S.C',
    'BANK OF ABYSSINIA',
    'AWASH BANK S.C',
    'DASHEN BANK S.C',
    'ZEMEN BANK S.C',
    'WEGAGEN BANK S.C',
    'COOPERATIVE BANK OF ETHIOPIA',
    'NIB INTERNATIONAL BANK',
    'HIBRET BANK S.C',
    'BERHAN BANK S.C',
    'ENAT BANK S.C',
    'BUNA BANK S.C',
    'ADDIS INTERNATIONAL BANK S.C',
    'DEBUB GLOBAL BANK S.C',
    'GADAA BANK S.C',
    'SIINQEE BANK S.C',
    'ZAMZAM BANK S.C',
    'AMHARA BANK S.C',
    'OROMIA INTERNATIONAL BANK S.C',  # older naming retained for compatibility
]


def _load_banks_from_csv(path: Path) -> List[str]:
    banks: Set[str] = set()
    with path.open('r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        # Try to find a column that looks like bank name
        field_map = {k.lower(): k for k in (reader.fieldnames or [])}
        col = field_map.get('bank') or field_map.get('bank name') or field_map.get('name')
        if not col:
            raise CommandError("CSV must contain a 'Bank' or 'Bank Name' column")
        for row in reader:
            raw = (row.get(col) or '').strip()
            if raw:
                banks.add(canonical_bank(raw))
    return sorted(banks)


def _extract_banks_from_ledger(path: Path, sheet: str | None = None) -> List[str]:
    try:
        import openpyxl  # type: ignore
    except Exception as exc:
        raise CommandError("openpyxl not installed. Run: pip install openpyxl") from exc

    wb = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active

    banks: Set[str] = set()

    def _norm(s: object) -> str:
        return ('' if s is None else str(s)).strip().lower()

    def _is_bank_title(vals: Iterable[object]) -> str | None:
        non_empty = [v for v in vals if str(v).strip() != '']
        if len(non_empty) != 1:
            return None
        title = str(non_empty[0]).strip()
        tnorm = title.lower()
        if ('bank' in tnorm) or ('/' in tnorm) or ('acc' in tnorm) or ('account' in tnorm):
            # Likely a bank section title
            return title
        return None

    def _is_bank_summary_header(cols: Iterable[object]) -> bool:
        header = [_norm(c) for c in cols]
        return (
            len(header) >= 5
            and header[0] in {'l/i', 'id'}
            and 'bank name' in header[1]
            and 'current balance' in header[4]
        )

    rows = list(ws.iter_rows(values_only=True))
    i = 0
    while i < len(rows):
        vals = list(rows[i])
        title = _is_bank_title(vals)
        if title:
            banks.add(canonical_bank(title))
            i += 1
            continue
        if _is_bank_summary_header(vals):
            i += 1
            while i < len(rows):
                r = list(rows[i])
                if not any(r):
                    break
                # Stop on next header-like block
                if _is_bank_summary_header(r):
                    break
                name_cell = r[1] if len(r) > 1 else ''
                name = canonical_bank(str(name_cell or ''))
                if name:
                    banks.add(name)
                i += 1
            continue
        # Fast exit when we reach an "all bank cash summary" style footer
        if 'all bank cash summary' in ' '.join(_norm(v) for v in vals):
            break
        i += 1

    return sorted(banks)


class Command(BaseCommand):
    help = (
        "Seed bank accounts (BankAccount) from a default list, a CSV, or an Excel ledger.\n"
        "By default creates one 'main' ETB account per bank name so that the Banks view has entries."
    )

    def add_arguments(self, parser):
        parser.add_argument('--source', choices=['default', 'csv', 'ledger'], default='default', help='Where to load bank names from')
        parser.add_argument('--file', type=str, default=None, help='Path to CSV file (with Bank column) or Excel .xlsx when --source=ledger')
        parser.add_argument('--sheet', type=str, default=None, help='Optional sheet name for --source=ledger')
        parser.add_argument('--types', type=str, default='main', help="Comma-separated account types to create per bank (e.g. 'main,usd,ecx')")
        parser.add_argument('--preview', action='store_true', help='Show what would be created without writing')

    def handle(self, *args, **opts):
        src = opts.get('source')
        types = [t.strip().lower() for t in (opts.get('types') or 'main').split(',') if t.strip()]

        if src in ('csv', 'ledger') and not opts.get('file'):
            raise CommandError("--file is required when --source is csv or ledger")

        # Load names
        if src == 'default':
            banks = [canonical_bank(b) for b in DEFAULT_BANKS]
        elif src == 'csv':
            banks = _load_banks_from_csv(Path(opts['file']).expanduser())
        else:
            banks = _extract_banks_from_ledger(Path(opts['file']).expanduser(), sheet=opts.get('sheet'))

        if not banks:
            self.stdout.write(self.style.WARNING('No bank names detected. Nothing to do.'))
            return

        created = 0
        skipped = 0
        for bank in banks:
            for t in types:
                name = account_name(bank, t)
                ccy = currency_for_type(t)
                exists = BankAccount.objects.filter(name__iexact=name).exists()
                if exists:
                    skipped += 1
                    self.stdout.write(f"skip: {name}")
                    continue
                if opts.get('preview'):
                    self.stdout.write(f"create: {name}  bank_name={bank}  ccy={ccy}")
                    created += 1
                    continue
                obj = BankAccount(name=name, bank_name=bank, currency=ccy)
                obj.save()
                created += 1
                self.stdout.write(self.style.SUCCESS(f"created: {name}"))

        if opts.get('preview'):
            self.stdout.write(self.style.WARNING(f"Preview: would create {created}, skip {skipped}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done: created {created}, skipped {skipped}"))

