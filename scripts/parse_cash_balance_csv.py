#!/usr/bin/env python3
"""
Parse a noisy cash-balance CSV export (concatenated ledgers + bank summary)
and produce a unified CSV with an added Bank column:

Output columns:
  Bank, ID, Date, Purpose of Payment, Check No., Reference, Debit, Credit, Balance

Assumptions this handles:
- Multiple repeated ledger headers like:
    - ID,Date,Purpose of Payment,Check No.,Reference,Debit,Credit,Balance
    - L/I,DATE,PURPOSE OF PAYMNET,CHECK NO.,REFERENCE,DEBIT,CREDIT,BALANCE
    - L/I,DATE,PURPOSE OF PAYMENTS,DEBIT,CREDIT,BALANCE,REMARK,
- A summary section near bottom listing bank names and current balances:
    L/I,BANK NAME,,,CURRENT BALANCE,REMARK,,
- Ledger blocks are either matched to a bank by final Balance value, or
  (if no reliable match) by their order relative to the bank list, skipping
  synthetic rows like "NIB TOTAL BAL. INCL. OVERDRAFT" (no own ledger).
- Dates are left as-is (strings). Amounts are kept as original strings.

Usage:
  python scripts/parse_cash_balance_csv.py \
      --input /path/to/cash_balance_transactions.csv \
      --output /path/to/cash_transactions_with_bank.csv

Tips:
- If running on Windows, quote paths with spaces.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Dict, Optional, Tuple


# Normalized output header
OUT_COLUMNS = [
    "Bank",
    "ID",
    "Date",
    "Purpose of Payment",
    "Check No.",
    "Reference",
    "Debit",
    "Credit",
    "Balance",
]


def norm(s: str) -> str:
    return (s or "").strip().lower()


def parse_decimal(s: str | None) -> Optional[Decimal]:
    if s is None:
        return None
    t = str(s).strip()
    if t == "":
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        # Allow commas or stray characters
        try:
            return Decimal(t.replace(",", ""))
        except Exception:
            return None


@dataclass
class BankSummary:
    name: str
    balance: Optional[Decimal]


@dataclass
class LedgerBlock:
    header: List[str]
    rows: List[List[str]]
    # Derived
    last_balance: Optional[Decimal]


def is_ledger_header(cols: List[str]) -> bool:
    if not cols:
        return False
    header = [norm(c) for c in cols]
    # Common variants
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
    # Variant without Check/Reference
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


def is_bank_summary_header(cols: List[str]) -> bool:
    if not cols:
        return False
    header = [norm(c) for c in cols]
    return (
        len(header) >= 5
        and header[0] in {"l/i", "id"}
        and "bank name" in header[1]
        and "current balance" in header[4]
    )


def tidy_row_to_out(header: List[str], row: List[str]) -> List[str]:
    """Map a ledger row with its specific header to the normalized OUT_COLUMNS shape, without Bank.
    Returns a list of 8 values: ID, Date, Purpose of Payment, Check No., Reference, Debit, Credit, Balance
    """
    hmap = {norm(h): i for i, h in enumerate(header)}

    def get(key_variants: List[str]) -> str:
        for k in key_variants:
            i = hmap.get(norm(k))
            if i is not None and i < len(row):
                return row[i] if row[i] is not None else ""
        return ""

    idv = get(["id", "l/i"]).strip()
    date = get(["date"]).strip()
    purpose = get(["purpose of payment", "purpose of paymnet", "purpose of payments"]).strip()
    checkno = get(["check no."]) .strip()
    ref = get(["reference"]).strip()

    # Some variants lack check/ref entirely
    debit = get(["debit"]).strip()
    credit = get(["credit"]).strip()
    balance = get(["balance"]).strip()

    return [idv, date, purpose, checkno, ref, debit, credit, balance]


def load_csv_rows(path: Path) -> List[List[str]]:
    rows: List[List[str]] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for r in reader:
            # Normalize None to ""
            rows.append([c if c is not None else "" for c in r])
    return rows


def extract_bank_summaries(rows: List[List[str]]) -> List[BankSummary]:
    banks: List[BankSummary] = []
    i = 0
    while i < len(rows):
        cols = rows[i]
        if is_bank_summary_header(cols):
            i += 1
            while i < len(rows):
                r = rows[i]
                # Stop on empty line or a new header
                if not any(r):
                    break
                if is_ledger_header(r) or is_bank_summary_header(r):
                    break
                # Expected: index, bank name, ... , current balance, remark
                bank_name = (r[1] or "").strip()
                bal_cell: Optional[str] = None
                if len(r) >= 5:
                    bal_cell = r[4]
                bal = parse_decimal(bal_cell) if bal_cell is not None else None
                if bank_name:
                    banks.append(BankSummary(bank_name, bal))
                i += 1
            continue
        i += 1
    return banks


def extract_ledger_blocks(rows: List[List[str]]) -> List[LedgerBlock]:
    blocks: List[LedgerBlock] = []
    i = 0
    while i < len(rows):
        cols = rows[i]
        if is_ledger_header(cols):
            header = cols
            body: List[List[str]] = []
            i += 1
            while i < len(rows):
                r = rows[i]
                if is_ledger_header(r) or is_bank_summary_header(r):
                    break
                # Skip section separators (text-only marker lines like repeated L/I,... without data)
                if not any(r):
                    i += 1
                    continue
                body.append(r)
                i += 1
            # Derive last balance from the last non-empty row
            last_balance: Optional[Decimal] = None
            for rr in reversed(body):
                # Attempt to locate balance col by header
                try:
                    b_index = [norm(h) for h in header].index("balance")
                except ValueError:
                    b_index = None  # type: ignore
                if b_index is not None and b_index < len(rr):
                    last_balance = parse_decimal(rr[b_index])
                    if last_balance is not None:
                        break
            blocks.append(LedgerBlock(header=header, rows=body, last_balance=last_balance))
            continue
        i += 1
    return blocks


def map_blocks_to_banks(blocks: List[LedgerBlock], banks: List[BankSummary]) -> List[Tuple[str, LedgerBlock]]:
    """Map each ledger block to a bank name.

    Strategy:
      1) Exact match on final balance to summary balance (first unused match wins)
      2) Fallback to sequential mapping to the next plausible bank (skip synthetic total rows)
    """
    result: List[Tuple[str, LedgerBlock]] = []
    used_bank_idx: set[int] = set()

    # Helper to identify synthetic banks that likely don't have their own ledger
    def is_synthetic(name: str) -> bool:
        n = name.lower()
        return ("total" in n and "incl" in n) or ("/" not in n and "bank" in n and "ecx" not in n and "dollar" not in n and "transport" not in n)

    # Pass 1: try matching by final balance
    for bi, block in enumerate(blocks):
        matched_idx = None
        if block.last_balance is not None:
            for j, b in enumerate(banks):
                if j in used_bank_idx:
                    continue
                if b.balance is not None and b.balance == block.last_balance:
                    matched_idx = j
                    break
        if matched_idx is not None:
            used_bank_idx.add(matched_idx)
            result.append((banks[matched_idx].name, block))
        else:
            result.append(("", block))  # to fill in pass 2

    # Pass 2: sequentially fill unmatched from remaining plausible banks
    bank_iter = [i for i, b in enumerate(banks) if i not in used_bank_idx and not is_synthetic(b.name)]
    it = iter(bank_iter)
    filled: List[Tuple[str, LedgerBlock]] = []
    for bank_name, block in result:
        if bank_name:
            filled.append((bank_name, block))
        else:
            try:
                idx = next(it)
                filled.append((banks[idx].name, block))
                used_bank_idx.add(idx)
            except StopIteration:
                filled.append(("UNKNOWN", block))
    return filled


def currency_from_bank(name: str) -> str:
    n = name.lower()
    if "dollar" in n or "/usd" in n or "usd" in n or "forex" in n:
        return "USD"
    return "ETB"


def process(input_csv: Path, output_csv: Path) -> None:
    rows = load_csv_rows(input_csv)

    banks = extract_bank_summaries(rows)
    if not banks:
        print("Warning: Bank summary section not found; mapping will be sequential only.", file=sys.stderr)

    blocks = extract_ledger_blocks(rows)
    if not blocks:
        raise SystemExit("No ledger blocks found. Ensure the CSV is the raw export with headers.")

    mapped = map_blocks_to_banks(blocks, banks)

    # Write unified CSV
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(OUT_COLUMNS)
        for bank_name, block in mapped:
            for r in block.rows:
                out = tidy_row_to_out(block.header, r)
                # Normalize header variants that omit some cols: ensure 8 cols
                if len(out) < 8:
                    out += [""] * (8 - len(out))
                w.writerow([bank_name] + out)

    print(f"Wrote {output_csv} with {sum(len(b.rows) for _, b in mapped)} transactions across {len(mapped)} ledgers.")


def main(argv: List[str]) -> None:
    import argparse

    p = argparse.ArgumentParser(description="Parse cash balance CSV into bank-tagged transactions.")
    p.add_argument("--input", required=True, help="Path to the noisy cash_balance_transactions.csv")
    p.add_argument("--output", required=True, help="Path to write unified CSV with Bank column")
    args = p.parse_args(argv)

    inp = Path(args.input)
    out = Path(args.output)
    if not inp.exists():
        raise SystemExit(f"Input file not found: {inp}")

    out.parent.mkdir(parents=True, exist_ok=True)
    process(inp, out)


if __name__ == "__main__":
    main(sys.argv[1:])

