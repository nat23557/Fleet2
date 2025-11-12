from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from django.core.management.base import BaseCommand, CommandError

from cash_management.models import BankAccount


ALIAS: Dict[str, str] = {
    # Canonicalization for common names
    'cbe': 'COMMERCIAL BANK OF ETHIOPIA',
    'commercial bank of ethiopia': 'COMMERCIAL BANK OF ETHIOPIA',
    'nib international bank': 'NIB INTERNATIONAL BANK',
    'ahadu bank': 'AHADU BANK S.C',
    'abay bank': 'ABAY BANK S.C',
    'dashen bank': 'DASHEN BANK S.C',
    'oromia international bank': 'OROMIA INTERNATIONAL BANK S.C',
    'wegagen bank': 'WEGAGEN BANK S.C',
    'zemen bank': 'ZEMEN BANK S.C',
    'debub global bank': 'DEBUB GLOBAL BANK S.C',
    'gadaa bank': 'GADAA BANK S.C',
    'cooperative bank of oromia': 'COOPERATIVE BANK OF ETHIOPIA',
}


def canonical_bank(raw: str) -> str:
    if not raw:
        return ''
    key = raw.strip().lower()
    if key in ALIAS:
        return ALIAS[key]
    # Default to uppercase form
    return raw.strip().upper()


def currency_for_type(acc_type: str) -> str:
    t = (acc_type or '').strip().lower()
    if t in ('dollar', 'usd', 'forex', 'retention', 'retantion'):
        return 'USD'
    return 'ETB'


def account_name(bank_name: str, acc_type: str) -> str:
    b = bank_name.strip()
    t = (acc_type or '').strip().lower()
    if t in ('', 'main', 'primary'):
        return b
    if t == 'current':
        # Match workbook style for Abay CURRENT; otherwise generic CURRENT
        if b.endswith('S.C'):
            return f"{b} CURRENT S.C"
        return f"{b}/CURRENT"
    if t == 'ecx':
        return f"{b}/ECX"
    if t in ('dollar', 'usd', 'forex', 'retention', 'retantion'):
        return f"{b}/DOLLAR ACC."
    if t == 'transport':
        return f"{b}/TRANSPORT ACC."
    if t == 'od':
        return f"{b}/OD"
    if t == 'special':
        return f"{b}/SPECIAL"
    # Fallback
    return f"{b}/{acc_type.strip().upper()}"


class Command(BaseCommand):
    help = "Seed bank accounts from a simple CSV with columns: Bank,Account Type,Source"

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='Path to CSV file with bank types')
        parser.add_argument('--preview', action='store_true', help='Show what would be created without writing')

    def handle(self, *args, **opts):
        path = Path(opts['file']).expanduser()
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        to_create = []
        with path.open('r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            # Support files that may not have exact header casing
            field_map = {k.lower(): k for k in reader.fieldnames or []}
            def col(name: str) -> str:
                return field_map.get(name.lower(), name)

            for row in reader:
                raw_bank = (row.get(col('Bank')) or '').strip()
                acc_type = (row.get(col('Account Type')) or '').strip()
                if not raw_bank:
                    continue
                bank = canonical_bank(raw_bank)
                name = account_name(bank, acc_type)
                ccy = currency_for_type(acc_type)
                to_create.append((name, bank, ccy))

        created = 0
        skipped = 0

        for name, bank, ccy in to_create:
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

