from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.db.models import Sum, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import TransactionForm, BankAccountForm, BankRegistrationForm
from .models import BankAccount, Transaction
from .exchange import get_or_update_today_rates
from .exchange import get_or_update_today_rates


def in_group(user, group_name: str) -> bool:
    try:
        return user.is_authenticated and user.groups.filter(name=group_name).exists()
    except Exception:
        return False


def is_clerk(user) -> bool:
    return in_group(user, 'Clerk')


def owner_required(view_func):
    return user_passes_test(lambda u: in_group(u, 'Owner') or u.is_superuser)(view_func)


def clerk_required(view_func):
    return user_passes_test(lambda u: in_group(u, 'Clerk') or in_group(u, 'Owner') or u.is_superuser)(view_func)


@login_required
def dashboard(request):
    # Clerks are limited to daily view only
    if is_clerk(request.user):
        return redirect('cash_management:daily')
    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))

    # Annotate per-account balances
    accounts_qs = (
        BankAccount.objects
        .annotate(
            total_credit=Coalesce(Sum('transaction__credit'), dec0),
            total_debit=Coalesce(Sum('transaction__debit'), dec0),
        )
        .annotate(
            balance=ExpressionWrapper(F('total_credit') - F('total_debit'), output_field=DecimalField(max_digits=12, decimal_places=2))
        )
        .order_by('name')
    )

    # Optional currency filter (ETB/USD)
    currency = request.GET.get('currency', '').strip().upper()
    if currency:
        accounts_qs = accounts_qs.filter(currency__iexact=currency)

    # Totals by currency (for KPI cards)
    totals_qs = (
        Transaction.objects
        .values('account__currency')
        .annotate(sum_credit=Coalesce(Sum('credit'), dec0), sum_debit=Coalesce(Sum('debit'), dec0))
        .annotate(balance=ExpressionWrapper(F('sum_credit') - F('sum_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
    )
    totals: dict[str, float] = {}
    for r in totals_qs:
        ccy = (r['account__currency'] or 'ETB').upper()
        totals[ccy] = float(r['balance'] or 0)
    # Ensure expected currency keys exist to avoid template lookup errors
    totals.setdefault('ETB', 0.0)
    totals.setdefault('USD', 0.0)

    # Live CBE conversion snapshot
    rates = get_or_update_today_rates()
    total_etb_native = float(totals.get('ETB', 0.0))
    total_usd_native = float(totals.get('USD', 0.0))
    total_forex_to_etb = 0.0
    for ccy, bal in totals.items():
        if ccy == 'ETB':
            continue
        rate = float(rates.get(ccy, 0) or 0)
        if rate > 0:
            total_forex_to_etb += float(bal) * rate
    grand_total = total_etb_native + total_forex_to_etb

    # Per-account UI helpers (threshold alerts + ETB equivalent)
    account_rows = []
    for a in accounts_qs:
        bal = float(a.balance or 0)
        ccy = (a.currency or 'ETB').upper()
        rate = float(rates.get(ccy, 0) or 0) if ccy != 'ETB' else 0.0
        etb_equiv = bal if ccy == 'ETB' else (bal * rate if rate > 0 else None)
        account_rows.append({
            'id': a.id,
            'name': a.name,
            'bank_name': a.bank_name,
            'currency': ccy,
            'balance': bal,
            'rate': rate if rate > 0 else None,
            'etb_equiv': etb_equiv,
            'below_threshold': (float(a.threshold or 0) > 0 and bal < float(a.threshold)),
            'url': reverse('cash_management:account_ledger', args=[a.id]),
        })

    context = {
        "accounts": accounts_qs,
        "totals": totals,  # e.g., {'ETB': 1234.56, 'USD': 789.01}
        "selected_currency": currency,
        "rates": {k: float(v) for k, v in rates.items() if k != 'ETB'},
        "total_etb_native": total_etb_native,
        "total_forex_to_etb": total_forex_to_etb,
        "grand_total": grand_total,
        "account_rows": account_rows,
        "can_add_txn": in_group(request.user, 'Clerk') or in_group(request.user, 'Owner') or request.user.is_superuser,
        "total_usd_native": total_usd_native,
    }
    return render(request, "cash_management/dashboard.html", context)


@login_required
def banks(request):
    if is_clerk(request.user):
        return redirect('cash_management:daily')
    """List banks (by BankAccount.bank_name) with aggregated balance.

    Supports optional `?currency=ETB|USD` filter.
    """
    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    currency = request.GET.get('currency', '').strip().upper()

    # Per-account balances
    accounts = (
        BankAccount.objects
        .annotate(
            total_credit=Coalesce(Sum('transaction__credit'), dec0),
            total_debit=Coalesce(Sum('transaction__debit'), dec0),
        )
        .annotate(balance=ExpressionWrapper(F('total_credit') - F('total_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
    )
    if currency:
        accounts = accounts.filter(currency__iexact=currency)

    # Aggregate in Python to keep it simple and include zero-transaction accounts
    bank_rows: dict[str, float] = {}
    for a in accounts:
        bank_rows[a.bank_name] = bank_rows.get(a.bank_name, 0.0) + float(a.balance or 0)

    rows = sorted(
        ([name, bal] for name, bal in bank_rows.items()), key=lambda x: x[0]
    )

    # Totals by currency for KPI
    totals_qs = (
        Transaction.objects
        .values('account__currency')
        .annotate(sum_credit=Coalesce(Sum('credit'), dec0), sum_debit=Coalesce(Sum('debit'), dec0))
        .annotate(balance=ExpressionWrapper(F('sum_credit') - F('sum_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
    )
    totals: dict[str, float] = {}
    for r in totals_qs:
        ccy = (r['account__currency'] or 'ETB').upper()
        totals[ccy] = float(r['balance'] or 0)
    # Ensure expected currency keys exist for safe template access
    totals.setdefault('ETB', 0.0)
    totals.setdefault('USD', 0.0)

    # Cash snapshot (aggregated) – include FOREX conversion and grand total
    rates = get_or_update_today_rates()
    total_etb_native = float(totals.get('ETB', 0.0))
    total_usd_native = float(totals.get('USD', 0.0))
    total_forex_to_etb = 0.0
    for ccy, bal in totals.items():
        if ccy == 'ETB':
            continue
        rate = float(rates.get(ccy, 0) or 0)
        if rate > 0:
            total_forex_to_etb += float(bal) * rate
    grand_total = total_etb_native + total_forex_to_etb

    context = {
        'rows': rows,  # list of [bank_name, balance]
        'selected_currency': currency,
        'totals': totals,
        'total_etb_native': total_etb_native,
        'total_forex_to_etb': total_forex_to_etb,
        'grand_total': grand_total,
        'can_add_txn': in_group(request.user, 'Clerk') or in_group(request.user, 'Owner') or request.user.is_superuser,
        'total_usd_native': total_usd_native,
        'can_register_bank': in_group(request.user, 'Owner') or request.user.is_superuser,
    }
    return render(request, 'cash_management/banks.html', context)


@login_required
def bank_detail(request, name: str):
    if is_clerk(request.user):
        return redirect('cash_management:daily')
    """Detail page for a single bank brand (bank_name), listing its accounts and balances."""
    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    currency = request.GET.get('currency', '').strip().upper()
    qs = BankAccount.objects.filter(bank_name__iexact=name)
    if currency:
        qs = qs.filter(currency__iexact=currency)
    accounts = (
        qs
        .annotate(
            total_credit=Coalesce(Sum('transaction__credit'), dec0),
            total_debit=Coalesce(Sum('transaction__debit'), dec0),
        )
        .annotate(balance=ExpressionWrapper(F('total_credit') - F('total_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('name')
    )
    total = sum(float(a.balance or 0) for a in accounts)
    context = {
        'bank_name': name,
        'accounts': accounts,
        'total': total,
        'selected_currency': currency,
    }
    return render(request, 'cash_management/bank_detail.html', context)


@login_required
def daily(request):
    """Daily cash transactions across all banks, with optional currency and date filters.

    Query params:
      - currency: ETB | USD (optional)
      - start: YYYY-MM-DD (optional)
      - end: YYYY-MM-DD (optional)
    """
    from django.db.models.functions import TruncDate
    import datetime as _dt

    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    currency = (request.GET.get('currency') or '').strip().upper()
    start_s = (request.GET.get('start') or '').strip()
    end_s = (request.GET.get('end') or '').strip()

    def _parse(d: str):
        try:
            y, m, d = [int(x) for x in d.split('-')]
            return _dt.date(y, m, d)
        except Exception:
            return None

    start = _parse(start_s) if start_s else None
    end = _parse(end_s) if end_s else None

    base = Transaction.objects.all()
    if currency:
        base = base.filter(account__currency__iexact=currency)
    if start:
        base = base.filter(date__gte=start)
    if end:
        base = base.filter(date__lte=end)

    # Opening balance prior to start
    prior_qs = Transaction.objects.all()
    if currency:
        prior_qs = prior_qs.filter(account__currency__iexact=currency)
    if start:
        prior_qs = prior_qs.filter(date__lt=start)
    agg_prior = prior_qs.aggregate(sum_credit=Coalesce(Sum('credit'), dec0), sum_debit=Coalesce(Sum('debit'), dec0))
    opening = float(agg_prior['sum_credit']) - float(agg_prior['sum_debit'])

    # Daily aggregates
    by_day = (
        base
        .annotate(day=TruncDate('date'))
        .values('day')
        .annotate(inflow=Coalesce(Sum('credit'), dec0), outflow=Coalesce(Sum('debit'), dec0))
        .order_by('day')
    )

    rows = []
    running = opening
    for r in by_day:
        inflow = float(r['inflow'])
        outflow = float(r['outflow'])
        running += inflow - outflow
        rows.append({
            'day': r['day'],
            'inflow': inflow,
            'outflow': outflow,
            'net': inflow - outflow,
            'running': running,
        })

    # Compute relative net magnitude for visual bars
    if rows:
        max_abs_net = max(abs(r['net']) for r in rows) or 0
        for r in rows:
            r['net_pct'] = round(abs(r['net']) * 100.0 / max_abs_net, 2) if max_abs_net > 0 else None

    context = {
        'rows': rows,
        'opening': opening,
        'selected_currency': currency,
        'start': start_s,
        'end': end_s,
        'can_add_txn': is_clerk(request.user) or in_group(request.user, 'Owner') or request.user.is_superuser,
    }
    return render(request, 'cash_management/daily.html', context)


@login_required
def account_ledger(request, pk: int):
    if is_clerk(request.user):
        return redirect('cash_management:daily')
    account = get_object_or_404(BankAccount, pk=pk)
    txns = Transaction.objects.filter(account=account).order_by('date', 'id')
    running = 0
    rows = []
    for t in txns:
        running += float(t.credit) - float(t.debit)
        rows.append((t, running))

    can_reverse = in_group(request.user, 'Owner') or request.user.is_superuser
    context = {
        'account': account,
        'rows': rows,
        'current_balance': running,
        'can_reverse': can_reverse,
    }
    return render(request, 'cash_management/account_ledger.html', context)


@login_required
@clerk_required
def new_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            txn: Transaction = form.save(commit=False)
            txn.created_by = request.user
            txn.save()
            _post_txn_alerts(txn)
            messages.success(request, 'Transaction recorded.')
            return redirect('cash_management:account_ledger', pk=txn.account_id)
    else:
        form = TransactionForm(user=request.user)

    # Provide account balances for UX preview
    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    accounts = (
        BankAccount.objects
        .annotate(
            total_credit=Coalesce(Sum('transaction__credit'), dec0),
            total_debit=Coalesce(Sum('transaction__debit'), dec0),
        )
        .annotate(balance=ExpressionWrapper(F('total_credit') - F('total_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('name')
    )
    acc_map = {
        a.id: {
            'balance': float(a.balance or 0),
            'currency': a.currency,
            'threshold': float(a.threshold or 0),
            'limit': float(a.large_txn_limit or 0),
            'bank': a.bank_name,
        }
        for a in accounts
    }

    # Suggest the most recent distinct descriptions to speed entry
    recent_desc = list(
        Transaction.objects.exclude(description='').order_by('-date', '-id').values_list('description', flat=True)[:50]
    )
    # Keep unique order
    seen = set()
    desc_suggestions = []
    for d in recent_desc:
        if d not in seen:
            desc_suggestions.append(d)
            seen.add(d)
        if len(desc_suggestions) >= 12:
            break

    context = {
        'form': form,
        'account_data': acc_map,
        'desc_suggestions': desc_suggestions,
    }
    return render(request, 'cash_management/transaction_form.html', context)


@login_required
@owner_required
def reverse_transaction(request, tx_id: int):
    txn = get_object_or_404(Transaction, pk=tx_id)
    if request.method != 'POST':
        return HttpResponseForbidden('POST required')
    rev = Transaction(
        account=txn.account,
        date=date.today(),
        description=f"Reversal of #{txn.id}: {txn.description}",
        reference=f"REV-{txn.reference}"[:100] if txn.reference else f"REV-{txn.id}",
        debit=txn.credit,
        credit=txn.debit,
        created_by=request.user,
    )
    rev.save()
    _post_txn_alerts(rev)
    messages.success(request, f'Reversal created (#{rev.id}).')
    return redirect('cash_management:account_ledger', pk=txn.account_id)


@login_required
def analytics(request):
    # Summaries for current year
    from django.db.models.functions import TruncMonth
    current_year = date.today().year
    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    qs = (
        Transaction.objects
        .filter(date__year=current_year)
        .annotate(month=TruncMonth('date'))
        .values('month')
        .annotate(inflow=Coalesce(Sum('credit'), dec0), outflow=Coalesce(Sum('debit'), dec0))
        .order_by('month')
    )
    months = [r['month'].strftime('%Y-%m') for r in qs]
    inflow = [float(r['inflow']) for r in qs]
    outflow = [float(r['outflow']) for r in qs]
    return render(request, 'cash_management/analytics.html', {
        'months': months,
        'inflow': inflow,
        'outflow': outflow,
    })


@login_required
def cash_summary(request):
    """All bank cash summary with ETB conversion using daily CBE rates.

    Shows each account with native currency balance and ETB equivalent. Also
    computes totals for ETB, FOREX (converted), and grand total.
    """
    if is_clerk(request.user):
        # clerks land on daily view, but summary is read-only; still allow view
        pass

    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    accounts = (
        BankAccount.objects
        .annotate(
            total_credit=Coalesce(Sum('transaction__credit'), dec0),
            total_debit=Coalesce(Sum('transaction__debit'), dec0),
        )
        .annotate(balance=ExpressionWrapper(F('total_credit') - F('total_debit'), output_field=DecimalField(max_digits=12, decimal_places=2)))
        .order_by('bank_name', 'name')
    )

    rates = get_or_update_today_rates()
    rows = []
    total_etb_native = 0.0
    total_forex_to_etb = 0.0

    for a in accounts:
        bal = float(a.balance or 0)
        ccy = (a.currency or 'ETB').upper()
        rate_val = rates.get(ccy)
        rate = float(rate_val) if rate_val is not None else None
        etb_equiv = (bal * rate) if (ccy != 'ETB' and rate is not None) else (bal if ccy == 'ETB' else None)
        remark = ''
        nm_up = (a.name or '').upper()
        if ccy != 'ETB':
            remark = 'FOREX'
        elif 'ECX' in nm_up:
            remark = 'ECX'
        elif 'SPECIAL' in nm_up:
            remark = 'SPECIAL'

        remark = ''
        nm_up = (a.name or '').upper()
        if ccy != 'ETB':
            remark = 'FOREX'
        elif 'ECX' in nm_up:
            remark = 'ECX'
        elif 'SPECIAL' in nm_up:
            remark = 'SPECIAL'

        rows.append({
            'name': a.name,
            'bank': a.bank_name,
            'currency': ccy,
            'balance': bal,
            'rate': rate,
            'etb_equiv': etb_equiv,
            'remark': remark,
            'row_class': ('row-forex' if remark == 'FOREX' else ('row-ecx' if remark == 'ECX' else ('row-special' if remark == 'SPECIAL' else ''))),
        })
        if ccy == 'ETB':
            total_etb_native += bal
        elif etb_equiv is not None:
            total_forex_to_etb += etb_equiv

    grand_total = total_etb_native + total_forex_to_etb

    # Share meter per row (based on ETB equivalent)
    if grand_total > 0:
        for r in rows:
            eq = r.get('etb_equiv')
            r['share_pct'] = round((eq or 0) * 100.0 / grand_total, 2) if eq is not None else None
    else:
        for r in rows:
            r['share_pct'] = None

    # Compact list of rates used for display
    rates_used = {k: float(v) for k, v in rates.items() if k != 'ETB'}

    context = {
        'rows': rows,
        'total_etb_native': total_etb_native,
        'total_forex_to_etb': total_forex_to_etb,
        'grand_total': grand_total,
        'rates': rates_used,
    }
    return render(request, 'cash_management/cash_summary.html', context)


@login_required
def live_cash(request):
    """Bloomberg-style live cash monitor with rapid updates.

    Shows today's transactions streaming in chronological order with
    color-coded amounts and attachment indicators. Uses polling via
    ``live_cash_feed`` endpoint.
    """
    import datetime as _dt
    today = _dt.date.today()
    # Optional date filter (YYYY-MM-DD). Defaults to today.
    def _parse(d: str):
        try:
            y, m, d = [int(x) for x in d.split('-')]
            return _dt.date(y, m, d)
        except Exception:
            return None
    date_s = (request.GET.get('date') or '').strip()
    selected_date = _parse(date_s) or today
    currency = (request.GET.get('currency') or '').strip().upper()

    base = Transaction.objects.filter(date=selected_date)
    if currency:
        base = base.filter(account__currency__iexact=currency)

    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    agg = base.aggregate(
        inflow=Coalesce(Sum('credit'), dec0),
        outflow=Coalesce(Sum('debit'), dec0),
    )

    # Last 50 entries for initial render (ascending for readability)
    initial = list(base.order_by('-date', '-id')[:50])
    initial.reverse()
    last_id = initial[-1].id if initial else 0

    rates = get_or_update_today_rates()

    def _row(t: Transaction):
        amt = float(t.credit) - float(t.debit)
        ccy = (t.account.currency or 'ETB').upper()
        rate = float(rates.get(ccy, 1.0) or 1.0) if ccy != 'ETB' else 1.0
        etb = amt if ccy == 'ETB' else amt * rate
        return {
            'id': t.id,
            'time': t.date.strftime('%H:%M'),
            'account': t.account.name,
            'bank': t.account.bank_name,
            'currency': ccy,
            'debit': float(t.debit),
            'credit': float(t.credit),
            'amount': amt,
            'etb': etb,
            'desc': t.description,
            'ref': t.reference,
            'attachment': t.attachment.url if t.attachment else '',
        }

    rows = [_row(t) for t in initial]

    context = {
        'today': today,
        'selected_date': selected_date,
        'is_today': (selected_date == today),
        'selected_currency': currency,
        'kpi_inflow': float(agg['inflow'] or 0),
        'kpi_outflow': float(agg['outflow'] or 0),
        'kpi_net': float(agg['inflow'] or 0) - float(agg['outflow'] or 0),
        'rows': rows,
        'last_id': last_id,
    }
    return render(request, 'cash_management/live.html', context)


@login_required
def live_cash_feed(request):
    """JSON feed of today's transactions after a given id.

    Query params:
      - after: last seen transaction id
      - currency: optional filter by account currency
    """
    import datetime as _dt
    try:
        after = int(request.GET.get('after') or 0)
    except Exception:
        after = 0
    currency = (request.GET.get('currency') or '').strip().upper()
    # Allow past date feed for the monitor
    def _parse(d: str):
        try:
            y, m, d = [int(x) for x in d.split('-')]
            return _dt.date(y, m, d)
        except Exception:
            return None
    date_s = (request.GET.get('date') or '').strip()
    target_date = _parse(date_s) or _dt.date.today()

    base = Transaction.objects.filter(date=target_date)
    if currency:
        base = base.filter(account__currency__iexact=currency)
    qs = base.filter(id__gt=after).order_by('date', 'id')[:200]

    dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    agg = base.aggregate(
        inflow=Coalesce(Sum('credit'), dec0),
        outflow=Coalesce(Sum('debit'), dec0),
    )

    rates = get_or_update_today_rates()
    rows = []
    last_id = after
    for t in qs:
        last_id = max(last_id, t.id)
        amt = float(t.credit) - float(t.debit)
        ccy = (t.account.currency or 'ETB').upper()
        rate = float(rates.get(ccy, 1.0) or 1.0) if ccy != 'ETB' else 1.0
        etb = amt if ccy == 'ETB' else amt * rate
        rows.append({
            'id': t.id,
            'time': t.date.strftime('%H:%M'),
            'account': t.account.name,
            'bank': t.account.bank_name,
            'currency': ccy,
            'debit': float(t.debit),
            'credit': float(t.credit),
            'amount': amt,
            'etb': etb,
            'desc': t.description,
            'ref': t.reference,
            'attachment': t.attachment.url if t.attachment else '',
        })

    data = {
        'last_id': last_id,
        'rows': rows,
        'kpi': {
            'inflow': float(agg['inflow'] or 0),
            'outflow': float(agg['outflow'] or 0),
            'net': float(agg['inflow'] or 0) - float(agg['outflow'] or 0),
        },
    }
    return JsonResponse(data)


def _post_txn_alerts(txn: Transaction) -> None:
    try:
        # Check balance threshold
        dec0 = Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
        agg = Transaction.objects.filter(account=txn.account).aggregate(
            total_credit=Coalesce(Sum('credit'), dec0), total_debit=Coalesce(Sum('debit'), dec0)
        )
        balance = float(agg['total_credit']) - float(agg['total_debit'])
        alerts = []
        if txn.account.threshold and balance < float(txn.account.threshold):
            alerts.append(f"Balance for {txn.account.name} fell below threshold: {balance:.2f}")
        # Large transaction
        amt = max(float(txn.debit or 0), float(txn.credit or 0))
        if txn.account.large_txn_limit and amt >= float(txn.account.large_txn_limit):
            alerts.append(f"Large transaction on {txn.account.name}: {amt:.2f}")
        if not alerts:
            return
        subject = "Cash Alerts"
        body = "\n".join(alerts)
        # Email Owners group if possible
        owners = Group.objects.filter(name='Owner').first()
        emails = []
        if owners:
            emails = [u.email for u in owners.user_set.filter(is_active=True) if u.email]
        if not emails:
            return
        try:
            send_mail(subject, body, None, emails, fail_silently=True)
        except Exception:
            pass
    except Exception:
        pass


@login_required
@owner_required
def account_new(request):
    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bank account created.')
            return redirect('cash_management:dashboard')
    else:
        form = BankAccountForm()
    return render(request, 'cash_management/account_form.html', {'form': form, 'title': 'New Account'})


@login_required
@owner_required
def account_edit(request, pk: int):
    account = get_object_or_404(BankAccount, pk=pk)
    if request.method == 'POST':
        form = BankAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bank account updated.')
            return redirect('cash_management:dashboard')
    else:
        form = BankAccountForm(instance=account)
    return render(request, 'cash_management/account_form.html', {'form': form, 'title': 'Edit Account'})


@login_required
@owner_required
def bank_register(request):
    """Simple, admin-only form to register a bank account with currency type, branch and purpose."""
    if request.method == 'POST':
        form = BankRegistrationForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, 'Bank registered successfully.')
            # Redirect to the bank detail page if possible
            return redirect('cash_management:bank_detail', name=obj.bank_name)
    else:
        form = BankRegistrationForm()
    return render(request, 'cash_management/bank_register.html', {'form': form, 'title': 'Register Bank'})
