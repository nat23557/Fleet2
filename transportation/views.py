# --------------------------------
# transportation/views.py
# --------------------------------

from django.shortcuts import (
    render, redirect, get_object_or_404
)
from django.contrib.auth import (
    authenticate, login, logout, update_session_auth_hash
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.http import JsonResponse
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from decimal import Decimal
from django.forms import inlineformset_factory
from io import BytesIO
from django.db.models.functions import Coalesce
from django.utils.http import url_has_allowed_host_and_scheme
from django.urls import reverse

from .models import (
    Staff, Driver, Truck, Cargo, Trip, TripFinancial, MajorAccident,
    ServiceRecord, ReplacedItem, Expense, Invoice, OfficeUsage, GPSRecord, OperationalExpenseDetail, Geofence
)
from .forms import (
    StaffForm, DriverForm, TruckForm, CargoForm, DriverTripCreateForm, TripFinancialForm,
    UpdateUserForm, ChangePasswordForm, MajorAccidentForm, ServiceRecordForm,
    ReplacedItemForm, ExpenseForm, InvoiceForm, OfficeUsageForm
)

import json
from datetime import datetime, timedelta
from calendar import monthrange
from collections import defaultdict, namedtuple

from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin

# Import only the operational expense form (no inline formset needed)
from .forms import OperationalExpenseDetailForm
from .models import TripFinancial, OperationalExpenseDetail, Trip
from .tasks import update_gps_records_sync   # Synchronous GPS updater
try:
    # Optional dependency; used to embed attachments into generated PDFs
    from PyPDF2 import PdfReader, PdfWriter
except Exception:
    PdfReader = None
    PdfWriter = None

# -----------------------------
# Reverse geocoding helper
# -----------------------------
import requests
from functools import lru_cache

@lru_cache(maxsize=512)
def reverse_geocode_location(lat, lng):
    """Resolve a human-readable place name from coordinates.

    Uses OpenStreetMap Nominatim service. Returns a short readable
    name if available; otherwise returns None.
    """
    try:
        if lat is None or lng is None:
            return None
        url = "https://nominatim.openstreetmap.org/reverse"
        headers = {"User-Agent": "Fleet2/1.0 (+https://example.com)"}
        params = {"format": "jsonv2", "lat": float(lat), "lon": float(lng)}
        resp = requests.get(url, headers=headers, params=params, timeout=6)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # Prefer a compact name from address components
        addr = data.get("address", {})
        for key in ("city", "town", "village", "hamlet", "municipality"):
            if addr.get(key):
                # Include country short if present
                country = addr.get("country_code", "").upper()
                return f"{addr[key]}{', ' + country if country else ''}"
        # Fallback to display_name
        dn = data.get("display_name")
        if isinstance(dn, str) and dn:
            # Shorten long display names
            parts = dn.split(",")
            return ", ".join([p.strip() for p in parts[:3]])
        return None
    except Exception:
        return None


# --------------------------------
# Zero-to-One: Weekly Story Mode
# --------------------------------
@login_required
def weekly_story_mode(request):
    """Generate a plain-English weekly brief for managers.

    Default window is the most recent completed week (Mon–Sun).
    Override using GET params:
      - start=YYYY-MM-DD
      - end=YYYY-MM-DD
      - week=current|prev (default prev)
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    tz = timezone.get_current_timezone()

    # Determine week window
    start_param = request.GET.get('start')
    end_param = request.GET.get('end')
    mode = (request.GET.get('week') or 'prev').lower()

    def _aware_day(d, end=False):
        if isinstance(d, datetime):
            dt = d
        else:
            # date object
            dt = datetime(d.year, d.month, d.day, 23, 59, 59) if end else datetime(d.year, d.month, d.day, 0, 0, 0)
        return timezone.make_aware(dt, tz) if timezone.is_naive(dt) else dt

    week_label = None

    if start_param and end_param:
        try:
            sd = datetime.strptime(start_param, '%Y-%m-%d').date()
            ed = datetime.strptime(end_param, '%Y-%m-%d').date()
            week_start = _aware_day(sd, end=False)
            week_end = _aware_day(ed, end=True)
            week_label = f"{sd.strftime('%b %d')}–{ed.strftime('%b %d, %Y')}"
        except Exception:
            week_start = None
            week_end = None
    if not (start_param and end_param):
        today = timezone.localdate()
        # Python weekday: Mon=0..Sun=6
        dow = today.weekday()
        if mode == 'current':
            monday = today - timedelta(days=dow)
            sunday = monday + timedelta(days=6)
        else:
            # previous complete week
            monday = today - timedelta(days=dow + 7)
            sunday = monday + timedelta(days=6)
        week_start = _aware_day(monday, end=False)
        week_end = _aware_day(sunday, end=True)
        week_label = f"{monday.strftime('%b %d')}–{sunday.strftime('%b %d, %Y')}"

    # Query completed trips for the window
    trips_qs = (Trip.objects
                .filter(status=Trip.STATUS_COMPLETED,
                        end_time__gte=week_start,
                        end_time__lte=week_end)
                .select_related('truck', 'driver__staff_profile__user')
                .order_by('end_time'))

    # If nothing to report, render a gentle empty brief
    if not trips_qs.exists():
        return render(request, 'transportation/weekly_story.html', {
            'user_role': user_role,
            'week_label': week_label,
            'story_paragraphs': [
                "No completed trips in the selected week. Operations were quiet — no actions required."
            ],
            'highlights': [],
            'stats': {},
        })

    # Helpers
    def d0(x):
        return x or Decimal('0')

    # Aggregate financials
    fin_qs = TripFinancial.objects.filter(trip__in=trips_qs).select_related('trip__truck', 'trip__driver__staff_profile__user')
    fin_totals = fin_qs.aggregate(revenue=Sum('total_revenue'), expense=Sum('total_expense'), income=Sum('income_before_tax'))
    total_revenue = d0(fin_totals.get('revenue'))
    total_expense = d0(fin_totals.get('expense'))
    total_income = d0(fin_totals.get('income'))
    margin_pct = (total_income / total_revenue * Decimal('100')) if total_revenue else Decimal('0')

    # Distance and basic counts
    trip_count = trips_qs.count()
    trucks_used = len({t.truck_id for t in trips_qs if t.truck_id})
    drivers_used = len({t.driver_id for t in trips_qs if t.driver_id})
    # Sum distance with fallback to calculated_distance
    total_km = Decimal('0')
    for t in trips_qs:
        try:
            v = t.calculated_distance() if callable(getattr(t, 'calculated_distance', None)) else t.distance_traveled
            total_km += Decimal(str(v or 0))
        except Exception:
            pass

    # Top driver and truck by income
    driver_stats = {}
    truck_stats = {}
    route_stats = {}
    expense_by_cat = {}

    # For outliers: expense per km per trip
    exp_per_km_list = []

    for fin in fin_qs.prefetch_related('expenses'):
        t = fin.trip
        drv = t.driver
        trk = t.truck
        rkey = (t.start_location or '—', t.end_location or '—')

        # Driver
        if drv:
            dkey = drv.pk
            obj = driver_stats.setdefault(dkey, {
                'driver': drv,
                'revenue': Decimal('0'),
                'expense': Decimal('0'),
                'income': Decimal('0'),
                'trips': 0,
            })
            obj['revenue'] += d0(fin.total_revenue)
            obj['expense'] += d0(fin.total_expense)
            obj['income'] += d0(fin.income_before_tax)
            obj['trips'] += 1

        # Truck
        if trk:
            tkey = trk.pk
            tobj = truck_stats.setdefault(tkey, {
                'truck': trk,
                'revenue': Decimal('0'),
                'expense': Decimal('0'),
                'income': Decimal('0'),
                'trips': 0,
            })
            tobj['revenue'] += d0(fin.total_revenue)
            tobj['expense'] += d0(fin.total_expense)
            tobj['income'] += d0(fin.income_before_tax)
            tobj['trips'] += 1

        # Route group
        robj = route_stats.setdefault(rkey, {
            'start': rkey[0], 'end': rkey[1],
            'revenue': Decimal('0'), 'expense': Decimal('0'), 'income': Decimal('0'), 'trips': 0
        })
        robj['revenue'] += d0(fin.total_revenue)
        robj['expense'] += d0(fin.total_expense)
        robj['income'] += d0(fin.income_before_tax)
        robj['trips'] += 1

        # Expense categories
        for e in fin.expenses.all():
            expense_by_cat[e.category] = expense_by_cat.get(e.category, Decimal('0')) + d0(e.amount)

        # Expense per km (outlier detector)
        try:
            v = t.calculated_distance() if callable(getattr(t, 'calculated_distance', None)) else t.distance_traveled
            km = float(v or 0)
            if km > 0:
                exp_per_km_list.append({
                    'trip': t,
                    'value': float(d0(fin.total_expense)) / km,
                })
        except Exception:
            pass

    top_driver = max(driver_stats.values(), key=lambda x: x['income']) if driver_stats else None
    top_truck = max(truck_stats.values(), key=lambda x: x['income']) if truck_stats else None
    # Best and worst routes by margin
    for r in route_stats.values():
        r['margin'] = (r['income'] / r['revenue'] * Decimal('100')) if r['revenue'] else Decimal('0')
    best_route = max(route_stats.values(), key=lambda x: (x['margin'], x['income'])) if route_stats else None
    worst_route = min(route_stats.values(), key=lambda x: (x['margin'], x['income'])) if route_stats else None

    # Negative-margin trips
    negative_trips = [fin.trip for fin in fin_qs if d0(fin.income_before_tax) < 0]

    # Expense leader category
    top_exp_cat = None
    if expense_by_cat:
        k, v = max(expense_by_cat.items(), key=lambda kv: kv[1])
        share = (v / total_expense * Decimal('100')) if total_expense else Decimal('0')
        top_exp_cat = {'category': k, 'amount': v, 'share_pct': share}

    # AR status: invoices for this period
    unpaid = Invoice.objects.filter(trip__in=trips_qs, is_paid=False)
    overdue = unpaid.filter(due_date__lt=timezone.localdate())

    # Outliers: top 3 expense-per-km
    exp_per_km_list.sort(key=lambda x: x['value'], reverse=True)
    outliers = exp_per_km_list[:3]

    # Suggestions: routes below 20% margin with >=2 trips
    suggestions = []
    target = Decimal('20')
    for r in sorted(route_stats.values(), key=lambda x: (x['margin'])):
        if r['trips'] >= 2 and r['margin'] < target and r['revenue'] > 0:
            # Additional revenue needed to reach target margin
            # new_margin = 1 - expense/(revenue+Δ) >= 0.20  => Δ = expense/0.8 - revenue
            needed = (r['expense'] / Decimal('0.80')) - r['revenue']
            if needed > 0:
                pct = (needed / r['revenue'] * Decimal('100')) if r['revenue'] else Decimal('0')
                suggestions.append({
                    'route': f"{r['start']} → {r['end']}",
                    'increase_pct': float(pct.quantize(Decimal('1.00'))),
                    'trips': r['trips']
                })
        if len(suggestions) >= 3:
            break

    # Build narrative
    def fmt_money(x):
        try:
            return f"{float(x):,.2f}"
        except Exception:
            return str(x)

    p1 = (
        f"Between {week_label}, we completed {trip_count} trip{'s' if trip_count != 1 else ''} "
        f"across {trucks_used} truck{'s' if trucks_used != 1 else ''} and {drivers_used} driver{'s' if drivers_used != 1 else ''}. "
        f"Total distance: {float(total_km):,.0f} km. "
        f"Revenue ETB {fmt_money(total_revenue)}, expenses ETB {fmt_money(total_expense)}, "
        f"profit ETB {fmt_money(total_income)} with a {float(margin_pct):.1f}% margin."
    )

    p2 = None
    if top_driver and top_truck:
        dname = top_driver['driver'].staff_profile.user.get_full_name() or top_driver['driver'].staff_profile.user.username
        p2 = (
            f"Top performers: Driver {dname} led with ETB {fmt_money(top_driver['income'])} across {top_driver['trips']} trips; "
            f"truck {top_truck['truck'].plate_number} generated ETB {fmt_money(top_truck['income'])}."
        )

    p3 = None
    if best_route and worst_route:
        p3 = (
            f"Best lane: {best_route['start']} → {best_route['end']} at {float(best_route['margin']):.1f}% margin. "
            f"Watchout: {worst_route['start']} → {worst_route['end']} ran at {float(worst_route['margin']):.1f}% margin."
        )

    p4 = None
    if negative_trips:
        p4 = f"{len(negative_trips)} trip(s) recorded negative profit; review tariffs and driver expenses on these jobs."

    p5 = None
    if top_exp_cat:
        p5 = (
            f"Expense mix: {top_exp_cat['category']} led costs at ETB {fmt_money(top_exp_cat['amount'])} "
            f"({float(top_exp_cat['share_pct']):.1f}% of spend)."
        )

    p6 = None
    if unpaid.exists():
        p6 = (
            f"Accounts receivable: {unpaid.count()} invoice(s) pending for the week; {overdue.count()} already overdue."
        )

    # Highlights bullets
    highlights = []
    for o in outliers:
        t = o['trip']
        highlights.append(
            f"High expense/km: Trip #{t.truck_trip_number or t.pk} on {t.truck.plate_number} at ETB {o['value']:.2f}/km"
        )
    for s in suggestions:
        highlights.append(
            f"Pricing: Raise {s['route']} tariffs by ~{s['increase_pct']:.0f}% (based on {s['trips']} trips) to target 20% margin"
        )

    story_paragraphs = [p for p in [p1, p2, p3, p4, p5, p6] if p]

    # Provide typed paragraphs for client-side filtering (Executive / Ops / Finance)
    story_typed = []
    if p1:
        story_typed.append({'text': p1, 'topic': 'summary'})
    if p2:
        story_typed.append({'text': p2, 'topic': 'performance'})
    if p3:
        story_typed.append({'text': p3, 'topic': 'routes'})
    if p4:
        story_typed.append({'text': p4, 'topic': 'risk'})
    if p5:
        story_typed.append({'text': p5, 'topic': 'finance'})
    if p6:
        story_typed.append({'text': p6, 'topic': 'ar'})

    # Previous week deltas for zero-to-one context
    prev_monday = (week_start - timedelta(days=7)).date()
    prev_sunday = (week_end - timedelta(days=7)).date()
    prev_start = timezone.make_aware(datetime(prev_monday.year, prev_monday.month, prev_monday.day, 0, 0, 0), tz)
    prev_end = timezone.make_aware(datetime(prev_sunday.year, prev_sunday.month, prev_sunday.day, 23, 59, 59), tz)
    prev_trips = Trip.objects.filter(status=Trip.STATUS_COMPLETED, end_time__gte=prev_start, end_time__lte=prev_end)
    prev_fin = TripFinancial.objects.filter(trip__in=prev_trips).aggregate(r=Sum('total_revenue'), e=Sum('total_expense'), i=Sum('income_before_tax'))
    prev_revenue = d0(prev_fin.get('r'))
    prev_income = d0(prev_fin.get('i'))
    prev_margin = (prev_income / prev_revenue * Decimal('100')) if prev_revenue else Decimal('0')
    prev_trip_count = prev_trips.count()

    def _pct(curr, prev):
        try:
            if prev and float(prev) != 0.0:
                return float((Decimal(curr) - Decimal(prev)) / Decimal(prev) * Decimal('100'))
            return 0.0
        except Exception:
            return 0.0

    deltas = {
        'revenue_pct': round(_pct(total_revenue, prev_revenue), 1),
        'income_pct': round(_pct(total_income, prev_income), 1),
        'margin_pct': round(_pct(margin_pct, prev_margin), 1),
        'trips_abs': int(trip_count - prev_trip_count),
    }

    # Share URL for this week
    try:
        share_url = request.build_absolute_uri(
            reverse('weekly_story_mode') + f"?start={week_start.date()}&end={week_end.date()}"
        )
    except Exception:
        share_url = None

    context = {
        'user_role': user_role,
        'week_label': week_label,
        'story_paragraphs': story_paragraphs,
        'story_typed': story_typed,
        'highlights': highlights,
        'stats': {
            'trips': trip_count,
            'trucks': trucks_used,
            'drivers': drivers_used,
            'km': float(total_km),
            'revenue': float(total_revenue),
            'expense': float(total_expense),
            'income': float(total_income),
            'margin': float(margin_pct),
        },
        'deltas': deltas,
        'share_url': share_url,
    }

    return render(request, 'transportation/weekly_story.html', context)

# ====================================================
# MENU: transportation/views.py
# ----------------------------------------------------
# 1. Helper Functions for Role Checking:
#      - get_user_role(request)
#      - check_user_role(request, allowed_roles)
#
# 2. Authentication:
#      - login_view(request)
#      - logout_view(request)
#
# 3. User Profile Management:
#      - user_profile(request)
#      - update_profile(request)
#      - change_password(request)
#
# 4. Home/Index:
#      - index(request)
#
# 5. Staff Views:
#      - staff_list(request)
#      - staff_detail(request, pk)
#      - staff_create(request)
#      - staff_update(request, pk)
#      - staff_delete(request, pk)
#
# 6. Driver Views:
#      - driver_list(request)
#      - driver_detail(request, pk)
#      - driver_create(request)
#      - driver_update(request, pk)
#      - driver_delete(request, pk)
#
# 7. Truck Views:
#      - truck_list(request)
#      - truck_detail(request, pk)
#      - truck_create(request)
#      - truck_update(request, pk)
#      - truck_delete(request, pk)
#
# 8. Cargo Views:
#      - cargo_list(request)
#      - cargo_detail(request, pk)
#      - cargo_create(request)
#      - cargo_update(request, pk)
#      - cargo_delete(request, pk)
#
# 9. Major Accident Views:
#      - accident_list(request, truck_id)
#      - accident_detail(request, pk)
#      - accident_create(request, truck_id)
#      - accident_update(request, pk)
#      - accident_delete(request, pk)
#
# 10. Service Record Views:
#      - service_list(request, truck_id)
#      - service_detail(request, pk)
#      - service_create(request, truck_id)
#      - service_update(request, pk)
#      - service_delete(request, pk)
#
# 11. Replaced Item Views:
#      - replaced_item_list(request, truck_id)
#      - replaced_item_detail(request, pk)
#      - replaced_item_create(request, truck_id)
#      - replaced_item_update(request, pk)
#      - replaced_item_delete(request, pk)
#
# 12. Trip Views:
#      * Function-based:
#          - trip_list(request)
#          - trip_detail(request, pk)
#          - trip_create(request)
#          - trip_update(request, pk)
#          - trip_delete(request, pk)
#          - trip_complete_confirmation(request, trip_id)
#          - trip_complete(request, trip_id)
#      * Class-based:
#          - TripListView
#          - TripDetailView
#          - TripCreateView
#          - TripUpdateView
#
# 13. Trip Financial Views:
#      - TripFinancialUpdateView
#
# 14. Expense Views:
#      - ExpenseCreateView
#      - ExpenseUpdateView
#      - expense_delete(request, pk)
#
# 15. Invoice Views:
#      - InvoiceCreateView
#      - InvoiceUpdateView
#
# 16. Additional: Report Views:
#      - report_index(request)
#      - MonthlyReportView
#      - AnnualReportView
#
# 17. Additional: Office Usage Views:
#      - OfficeUsageListView
#      - OfficeUsageDetailView
#      - OfficeUsageCreateView
#      - OfficeUsageUpdateView
#      - OfficeUsageDeleteView
# ====================================================

# --------------------------------
# Helper Functions for Role Checking
# --------------------------------
def get_user_role(request):
    """
    Returns:
      - "ADMIN" if the user is a Django superuser.
      - staff_instance.role if found in the Staff model.
      - None if no role is found.
    """
    if request.user.is_authenticated:
        # 1. If user is a superuser, treat them as ADMIN
        if request.user.is_superuser:
            return "ADMIN"

        # 2. Otherwise, look in the Staff model
        staff_instance = Staff.objects.filter(user=request.user).first()
        if staff_instance and staff_instance.role:
            return staff_instance.role.strip().upper()
    return None


def check_user_role(request, allowed_roles):
    """
    1. Ensure the user has a valid role in ['ADMIN','MANAGER','DRIVER'].
    2. Check if the user's role is in the allowed_roles list.

    Returns:
      (True, user_role) if allowed,
      (False, user_role) otherwise.
    """
    raw_role = get_user_role(request)
    user_role = (raw_role or "").strip().upper()

    # If not ADMIN, MANAGER, or DRIVER, deny
    if user_role not in ['ADMIN', 'MANAGER', 'DRIVER']:
        messages.error(request, "You do not have permission to access any functionality. Please contact the admin.")
        return False, user_role or None

    # If role is valid but not in allowed_roles, also deny
    if user_role not in allowed_roles:
        messages.error(request, f"You do not have permission to perform this action (Your role is {user_role}).")
        return False, user_role

    # Otherwise, permitted
    return True, user_role



# --------------------------------
# 1. Authentication
# --------------------------------
def login_view(request):
    """
    A custom login view with a dark, mysterious login form.
    Captures the user's role on successful login and stores it in session.
    """
    error_message = None

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            # Log the user in
            login(request, user)

            # Fetch the user's role from the Staff model
            staff_obj = Staff.objects.filter(user=user).first()
            if staff_obj:
                role_value = staff_obj.role.strip().upper() if staff_obj.role else None
                request.session['user_role'] = role_value
            else:
                # If not found or no valid role, store None
                request.session['user_role'] = None

            # Redirect to a simple hub after login (for ADMIN/MANAGER);
            # drivers still get redirected by index() logic if they visit home.
            try:
                role = get_user_role(request)
                if role in ['ADMIN', 'MANAGER']:
                    return redirect('home_hub')
            except Exception:
                pass
            return redirect('home')
        else:
            error_message = "Invalid username or password."

    return render(request, 'login.html', {'error_message': error_message})



@login_required
def logout_view(request):
    """
    Logs out the user and redirects to the login page.
    """
    logout(request)
    return redirect('login')


# --------------------------------
# 2. User Profile Management
# --------------------------------
@login_required
def user_profile(request):
    """
    Displays the logged-in user's profile details.
    """
    user_role = get_user_role(request)
    # Even for user profile, ensure they're at least one of the three roles:
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    return render(request, 'transportation/user_profile.html', {
        'user': request.user,
        'user_role': user_role
    })


@login_required
def update_profile(request):
    """
    Allows users to update their profile details.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    if request.method == "POST":
        form = UpdateUserForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('home')
    else:
        form = UpdateUserForm(instance=request.user)

    return render(request, 'transportation/update_profile.html', {
        'form': form,
        'user_role': user_role
    })


@login_required
def change_password(request):
    """
    Allows users to change their password securely.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    if request.method == "POST":
        form = ChangePasswordForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)  # Prevents logout after password change
            messages.success(request, "Password updated successfully!")
            return redirect('home')
    else:
        form = ChangePasswordForm(request.user)

    return render(request, 'transportation/change_password.html', {
        'form': form,
        'user_role': user_role
    })


# --------------------------------
# 3. Home/Index
# --------------------------------

# ---------------------------------------------------
# Index View (with GPS data update on each refresh)
# ---------------------------------------------------
@login_required
def index(request):
    """Role-aware landing.

    Drivers are redirected to a minimal driver home without maps/GPS.
    Admin/Manager see the standard dashboard with maps.
    """
    user_role = get_user_role(request)
    if user_role == "SUPERUSER":
        user_role = "ADMIN"

    # For drivers, send to a dedicated, map-free home.
    if user_role == 'DRIVER':
        return redirect('driver_home')

    # Only update GPS data for non-driver dashboards
    update_gps_records_sync()

    if user_role not in ['ADMIN', 'MANAGER', 'DRIVER']:
        messages.error(request, "You do not have the required permissions.")
        return redirect('login')

    current_time = timezone.localtime(timezone.now())
    context = {
        'user_role': user_role,
        'current_time': current_time,
        'driver_has_active_trip': False,
        'driver_has_active_trip': False,
    }

    if user_role in ['ADMIN', 'MANAGER']:
        # Base fleet/driver counts
        total_trucks = Truck.objects.count()
        available_trucks = Truck.objects.filter(status='AVAILABLE').count()
        in_use_trucks = Truck.objects.filter(status='IN_USE').count()
        maintenance_trucks = Truck.objects.filter(status='MAINTENANCE').count()
        fleet_utilization = round((in_use_trucks / total_trucks) * 100) if total_trucks else 0

        total_drivers = Driver.objects.count()
        drivers_on_trip = Driver.objects.filter(trip__status=Trip.STATUS_IN_PROGRESS).distinct().count()
        drivers_available = max(total_drivers - drivers_on_trip, 0)
        avg_experience = Driver.objects.aggregate(avg_years=Avg('years_of_experience'))['avg_years'] or 0

        finance_aggregate = TripFinancial.objects.aggregate(
            total_revenue=Coalesce(Sum('total_revenue'), Decimal('0')),
            total_expense=Coalesce(Sum('total_expense'), Decimal('0')),
            net_income=Coalesce(Sum('income_before_tax'), Decimal('0')),
        )

        active_trips = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS).select_related(
            'truck', 'driver__staff_profile__user'
        ).order_by('start_time', 'truck__plate_number')
        recent_trips = Trip.objects.select_related(
            'truck', 'driver__staff_profile__user'
        ).order_by('-end_time', '-start_time', '-id')[:6]

        top_drivers = Driver.objects.select_related('staff_profile__user').annotate(
            completed_trips=Count('trip', filter=Q(trip__status=Trip.STATUS_COMPLETED))
        ).order_by('-completed_trips', 'staff_profile__user__first_name', 'staff_profile__user__username')[:5]

        trucks_overview = Truck.objects.select_related('driver__staff_profile__user').order_by(
            'status', '-is_in_duty', 'plate_number'
        )[:8]

        completed_this_month = Trip.objects.filter(
            status=Trip.STATUS_COMPLETED,
            end_time__year=current_time.year,
            end_time__month=current_time.month,
        ).count()

        # Additional: Alerts and month KPIs (for immediate render; also kept live via /dashboard/data)
        today = timezone.localdate()
        now_dt = current_time
        tz = timezone.get_current_timezone()
        # This month window
        m_start = timezone.make_aware(datetime(now_dt.year, now_dt.month, 1, 0, 0, 0), tz)
        last_day = monthrange(now_dt.year, now_dt.month)[1]
        m_end = timezone.make_aware(datetime(now_dt.year, now_dt.month, last_day, 23, 59, 59), tz)
        # Previous month window
        if now_dt.month == 1:
            pm_year, pm_month = now_dt.year - 1, 12
        else:
            pm_year, pm_month = now_dt.year, now_dt.month - 1
        pm_last_day = monthrange(pm_year, pm_month)[1]
        pm_start = timezone.make_aware(datetime(pm_year, pm_month, 1, 0, 0, 0), tz)
        pm_end = timezone.make_aware(datetime(pm_year, pm_month, pm_last_day, 23, 59, 59), tz)

        curr_fin = TripFinancial.objects.filter(
            trip__end_time__gte=m_start, trip__end_time__lte=m_end
        ).aggregate(revenue=Sum('total_revenue'), expense=Sum('total_expense'), income=Sum('income_before_tax'))
        prev_fin = TripFinancial.objects.filter(
            trip__end_time__gte=pm_start, trip__end_time__lte=pm_end
        ).aggregate(revenue=Sum('total_revenue'), income=Sum('income_before_tax'))

        revenue_month = float(curr_fin.get('revenue') or 0)
        income_month = float(curr_fin.get('income') or 0)
        prev_revenue = float(prev_fin.get('revenue') or 0)
        prev_income = float(prev_fin.get('income') or 0)

        def pct_change(curr, prev):
            if prev and prev != 0:
                return round(((curr - prev) / prev) * 100.0, 1)
            return 0.0

        revenue_change_pct = pct_change(revenue_month, prev_revenue)
        income_change_pct = pct_change(income_month, prev_income)

        unpaid_invoices_count = Invoice.objects.filter(is_paid=False).count()
        overdue_unpaid_count = Invoice.objects.filter(is_paid=False, due_date__lt=today).count()
        in_30 = today + timedelta(days=30)
        services_due_count = ServiceRecord.objects.filter(next_service_date__gte=today, next_service_date__lte=in_30).count()
        licenses_expiring_count = Driver.objects.filter(
            Q(djibouti_license_expiration__gte=today, djibouti_license_expiration__lte=in_30)
            | Q(ethiopian_license_expiration__gte=today, ethiopian_license_expiration__lte=in_30)
        ).count()
        completed_today = Trip.objects.filter(status=Trip.STATUS_COMPLETED, end_time__date=today).count()

        context.update({
            'fleet_metrics': {
                'total': total_trucks,
                'available': available_trucks,
                'in_use': in_use_trucks,
                'maintenance': maintenance_trucks,
                'utilization': fleet_utilization,
                'completed_this_month': completed_this_month,
            },
            'driver_metrics': {
                'total': total_drivers,
                'on_trip': drivers_on_trip,
                'available': drivers_available,
                'avg_experience': avg_experience,
            },
            'finance_metrics': finance_aggregate,
            'active_trips_list': active_trips[:6],
            'recent_trips': recent_trips,
            'top_drivers': top_drivers,
            'trucks_overview': trucks_overview,
            # Vertical-ops dashboard extras
            'active_trips_count': active_trips.count(),
            'trucks_available': available_trucks,
            'trucks_in_use': in_use_trucks,
            'trucks_maintenance': maintenance_trucks,
            'driver_count': total_drivers,
            'completed_today': completed_today,
            'revenue_month': revenue_month,
            'income_month': income_month,
            'revenue_change_pct': revenue_change_pct,
            'income_change_pct': income_change_pct,
            'unpaid_invoices_count': unpaid_invoices_count,
            'overdue_unpaid_count': overdue_unpaid_count,
            'services_due_count': services_due_count,
            'licenses_expiring_count': licenses_expiring_count,
            'start_of_month': m_start,
        })

        # Pending invoices (activate section on dashboard)
        try:
            pending_invoices = Invoice.objects.filter(is_paid=False).select_related('trip', 'trip__truck', 'trip__driver').order_by('due_date', 'id')[:8]
        except Exception:
            pending_invoices = Invoice.objects.none()
        context['pending_invoices'] = pending_invoices

    elif user_role == 'DRIVER':
        driver = Driver.objects.select_related('staff_profile__user').filter(
            staff_profile__user=request.user
        ).first()

        if driver:
            driver_trips = Trip.objects.filter(driver=driver).select_related('truck').order_by(
                '-start_time', '-id'
            )
            completed_trips = driver_trips.filter(status=Trip.STATUS_COMPLETED).count()
            active_trips = driver_trips.filter(status=Trip.STATUS_IN_PROGRESS)
            has_active_trip = active_trips.exists()

            driver_financials = TripFinancial.objects.filter(trip__driver=driver).aggregate(
                total_revenue=Coalesce(Sum('total_revenue'), Decimal('0')),
                total_expense=Coalesce(Sum('total_expense'), Decimal('0')),
                net_income=Coalesce(Sum('income_before_tax'), Decimal('0')),
                payable=Coalesce(Sum('payable_receivable_amount'), Decimal('0')),
            )

            total_distance = driver_trips.aggregate(
                total_distance=Coalesce(Sum('distance_traveled'), Decimal('0'))
            )['total_distance']

            assigned_truck = Truck.objects.filter(driver=driver).select_related('driver').first()

            context.update({
                'driver_context_ready': True,
                'driver_profile': driver,
                'driver_metrics': {
                    'completed': completed_trips,
                    'active': active_trips.count(),
                    'total': driver_trips.count(),
                    'distance': total_distance,
                },
                'driver_financials': driver_financials,
                'assigned_truck': assigned_truck,
                'next_trip': next_trip,
                'driver_has_active_trip': has_active_trip,
            })
        else:
            context.update({
                'driver_context_ready': False,
                'driver_metrics': {
                    'completed': 0,
                    'active': 0,
                    'total': 0,
                    'distance': Decimal('0'),
                },
                'driver_financials': {
                    'total_revenue': Decimal('0'),
                    'total_expense': Decimal('0'),
                    'net_income': Decimal('0'),
                    'payable': Decimal('0'),
                },
                'driver_has_active_trip': False,
            })

    return render(request, "index.html", context)


    
# --------------------------------
# 4. Staff Views
# --------------------------------
@login_required
def staff_list(request):
    # Only ADMIN can access staff pages
    allowed, user_role = check_user_role(request, ['ADMIN'])
    if not allowed:
        return redirect('home')

    staff_members = Staff.objects.all()
    return render(request, "transportation/staff_list.html", {
        "staff_members": staff_members,
        "user_role": user_role
    })


@login_required
def staff_detail(request, pk):
    # Only ADMIN
    allowed, user_role = check_user_role(request, ['ADMIN'])
    if not allowed:
        return redirect('home')

    staff_member = get_object_or_404(Staff, pk=pk)
    return render(request, "transportation/staff_detail.html", {
        "staff_member": staff_member,
        "user_role": user_role
    })


@login_required
def staff_create(request):
    # Only ADMIN
    allowed, user_role = check_user_role(request, ['ADMIN'])
    if not allowed:
        return redirect('home')

    if request.method == "POST":
        form = StaffForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = StaffForm()
    return render(request, "transportation/staff_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def staff_update(request, pk):
    # Only ADMIN
    allowed, user_role = check_user_role(request, ['ADMIN'])
    if not allowed:
        return redirect('home')

    staff_member = get_object_or_404(Staff, pk=pk)
    if request.method == "POST":
        form = StaffForm(request.POST, request.FILES, instance=staff_member)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = StaffForm(instance=staff_member)
    return render(request, "transportation/staff_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def staff_delete(request, pk):
    # Only ADMIN
    allowed, user_role = check_user_role(request, ['ADMIN'])
    if not allowed:
        return redirect('home')

    staff_member = get_object_or_404(Staff, pk=pk)
    if request.method == "POST":
        try:
            with transaction.atomic():
                user_to_delete = staff_member.user
                if user_to_delete:
                    user_to_delete.delete()
            messages.success(
                request,
                f"Staff and user '{staff_member}' deleted successfully."
            )
        except Exception as e:
            messages.error(request, f"Error deleting user: {str(e)}")
        return _redirect_back(request)
    return render(request, "transportation/staff_confirm_delete.html", {
        "staff_member": staff_member,
        "user_role": user_role
    })


# --------------------------------
# 5. Driver Views
# --------------------------------
@login_required
def driver_list(request):
    # ADMIN or MANAGER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    drivers = Driver.objects.select_related("staff_profile__user").all()
    return render(request, "transportation/driver_list.html", {
        "drivers": drivers,
        "user_role": user_role
    })


@login_required
def driver_detail(request, pk):
    # ADMIN or MANAGER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    driver = get_object_or_404(Driver, pk=pk)
    return render(request, "transportation/driver_detail.html", {
        "driver": driver,
        "user_role": user_role
    })


@login_required
def driver_create(request):
    # ADMIN or MANAGER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    if request.method == "POST":
        form = DriverForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = DriverForm()
    return render(request, "transportation/driver_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def driver_update(request, pk):
    # ADMIN or MANAGER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    driver = get_object_or_404(Driver, pk=pk)
    if request.method == "POST":
        form = DriverForm(request.POST, request.FILES, instance=driver)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = DriverForm(instance=driver)
    return render(request, "transportation/driver_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def driver_delete(request, pk):
    # ADMIN or MANAGER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    driver = get_object_or_404(Driver, pk=pk)
    if request.method == "POST":
        driver.delete()
        return _redirect_back(request)
    return render(request, "transportation/driver_confirm_delete.html", {
        "driver": driver,
        "user_role": user_role
    })

# --------------------------------
# 6. Truck Views
# --------------------------------
@login_required
def truck_list(request):
    # Update GPS records before processing truck data
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    from django.db.models import Count
    trucks = Truck.objects.all().annotate(total_trips=Count('trip'))
    return render(request, 'transportation/truck_list.html', {
        'trucks': trucks,
        'user_role': user_role
    })

@login_required
def truck_detail(request, pk):
    # Update GPS records before processing truck detail
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    truck = get_object_or_404(Truck, pk=pk)
    return render(request, "transportation/truck_detail.html", {
        "truck": truck,
        "user_role": user_role
    })
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils.timezone import now as tz_now

@login_required
@require_GET
def truck_status(request, pk=None):
    """Return latest GPS status.
    - Admin/Manager: can request all trucks (no pk) or a specific pk.
    - Driver: must request a pk and it must be their assigned truck; otherwise 403.
    """
    # Role gate
    allowed, role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return JsonResponse({}, status=403)

    # If driver, force ownership check and require pk
    if role == 'DRIVER':
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        if not pk:
            return JsonResponse([], safe=False, status=403)
        truck = get_object_or_404(Truck, pk=pk)
        if not driver or getattr(truck, 'driver_id', None) != getattr(driver, 'id', None):
            return JsonResponse({}, status=403)
        latest_record = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if latest_record:
            return JsonResponse({
                "id": truck.id,
                "plate_number": truck.plate_number,
                "location": latest_record.loc,
                "latitude": float(latest_record.lat),
                "longitude": float(latest_record.lng),
                "engine": latest_record.engine,
                "speed": float(latest_record.speed),
                "fuel1": float(latest_record.fuel_1) if latest_record.fuel_1 is not None else None,
                "fuel2": float(latest_record.fuel_2) if latest_record.fuel_2 is not None else None,
                "angle": latest_record.angle,
                "status": str(latest_record.status),
                "timestamp": latest_record.dt_tracker.isoformat() if latest_record.dt_tracker else None,
                "driver_name": (truck.driver.staff_profile.user.username
                                 if getattr(truck, 'driver', None) and getattr(truck.driver, 'staff_profile', None)
                                 else ""),
            })
        return JsonResponse({"error": "No GPS data available for this truck."})

    # Admin/Manager flow
    if pk:
        truck = get_object_or_404(Truck, pk=pk)
        latest_record = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if latest_record:
            return JsonResponse({
                "id": truck.id,
                "plate_number": truck.plate_number,
                "location": latest_record.loc,
                "latitude": float(latest_record.lat),
                "longitude": float(latest_record.lng),
                "engine": latest_record.engine,
                "speed": float(latest_record.speed),
                "fuel1": float(latest_record.fuel_1) if latest_record.fuel_1 is not None else None,
                "fuel2": float(latest_record.fuel_2) if latest_record.fuel_2 is not None else None,
                "angle": latest_record.angle,
                "status": str(latest_record.status),
                "timestamp": latest_record.dt_tracker.isoformat() if latest_record.dt_tracker else None,
                "driver_name": (truck.driver.staff_profile.user.username
                                 if getattr(truck, 'driver', None) and getattr(truck.driver, 'staff_profile', None)
                                 else ""),
            })
        return JsonResponse({"error": "No GPS data available for this truck."})

    # No pk: list for all trucks (admin/manager only)
    trucks = Truck.objects.all()
    data = []
    for truck in trucks:
        latest_record = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if latest_record:
            data.append({
                "id": truck.id,
                "plate_number": truck.plate_number,
                "location": latest_record.loc,
                "latitude": float(latest_record.lat),
                "longitude": float(latest_record.lng),
                "engine": latest_record.engine,
                "speed": float(latest_record.speed),
                "fuel1": float(latest_record.fuel_1) if latest_record.fuel_1 is not None else None,
                "fuel2": float(latest_record.fuel_2) if latest_record.fuel_2 is not None else None,
                "driver_name": (truck.driver.staff_profile.user.username
                                 if getattr(truck, 'driver', None) and getattr(truck.driver, 'staff_profile', None)
                                 else ""),
                "timestamp": latest_record.dt_tracker.isoformat() if latest_record.dt_tracker else None,
            })
    return JsonResponse(data, safe=False)


from django.db import DatabaseError

@login_required
@require_GET
def geofence_list(request, truck_id):
    # Admin/Manager only
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return JsonResponse([], safe=False, status=403)
    try:
        qs = Geofence.objects.filter(truck_id=truck_id, active=True).order_by('-created_at')
        def to_geo(f):
            g = { 'id': f.id, 'type': f.type, 'name': f.name or '' }
            g.update(f.geometry or {})
            return g
        return JsonResponse([to_geo(f) for f in qs], safe=False)
    except DatabaseError:
        # Table may not exist yet; return empty list instead of 500
        return JsonResponse([], safe=False)


@login_required
@require_POST
def geofence_create(request, truck_id):
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return JsonResponse({}, status=403)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')
    gtype = (payload.get('type') or '').lower()
    name = payload.get('name') or ''
    geometry = payload.copy()
    for k in ('type','name'): geometry.pop(k, None)
    if gtype not in ('circle','rect','polygon'):
        return HttpResponseBadRequest('Invalid type')
    f = Geofence.objects.create(
        truck_id=truck_id,
        name=name,
        type=gtype,
        geometry=geometry,
        created_by=request.user
    )
    return JsonResponse({ 'id': f.id })


@login_required
@require_POST
def geofence_clear(request, truck_id):
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return JsonResponse({}, status=403)
    Geofence.objects.filter(truck_id=truck_id, active=True).update(active=False, updated_at=timezone.now())
    return JsonResponse({ 'ok': True })


def _admin_emails():
    """Return a non-empty list of recipient emails for admin notifications."""
    User = get_user_model()
    emails = list(User.objects.filter(is_superuser=True, is_active=True).exclude(email__isnull=True).values_list('email', flat=True))
    if not emails:
        # Fallback to configured sender if no superuser emails are set
        fallback = getattr(settings, 'EMAIL_HOST_USER', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        if fallback:
            emails = [fallback]
    return emails


@login_required
@require_POST
def geofence_event(request):
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return JsonResponse({}, status=403)
    """Accepts geofence lifecycle/transition events from the UI and emails admins.

    Expected JSON body:
      {
        "event_type": "created" | "disabled" | "entered" | "exited",
        "fence": { "type": "circle|rect|polygon", "name": str, ... },
        "truck_id": int,  # preferred
        "plate_number": str,  # fallback if id not provided
        "position": [lat, lng]  # optional, for enter/exit
      }
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest('Invalid JSON')

    event_type = (payload.get('event_type') or '').lower()
    fence = payload.get('fence') or {}
    plate = payload.get('plate_number')
    truck_id = payload.get('truck_id')
    pos = payload.get('position')

    if event_type not in { 'created', 'disabled', 'entered', 'exited' }:
        return HttpResponseBadRequest('Invalid event_type')

    truck = None
    if truck_id:
        truck = Truck.objects.filter(pk=truck_id).first()
    if not truck and plate:
        truck = Truck.objects.filter(plate_number=plate).first()

    truck_label = truck.plate_number if truck else (plate or 'Unknown')
    driver_name = ''
    if truck and getattr(truck, 'driver', None) and getattr(truck.driver, 'staff_profile', None):
        driver_name = truck.driver.staff_profile.user.username

    # Build email (plain + HTML with inline SVG for fence)
    fence_name = fence.get('name') or fence.get('type') or 'Geofence'
    subject = f"[Geofence] {event_type.title()} — {truck_label} ({driver_name or 'No driver'})"
    lines = [
        f"Event: {event_type}",
        f"By: {request.user.get_username()} ({request.user.email or 'no-email'})",
        f"Truck: {truck_label}",
        f"Driver: {driver_name or 'N/A'}",
        f"Fence: {fence_name} (type={fence.get('type','?')})",
        f"Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    if pos and isinstance(pos, (list, tuple)) and len(pos) == 2:
        lines.append(f"Position: ({pos[0]}, {pos[1]})")
    # Add fence geometry details briefly
    if fence.get('type') == 'circle' and 'center' in fence:
        lines.append(f"Circle center: {tuple(fence.get('center'))}, radius: {fence.get('radius')} m")
    elif fence.get('type') == 'rect' and fence.get('sw') and fence.get('ne'):
        lines.append(f"Rectangle SW: {tuple(fence.get('sw'))}, NE: {tuple(fence.get('ne'))}")
    elif fence.get('type') == 'polygon' and fence.get('points'):
        lines.append(f"Polygon vertices: {len(fence.get('points'))}")

    message = "\n".join(lines)

    def fence_svg(f):
        try:
            brand = "#017335"  # Thermo Fam green
            bg = "#0a0f14"     # dark card bg
            stroke = "#00acc1"  # cyan accent
            w, h, pad = 360, 200, 10
            # compute bounds
            if f.get('type') == 'circle':
                lat, lng = f.get('center', [0,0])
                r = float(f.get('radius', 500))
                dlat = r / 111320.0
                dlng = r / (111320.0 * max(0.1, __import__('math').cos(lat*3.14159/180)))
                y1, y2 = lat - dlat, lat + dlat
                x1, x2 = lng - dlng, lng + dlng
                points = [(lat, lng)]
            elif f.get('type') == 'rect':
                (y1, x1) = f.get('sw', [0,0])
                (y2, x2) = f.get('ne', [0,0])
                points = [(y1,x1),(y1,x2),(y2,x2),(y2,x1)]
            else:
                pts = f.get('points') or []
                ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
                y1, y2 = min(ys), max(ys); x1, x2 = min(xs), max(xs)
                points = pts
            # avoid zero-size bbox
            if y1 == y2: y2 = y1 + 0.001
            if x1 == x2: x2 = x1 + 0.001
            def mapx(x):
                return pad + (x - x1) / (x2 - x1) * (w - 2*pad)
            def mapy(y):
                return pad + (1 - (y - y1) / (y2 - y1)) * (h - 2*pad)
            svg = [f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg">']
            svg.append(f'<rect x="0" y="0" width="{w}" height="{h}" rx="12" fill="{bg}"/>')
            svg.append(f'<text x="12" y="22" fill="{brand}" font-family="Arial" font-size="14" font-weight="700">{fence_name}</text>')
            if f.get('type') == 'circle':
                cx = mapx(points[0][1]); cy = mapy(points[0][0])
                # radius in pixels ~ use dx from bbox
                rx = (mapx(x2) - mapx(x1)) / 2
                svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rx:.1f}" fill="rgba(0,172,193,0.08)" stroke="{stroke}" stroke-width="2"/>')
            elif f.get('type') == 'rect':
                x = mapx(x1); y = mapy(y2); ww = mapx(x2) - mapx(x1); hh = mapy(y1) - mapy(y2)
                svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{ww:.1f}" height="{hh:.1f}" fill="rgba(0,172,193,0.06)" stroke="{stroke}" stroke-width="2"/>')
            else:
                pts_attr = " ".join([f"{mapx(px):.1f},{mapy(py):.1f}" for (py,px) in points])
                svg.append(f'<polygon points="{pts_attr}" fill="rgba(0,172,193,0.06)" stroke="{stroke}" stroke-width="2"/>')
            svg.append('</svg>')
            return "".join(svg)
        except Exception:
            return ''

    svg_markup = fence_svg(fence)
    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;background:#0e141a;padding:16px;color:#e6eef5">
      <div style="max-width:640px;margin:auto;background:#0e141a;border:1px solid #123;box-shadow:0 6px 18px rgba(0,0,0,.25);border-radius:12px;overflow:hidden">
        <div style="background:linear-gradient(135deg,#0a8c52,#017335);padding:12px 16px;color:#fff;font-weight:800">Geofence {event_type.title()}</div>
        <div style="padding:16px">
          <div style="margin-bottom:12px;line-height:1.5">
            <div><b>Truck:</b> {truck_label}</div>
            <div><b>Driver:</b> {driver_name or 'N/A'}</div>
            <div><b>Fence:</b> {fence_name} (type={fence.get('type','?')})</div>
            {('<div><b>Position:</b> (%s, %s)</div>' % (pos[0], pos[1])) if pos else ''}
            <div><b>Time:</b> {timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z')}</div>
          </div>
          {svg_markup}
        </div>
      </div>
    </div>
    """

    recipients = _admin_emails()
    if recipients:
        try:
            send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True, html_message=html)
        except Exception:
            # Don't break the UI on email errors
            pass

    return JsonResponse({ 'ok': True })


# --------------------------------
# Live data APIs used by dashboard and maps
# --------------------------------

@login_required
@require_GET
def dashboard_data(request):
    """Return lightweight KPI numbers for the dashboard auto-refresh.

    Keys expected by `static/js/dashboard.js` and `templates/index.html`:
      - active_trips_count, trucks_available, trucks_in_use, trucks_maintenance,
        driver_count, completed_today, revenue_month, income_month,
        revenue_change_pct, income_change_pct,
        unpaid_invoices_count, overdue_unpaid_count,
        services_due_count, licenses_expiring_count
    """
    # Role gate: any authenticated role can read their dashboard KPIs
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return JsonResponse({}, status=403)

    today = timezone.localdate()
    # Month window (aware)
    now_dt = timezone.localtime(timezone.now())
    tz = timezone.get_current_timezone()
    m_start = timezone.make_aware(datetime(now_dt.year, now_dt.month, 1, 0, 0, 0), tz)
    last_day = monthrange(now_dt.year, now_dt.month)[1]
    m_end = timezone.make_aware(datetime(now_dt.year, now_dt.month, last_day, 23, 59, 59), tz)

    # Previous month window
    if now_dt.month == 1:
        pm_year, pm_month = now_dt.year - 1, 12
    else:
        pm_year, pm_month = now_dt.year, now_dt.month - 1
    pm_last_day = monthrange(pm_year, pm_month)[1]
    pm_start = timezone.make_aware(datetime(pm_year, pm_month, 1, 0, 0, 0), tz)
    pm_end = timezone.make_aware(datetime(pm_year, pm_month, pm_last_day, 23, 59, 59), tz)

    # Counts (scoped for drivers)
    role = get_user_role(request)
    driver = None
    if role == 'DRIVER':
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        # Default zeros if no driver profile
        active_trips_qs = Trip.objects.none()
        assigned_truck = None
        if driver:
            active_trips_qs = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS, driver=driver)
            assigned_truck = Truck.objects.filter(driver=driver).first()
        active_trips_count = active_trips_qs.count()
        # Map single-truck state into the same shape
        trucks_available = 1 if assigned_truck and assigned_truck.status == 'AVAILABLE' else 0
        trucks_in_use = 1 if assigned_truck and assigned_truck.status == 'IN_USE' else 0
        trucks_maintenance = 1 if assigned_truck and assigned_truck.status == 'MAINTENANCE' else 0
        driver_count = 1 if driver else 0
        completed_today = Trip.objects.filter(status=Trip.STATUS_COMPLETED, end_time__date=today, driver=driver).count()
    else:
        active_trips_count = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS).count()
        trucks_available = Truck.objects.filter(status='AVAILABLE').count()
        trucks_in_use = Truck.objects.filter(status='IN_USE').count()
        trucks_maintenance = Truck.objects.filter(status='MAINTENANCE').count()
        driver_count = Driver.objects.count()
        completed_today = Trip.objects.filter(status=Trip.STATUS_COMPLETED, end_time__date=today).count()

    # Financials (current vs previous month)
    fin_filter = {}
    if role == 'DRIVER' and driver:
        fin_filter['trip__driver'] = driver
    curr_fin = TripFinancial.objects.filter(
        trip__end_time__gte=m_start, trip__end_time__lte=m_end, **fin_filter
    ).aggregate(revenue=Sum('total_revenue'), expense=Sum('total_expense'), income=Sum('income_before_tax'))
    prev_fin = TripFinancial.objects.filter(
        trip__end_time__gte=pm_start, trip__end_time__lte=pm_end, **fin_filter
    ).aggregate(revenue=Sum('total_revenue'), income=Sum('income_before_tax'))

    revenue_month = float(curr_fin.get('revenue') or 0)
    income_month = float(curr_fin.get('income') or 0)
    prev_revenue = float(prev_fin.get('revenue') or 0)
    prev_income = float(prev_fin.get('income') or 0)

    def pct_change(curr, prev):
        if prev and prev != 0:
            return round(((curr - prev) / prev) * 100.0, 1)
        return 0.0

    revenue_change_pct = pct_change(revenue_month, prev_revenue)
    income_change_pct = pct_change(income_month, prev_income)

    # Alerts
    unpaid_invoices_count = Invoice.objects.filter(is_paid=False).count()
    overdue_unpaid_count = Invoice.objects.filter(is_paid=False, due_date__lt=today).count()

    # Service reminders (next 30 days)
    in_30 = today + timedelta(days=30)
    services_due_count = ServiceRecord.objects.filter(next_service_date__gte=today, next_service_date__lte=in_30).count()

    # License expirations (either country) in next 30 days
    licenses_expiring_count = Driver.objects.filter(
        Q(djibouti_license_expiration__gte=today, djibouti_license_expiration__lte=in_30)
        | Q(ethiopian_license_expiration__gte=today, ethiopian_license_expiration__lte=in_30)
    ).count()

    return JsonResponse({
        'active_trips_count': active_trips_count,
        'trucks_available': trucks_available,
        'trucks_in_use': trucks_in_use,
        'trucks_maintenance': trucks_maintenance,
        'driver_count': driver_count,
        'completed_today': completed_today,
        'revenue_month': revenue_month,
        'income_month': income_month,
        'revenue_change_pct': revenue_change_pct,
        'income_change_pct': income_change_pct,
        'unpaid_invoices_count': unpaid_invoices_count,
        'overdue_unpaid_count': overdue_unpaid_count,
        'services_due_count': services_due_count,
        'licenses_expiring_count': licenses_expiring_count,
    })


@login_required
@require_GET
def live_trips_status(request):
    """Return latest GPS snapshot for active trips.

    Optional query param: `trip_id` to only return a single trip entry.
    Response shape: {"items": [ {trip_id, truck_id, truck_plate, driver, lat, lng, speed, engine, status, loc, fuel1, fuel2, updated, age_seconds}, ... ]}
    """
    # Any authenticated role can access their own dashboard; for drivers, we may scope results
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return JsonResponse({'items': []}, status=403)

    try:
        trip_id = int(request.GET.get('trip_id')) if request.GET.get('trip_id') else None
    except (TypeError, ValueError):
        trip_id = None

    qs = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS).select_related('truck', 'driver__staff_profile__user')
    if trip_id:
        qs = qs.filter(pk=trip_id)
    elif user_role == 'DRIVER':
        # Show only this driver's active trips if driver
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        if driver:
            qs = qs.filter(driver=driver)
        else:
            qs = Trip.objects.none()

    items = []
    now_ts = tz_now()
    for trip in qs:
        truck = trip.truck
        gps = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if gps:
            updated = gps.dt_tracker
            try:
                age = max(0, int((now_ts - updated).total_seconds()))
            except Exception:
                age = None
            item = {
                'trip_id': trip.pk,
                'truck_id': truck.pk,
                'truck_plate': truck.plate_number,
                'driver': (trip.driver.staff_profile.user.get_full_name() or trip.driver.staff_profile.user.username) if trip.driver else None,
                'lat': float(gps.lat) if gps.lat is not None else None,
                'lng': float(gps.lng) if gps.lng is not None else None,
                'speed': float(gps.speed) if gps.speed is not None else None,
                'engine': gps.engine,
                'status': gps.status,
                'loc': gps.loc,
                'fuel1': float(gps.fuel_1) if gps.fuel_1 is not None else None,
                'fuel2': float(gps.fuel_2) if gps.fuel_2 is not None else None,
                'updated': updated.isoformat() if updated else None,
                'age_seconds': age,
            }
        else:
            item = {
                'trip_id': trip.pk,
                'truck_id': truck.pk,
                'truck_plate': truck.plate_number,
                'driver': (trip.driver.staff_profile.user.get_full_name() or trip.driver.staff_profile.user.username) if trip.driver else None,
                'lat': None,
                'lng': None,
                'speed': None,
                'engine': None,
                'status': None,
                'loc': None,
                'fuel1': None,
                'fuel2': None,
                'updated': None,
                'age_seconds': None,
            }
        items.append(item)

    return JsonResponse({'items': items})


@login_required
@require_GET
def trip_route(request, trip_id):
    """Return the saved route for a trip and active geofences for its truck.

    Response: {"route": [...], "fences": [{...}, ...]}
    Ensures route is time-ordered and de-duplicated to avoid visual artifacts.
    """
    # Role-gate and ownership: drivers can only access their own trip route
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return JsonResponse({}, status=403)
    trip = get_object_or_404(Trip.objects.select_related('truck'), pk=trip_id)
    if user_role == 'DRIVER':
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        if not driver or trip.driver_id != getattr(driver, 'id', None):
            return JsonResponse({}, status=403)

    raw_route = list(trip.route or [])

    # Normalize and sort points by timestamp, keeping original order as a tiebreaker
    cleaned = []
    for idx, p in enumerate(raw_route):
        try:
            lat = float(p.get('lat'))
            lng = float(p.get('lng'))
        except Exception:
            continue
        if not (lat or lng):
            continue
        cleaned.append({
            'lat': lat,
            'lng': lng,
            'loc': p.get('loc') or '',
            'timestamp': p.get('timestamp'),
            '_i': idx,
        })

    def sort_key(p):
        t = p.get('timestamp')
        if t:
            try:
                from datetime import datetime as _dt
                return (0, _dt.fromisoformat(str(t).replace('Z', '+00:00')), p['_i'])
            except Exception:
                pass
        return (1, p['_i'], p['_i'])

    cleaned.sort(key=sort_key)

    # Drop consecutive duplicates within ~1m to avoid circles/jitter
    deduped = []
    last_lat = last_lng = None
    for p in cleaned:
        if last_lat is not None:
            if abs(p['lat'] - last_lat) < 1e-5 and abs(p['lng'] - last_lng) < 1e-5:
                continue
        deduped.append({k: v for k, v in p.items() if k != '_i'})
        last_lat, last_lng = p['lat'], p['lng']

    fences_qs = Geofence.objects.filter(truck=trip.truck, active=True).order_by('id')

    def fence_obj(f):
        data = {'id': f.id, 'type': f.type, 'name': f.name or ''}
        if f.geometry:
            try:
                data.update(f.geometry)
            except Exception:
                pass
        return data

    return JsonResponse({'route': deduped, 'fences': [fence_obj(f) for f in fences_qs]})


# --------------------------------
# Minimal hub routes (redirects for now)
# --------------------------------

@login_required
def operations_hub(request):
    """Temporary hub that points to trip list (ops)."""
    allowed, _ = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')
    # Drivers go to their minimal home; others to trip list
    if get_user_role(request) == 'DRIVER':
        return redirect('driver_home')
    return redirect('trip_list')


# --------------------------------
# Driver Home (map/GPS-free)
# --------------------------------
@login_required
def driver_home(request):
    allowed, user_role = check_user_role(request, ['DRIVER'])
    if not allowed:
        return redirect('home')

    staff = getattr(request.user, 'staff', None)
    driver = getattr(staff, 'driver_profile', None) if staff else None
    assigned_truck = Truck.objects.filter(driver=driver).first() if driver else None

    active_trip = None
    financial = None
    invoice = None
    if driver:
        active_trip = Trip.objects.filter(driver=driver, status=Trip.STATUS_IN_PROGRESS).select_related('truck').first()
        if active_trip:
            financial, _ = TripFinancial.objects.get_or_create(trip=active_trip)
            invoice = Invoice.objects.filter(trip=active_trip).first()
            # Live metrics
            try:
                latest = GPSRecord.objects.filter(truck__plate_number=active_trip.truck.plate_number).order_by('-dt_tracker').only('odometer').first()
                if latest is not None and active_trip.initial_kilometer is not None:
                    active_distance_km = max(0.0, float(latest.odometer) - float(active_trip.initial_kilometer))
                else:
                    cd = active_trip.calculated_distance() if callable(getattr(active_trip, 'calculated_distance', None)) else active_trip.calculated_distance
                    active_distance_km = float(cd or 0)
            except Exception:
                cd = active_trip.calculated_distance() if callable(getattr(active_trip, 'calculated_distance', None)) else active_trip.calculated_distance
                active_distance_km = float(cd or 0)
            active_duration_days = None
            if active_trip.start_time:
                active_duration_days = round((timezone.now() - active_trip.start_time).total_seconds() / 86400.0, 2)
        else:
            active_distance_km = None
            active_duration_days = None

    ctx = {
        'user_role': 'DRIVER',
        'driver': driver,
        'assigned_truck': assigned_truck,
        'active_trip': active_trip,
        'financial': financial,
        'invoice': invoice,
        'has_active_trip': bool(active_trip),
        'active_distance_km': active_distance_km if active_trip else None,
        'active_duration_days': active_duration_days if active_trip else None,
    }
    return render(request, 'transportation/driver_home.html', ctx)


# Small helper for consistent post-submit navigation
def _redirect_back(request, fallback_name=None):
    """Redirect to ?next, posted next, or safe referer; else to role-based hub/home.

    fallback_name: named URL to use if no next/referer is present. If None, picks
    'home_hub' for ADMIN/MANAGER, 'driver_home' for DRIVER, else 'home'.
    """
    nxt = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    if fallback_name:
        try:
            return redirect(fallback_name)
        except Exception:
            pass
    role = get_user_role(request)
    if role in ['ADMIN', 'MANAGER']:
        return redirect('home_hub')
    if role == 'DRIVER':
        return redirect('driver_home')
    return redirect('home')

# --------------------------------
# Simple Landing Hub and Focused Pages
# --------------------------------

@login_required
def home_hub(request):
    """A very simple post-login hub with four clear choices.

    Shows counts for Active Trips and Completed Trips to match the requested UX.
    Admin/Manager only; drivers keep using driver_home.
    """
    # Drivers continue to their dedicated home
    if get_user_role(request) == 'DRIVER':
        return redirect('driver_home')

    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    active_count = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS).count()
    completed_count = Trip.objects.filter(status=Trip.STATUS_COMPLETED).count()

    return render(request, 'transportation/simple_hub.html', {
        'user_role': user_role,
        'active_trips_count': active_count,
        'completed_trips_count': completed_count,
    })


@login_required
def fleet_map_page(request):
    """Dedicated interactive map page for fleet live locations.

    Reuses existing Leaflet + fleet_map.js scripts and live endpoints.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    # Optionally refresh GPS data for the map
    update_gps_records_sync()

    return render(request, 'transportation/fleet_map.html', {
        'user_role': user_role,
    })


@login_required
def active_trips_overview(request):
    """All active trips in one place without duplicate info.

    Render concise cards/rows with key details and a link to each trip.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    trips = (Trip.objects
             .filter(status=Trip.STATUS_IN_PROGRESS)
             .select_related('truck', 'driver__staff_profile__user')
             .order_by('-start_time', '-id'))

    # Build cards with live distance and duration in days
    cards = []
    now = timezone.now()
    for t in trips:
        # live distance
        dist = None
        try:
            latest = GPSRecord.objects.filter(truck__plate_number=t.truck.plate_number).order_by('-dt_tracker').only('odometer').first()
            if latest is not None and t.initial_kilometer is not None:
                dist = max(0.0, float(latest.odometer) - float(t.initial_kilometer))
        except Exception:
            dist = None
        if dist is None:
            cd = t.calculated_distance() if callable(getattr(t, 'calculated_distance', None)) else t.calculated_distance
            dist = float(cd or 0)
        # duration in days from start to now
        dur_days = None
        if t.start_time:
            dur_days = round((now - t.start_time).total_seconds() / 86400.0, 2)
        cards.append({'trip': t, 'distance_km': dist, 'duration_days': dur_days})

    return render(request, 'transportation/active_trips.html', {
        'user_role': user_role,
        'trips': trips,
        'trip_cards': cards,
        'active_trips_count': trips.count(),
    })


@login_required
def completed_trips_matrix(request):
    """Completed trips grouped by Truck in a comparison matrix.

    Uses the same filter form as trip_completed_filter; shows one table per truck,
    with trips as columns and detail rows for side-by-side comparison.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    from .forms import CompletedTripsFilterForm
    form = CompletedTripsFilterForm(request.POST or None)

    trips_qs = Trip.objects.filter(status=Trip.STATUS_COMPLETED).select_related('truck', 'driver__staff_profile__user')
    # Apply timeframe filters similar to existing page
    if request.method == 'POST' and form.is_valid():
        tf = form.cleaned_data.get('timeframe')
        if tf == 'custom':
            start_date = form.cleaned_data['start_date']
            end_date = form.cleaned_data['end_date']
            if start_date and end_date:
                trips_qs = trips_qs.filter(end_time__date__gte=start_date, end_time__date__lte=end_date)
        else:
            now = timezone.now()
            from dateutil.relativedelta import relativedelta
            if tf == '1_month':
                date_from = now - relativedelta(months=1)
            elif tf == '3_months':
                date_from = now - relativedelta(months=3)
            elif tf == '1_year':
                date_from = now - relativedelta(years=1)
            elif tf == '2_years':
                date_from = now - relativedelta(years=2)
            else:
                date_from = None
            if date_from:
                trips_qs = trips_qs.filter(end_time__gte=date_from)

    trips_qs = trips_qs.order_by('-end_time', '-id')

    # Determine how many latest trips per truck to include
    per_truck = 6
    if request.method in ("POST", "GET") and form.is_valid():
        per_truck = form.cleaned_data.get('per_truck') or 6
        try:
            per_truck = int(per_truck)
        except Exception:
            per_truck = 6

    # Group trips by truck
    grouped = defaultdict(list)
    for t in trips_qs:
        # Accumulate trips per truck, keep only the latest N
        lst = grouped[t.truck]
        if len(lst) < per_truck:
            lst.append(t)

    # Prefetch financials per trip id
    fin_map = {f.trip_id: f for f in TripFinancial.objects.filter(trip__in=trips_qs)}

    # Build per-truck comparison data
    truck_blocks = []
    for truck, trips in grouped.items():
        # columns are trips; rows are fields
        cols = []
        for t in trips:
            fin = fin_map.get(t.id)
            # Resolve friendly route names with fallback if stored name is unknown
            start_name = t.start_location
            end_name = t.end_location
            try:
                if not start_name or start_name.strip().lower() == 'unknown':
                    if isinstance(t.route, list) and t.route:
                        p0 = t.route[0]
                        start_name = reverse_geocode_location(p0.get('lat'), p0.get('lng')) or start_name
                if not end_name or end_name.strip().lower() == 'unknown':
                    if isinstance(t.route, list) and t.route:
                        p1 = t.route[-1]
                        end_name = reverse_geocode_location(p1.get('lat'), p1.get('lng')) or end_name
            except Exception:
                pass
            cols.append({
                'id': t.id,
                'truck_trip_number': t.truck_trip_number,
                'route': f"{(start_name or '—')} → {(end_name or '—')}",
                'start': t.start_time,
                'end': t.end_time,
                'distance': t.calculated_distance() or t.distance_traveled,
                'cargo': t.cargo_type,
                'load': t.cargo_load,
                'tariff': t.tariff_rate,
                'revenue': getattr(fin, 'total_revenue', None),
                'expense': getattr(fin, 'total_expense', None),
                'income': getattr(fin, 'income_before_tax', None),
                'payable_receivable': getattr(fin, 'payable_receivable_amount', None),
                'dispatch': getattr(fin, 'operational_expense', None),
                'margin': getattr(fin, 'net_profit_margin', None),
                'driver': (t.driver.staff_profile.user.get_full_name() or t.driver.staff_profile.user.username) if t.driver else None,
            })
        truck_blocks.append({ 'truck': truck, 'columns': cols })

    return render(request, 'transportation/trip_completed_matrix.html', {
        'user_role': user_role,
        'form': form,
        'truck_blocks': truck_blocks,
    })


@login_required
def driver_performance(request):
    """Driver performance indicator: trips completed, time per trip, drive vs idle time, expenses, income.

    Timeframe filter is optional; defaults to last 1 month.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    # Reuse CompletedTripsFilterForm for timeframe selection
    from .forms import CompletedTripsFilterForm
    form = CompletedTripsFilterForm(request.POST or None)

    # Determine date range
    date_from = None
    date_to = None
    now = timezone.now()
    from dateutil.relativedelta import relativedelta
    if request.method == 'POST' and form.is_valid():
        tf = form.cleaned_data['timeframe']
        if tf == 'custom':
            date_from = form.cleaned_data['start_date']
            date_to = form.cleaned_data['end_date']
        elif tf == '1_month':
            date_from = now - relativedelta(months=1)
        elif tf == '3_months':
            date_from = now - relativedelta(months=3)
        elif tf == '1_year':
            date_from = now - relativedelta(years=1)
        elif tf == '2_years':
            date_from = now - relativedelta(years=2)
    else:
        date_from = now - relativedelta(months=1)

    trips_qs = Trip.objects.filter(status=Trip.STATUS_COMPLETED).select_related('truck', 'driver__staff_profile__user')
    if date_from:
        trips_qs = trips_qs.filter(end_time__gte=date_from)
    if date_to:
        # inclusive end of day for a date object
        try:
            dt_end = datetime.combine(date_to, datetime.max.time())
            if timezone.is_naive(dt_end):
                dt_end = timezone.make_aware(dt_end)
        except Exception:
            dt_end = None
        if dt_end:
            trips_qs = trips_qs.filter(end_time__lte=dt_end)

    # Organize trips per driver
    by_driver = defaultdict(list)
    for t in trips_qs:
        if t.driver_id:
            by_driver[t.driver].append(t)

    # Helper to accumulate driving vs idle time from GPS snapshots
    def drive_idle_for_trip(trip: Trip):
        if not (trip.start_time and trip.end_time):
            return 0, 0
        qs = GPSRecord.objects.filter(
            truck=trip.truck,
            dt_tracker__gte=trip.start_time,
            dt_tracker__lte=trip.end_time,
        ).order_by('dt_tracker').only('dt_tracker', 'speed')
        if not qs.exists():
            # Fallback: all time as driving duration equals trip duration (no GPS granularity)
            delta = (trip.end_time - trip.start_time).total_seconds()
            return delta, 0
        drive = 0.0
        idle = 0.0
        prev = None
        prev_speed = None
        for rec in qs:
            if prev is None:
                prev = rec.dt_tracker
                prev_speed = float(rec.speed or 0)
                continue
            dt = max(0.0, (rec.dt_tracker - prev).total_seconds())
            # Consider driving when speed > 0
            if (prev_speed or 0) > 0:
                drive += dt
            else:
                idle += dt
            prev = rec.dt_tracker
            prev_speed = float(rec.speed or 0)
        # Account for tail gap up to trip end
        if prev and trip.end_time and trip.end_time > prev:
            tail = (trip.end_time - prev).total_seconds()
            if (prev_speed or 0) > 0:
                drive += tail
            else:
                idle += tail
        return drive, idle

    # Prefetch financials
    fin_map = {f.trip_id: f for f in TripFinancial.objects.filter(trip__in=trips_qs)}

    driver_rows = []
    for driver, trips in by_driver.items():
        completed = len(trips)
        total_drive = 0.0
        total_idle = 0.0
        total_duration = 0.0
        total_revenue = Decimal('0')
        total_expense = Decimal('0')
        total_income = Decimal('0')
        for t in trips:
            if t.start_time and t.end_time:
                total_duration += max(0.0, (t.end_time - t.start_time).total_seconds())
            d, i = drive_idle_for_trip(t)
            total_drive += d
            total_idle += i
            fin = fin_map.get(t.id)
            if fin:
                total_revenue += fin.total_revenue or Decimal('0')
                total_expense += fin.total_expense or Decimal('0')
                total_income += fin.income_before_tax or Decimal('0')
        # convert seconds to hours for readability
        def _hours(v):
            try:
                return round(float(v) / 3600.0, 2)
            except Exception:
                return 0.0
        def _days(v):
            try:
                return round(float(v) / 86400.0, 2)
            except Exception:
                return 0.0
        driver_rows.append({
            'driver': driver,
            'completed': completed,
            'drive_hours': _hours(total_drive),
            'idle_hours': _hours(total_idle),
            'duration_days': _days(total_duration),
            'revenue': total_revenue,
            'expense': total_expense,
            'income': total_income,
        })

    # Sort by completed trips desc
    driver_rows.sort(key=lambda r: (-r['completed'], r['driver'].staff_profile.user.username))

    return render(request, 'transportation/driver_performance.html', {
        'user_role': user_role,
        'form': form,
        'rows': driver_rows,
    })


@login_required
def admin_actions_hub(request):
    """Simple admin/manager hub listing key administrative actions.

    - ADMIN: can create users (staff) and everything else
    - MANAGER: can register trucks, register drivers, create cargo
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    return render(request, 'transportation/admin_hub.html', {
        'user_role': user_role,
    })


@login_required
def people_hub(request):
    """Temporary hub that points to drivers list (people)."""
    allowed, _ = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    return redirect('driver-list')

@login_required
def truck_create(request):
    # Update GPS records before processing truck creation
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    if request.method == "POST":
        form = TruckForm(request.POST)
        if form.is_valid():
            truck = form.save(commit=False)
            truck.save()
            form.save_m2m()
            return _redirect_back(request)
    else:
        form = TruckForm()
    return render(request, "transportation/truck_form.html", {
        "form": form,
        "user_role": user_role
    })

@login_required
def truck_update(request, pk):
    # Update GPS records before processing truck update
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    truck = get_object_or_404(Truck, pk=pk)
    if request.method == "POST":
        form = TruckForm(request.POST, instance=truck)
        if form.is_valid():
            truck = form.save(commit=False)
            truck.save()
            form.save_m2m()
            return _redirect_back(request)
    else:
        form = TruckForm(instance=truck)
    return render(request, "transportation/truck_form.html", {
        "form": form,
        "user_role": user_role
    })

@login_required
def truck_delete(request, pk):
    # Update GPS records before processing truck deletion
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    truck = get_object_or_404(Truck, pk=pk)
    if request.method == "POST":
        truck.delete()
        return _redirect_back(request)
    return render(request, "transportation/truck_confirm_delete.html", {
        "truck": truck,
        "user_role": user_role
    })



# --------------------------------
# 7. Cargo Views
# --------------------------------
@login_required
def cargo_list(request):
    # ADMIN, MANAGER, or DRIVER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    cargo_list_obj = Cargo.objects.all()
    return render(request, "transportation/cargo_list.html", {
        "cargo_list": cargo_list_obj,
        "user_role": user_role
    })


@login_required
def cargo_detail(request, pk):
    # ADMIN, MANAGER, or DRIVER
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    cargo = get_object_or_404(Cargo, pk=pk)
    return render(request, "transportation/cargo_detail.html", {
        "cargo": cargo,
        "user_role": user_role
    })


@login_required
def cargo_create(request):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    if request.method == "POST":
        form = CargoForm(request.POST)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = CargoForm()
    return render(request, "transportation/cargo_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def cargo_update(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    cargo = get_object_or_404(Cargo, pk=pk)
    if request.method == "POST":
        form = CargoForm(request.POST, instance=cargo)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = CargoForm(instance=cargo)
    return render(request, "transportation/cargo_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def cargo_delete(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    cargo = get_object_or_404(Cargo, pk=pk)
    if request.method == "POST":
        cargo.delete()
        return _redirect_back(request)
    return render(request, "transportation/cargo_confirm_delete.html", {
        "cargo": cargo,
        "user_role": user_role
    })


# --------------------------------
# 8. Major Accident Views
# --------------------------------
@login_required
def accident_list(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    accidents = MajorAccident.objects.filter(truck=truck)
    return render(request, 'transportation/accident_list.html', {
        'accidents': accidents,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def accident_detail(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    accident = get_object_or_404(MajorAccident, pk=pk)
    return render(request, 'transportation/accident_detail.html', {
        "accident": accident,
        "user_role": user_role
    })


@login_required
def accident_create(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    if request.method == 'POST':
        form = MajorAccidentForm(request.POST, request.FILES)
        if form.is_valid():
            accident = form.save(commit=False)
            accident.truck = truck
            accident.save()
            return redirect('home')
    else:
        form = MajorAccidentForm()
    return render(request, 'transportation/accident_form.html', {
        'form': form,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def accident_update(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    accident = get_object_or_404(MajorAccident, pk=pk)
    truck = accident.truck
    if request.method == 'POST':
        form = MajorAccidentForm(request.POST, request.FILES, instance=accident)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = MajorAccidentForm(instance=accident)
    return render(request, 'transportation/accident_form.html', {
        "form": form,
        "truck": truck,
        "user_role": user_role
    })


@login_required
def accident_delete(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    accident = get_object_or_404(MajorAccident, pk=pk)
    if request.method == 'POST':
        accident.delete()
        return redirect('home')
    return render(request, 'transportation/accident_confirm_delete.html', {
        "accident": accident,
        "user_role": user_role
    })


# --------------------------------
# 9. Service Record Views
# --------------------------------
@login_required
def service_list(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    services = ServiceRecord.objects.filter(truck=truck)
    return render(request, 'transportation/service_list.html', {
        'services': services,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def service_detail(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    service = get_object_or_404(ServiceRecord, pk=pk)
    return render(request, 'transportation/service_detail.html', {
        "service": service,
        "user_role": user_role
    })


@login_required
def service_create(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    if request.method == 'POST':
        form = ServiceRecordForm(request.POST, request.FILES)
        if form.is_valid():
            service = form.save(commit=False)
            service.truck = truck
            service.save()
            return _redirect_back(request)
    else:
        form = ServiceRecordForm()
    return render(request, 'transportation/service_form.html', {
        'form': form,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def service_update(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    service = get_object_or_404(ServiceRecord, pk=pk)
    truck = service.truck
    if request.method == 'POST':
        form = ServiceRecordForm(request.POST, request.FILES, instance=service)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = ServiceRecordForm(instance=service)
    return render(request, 'transportation/service_form.html', {
        "form": form,
        "truck": truck,
        "user_role": user_role
    })


@login_required
def service_delete(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    service = get_object_or_404(ServiceRecord, pk=pk)
    truck = service.truck
    if request.method == 'POST':
        service.delete()
        return _redirect_back(request)
    return render(request, 'transportation/service_confirm_delete.html', {
        "service": service,
        "truck": truck,
        "user_role": user_role
    })



# --------------------------------
# 10. Replaced Item Views
# --------------------------------
@login_required
def replaced_item_list(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    items = ReplacedItem.objects.filter(truck=truck)
    return render(request, 'transportation/replaced_item_list.html', {
        'items': items,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def replaced_item_detail(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    item = get_object_or_404(ReplacedItem, pk=pk)
    return render(request, 'transportation/replaced_item_detail.html', {
        "item": item,
        "user_role": user_role
    })


@login_required
def replaced_item_create(request, truck_id):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    truck = get_object_or_404(Truck, pk=truck_id)
    if request.method == 'POST':
        form = ReplacedItemForm(request.POST, request.FILES)
        if form.is_valid():
            replaced = form.save(commit=False)
            replaced.truck = truck
            replaced.save()
            return _redirect_back(request)
    else:
        form = ReplacedItemForm()
    return render(request, 'transportation/replaced_item_form.html', {
        'form': form,
        'truck': truck,
        'user_role': user_role
    })


@login_required
def replaced_item_update(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    item = get_object_or_404(ReplacedItem, pk=pk)
    truck = item.truck
    if request.method == 'POST':
        form = ReplacedItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            return _redirect_back(request)
    else:
        form = ReplacedItemForm(instance=item)
    return render(request, 'transportation/replaced_item_form.html', {
        "form": form,
        "truck": truck,
        "user_role": user_role
    })


@login_required
def replaced_item_delete(request, pk):
    # ADMIN or MANAGER only
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    item = get_object_or_404(ReplacedItem, pk=pk)
    truck = item.truck
    if request.method == 'POST':
        item.delete()
        return _redirect_back(request)
    return render(request, 'transportation/replaced_item_confirm_delete.html', {
        "item": item,
        "truck": truck,
        "user_role": user_role
    })

# --------------------------------
# 11. Trip Views (Mix of Class-based and Function-based)
# --------------------------------
# views.py


class TripListView(LoginRequiredMixin, ListView):
    model = Trip
    template_name = "transportation/trip_list.html"
    context_object_name = "trips"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        context['has_uncompleted_trip'] = Trip.objects.filter(
            driver=self.request.user.driver_profile, status=Trip.STATUS_IN_PROGRESS
        ).exists()
        # Retrieve pending invoices (i.e. invoices where is_paid is False)
        context['pending_invoices'] = Invoice.objects.filter(is_paid=False)
        return context



@login_required
def trip_list(request):
    # Pull latest GPS data (optional, if desired)
    update_gps_records_sync()

    # Check if user is allowed
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    # For Admin/Manager: Show all in-progress trips
    driver = None
    trips = Trip.objects.filter(status=Trip.STATUS_IN_PROGRESS).select_related("truck", "driver").order_by('-id')
    has_uncompleted_trip = False

    if user_role == 'DRIVER':
        # Get the staff/driver profile safely
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        if driver:
            # Show only this driver's in-progress trips
            trips = trips.filter(driver=driver)
            # Check if the driver has any in-progress trip
            has_uncompleted_trip = trips.exists()
        else:
            # If no valid Driver object, show none
            trips = Trip.objects.none()

    # Retrieve pending invoices (i.e. invoices where is_paid is False)
    pending_invoices = Invoice.objects.filter(is_paid=False)

    # Bird's eye KPIs and context
    now = timezone.now()
    today = now.date()
    # Aware month window
    tz = timezone.get_current_timezone()
    m_start = timezone.make_aware(datetime(now.year, now.month, 1, 0, 0, 0), tz)
    last_day = monthrange(now.year, now.month)[1]
    m_end = timezone.make_aware(datetime(now.year, now.month, last_day, 23, 59, 59), tz)

    active_trips_count = trips.count()
    completed_today_qs = Trip.objects.filter(status=Trip.STATUS_COMPLETED, end_time__date=today)
    if user_role == 'DRIVER' and driver:
        completed_today_qs = completed_today_qs.filter(driver=driver)
    completed_today = completed_today_qs.count()

    monthly_fin_qs = TripFinancial.objects.filter(trip__end_time__gte=m_start, trip__end_time__lte=m_end)
    if user_role == 'DRIVER' and driver:
        monthly_fin_qs = monthly_fin_qs.filter(trip__driver=driver)
    monthly_fin = monthly_fin_qs.aggregate(
        revenue=Sum('total_revenue'), expense=Sum('total_expense'), income=Sum('income_before_tax')
    )
    revenue_month = monthly_fin.get('revenue') or Decimal('0')
    expense_month = monthly_fin.get('expense') or Decimal('0')
    income_month = monthly_fin.get('income') or Decimal('0')

    # Recently completed trips for quick scan
    recent_completed_qs = Trip.objects.select_related('truck', 'driver').filter(status=Trip.STATUS_COMPLETED).order_by('-end_time')
    if user_role == 'DRIVER':
        if driver:
            recent_completed_qs = recent_completed_qs.filter(driver=driver)
        else:
            recent_completed_qs = Trip.objects.none()
    recent_completed = recent_completed_qs[:8]

    is_driver = user_role == 'DRIVER'
    show_fleet_map = user_role in ('ADMIN', 'MANAGER')

    return render(request, "transportation/trip_list.html", {
        "trips": trips,
        "user_role": user_role,
        "has_uncompleted_trip": has_uncompleted_trip,
        "pending_invoices": pending_invoices,
        # KPIs
        "active_trips_count": active_trips_count,
        "completed_today": completed_today,
        "revenue_month": revenue_month,
        "expense_month": expense_month,
        "income_month": income_month,
        "recent_completed": recent_completed,
        "is_driver": is_driver,
        "show_fleet_map": show_fleet_map,
    })


# views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from .forms import CompletedTripsFilterForm
from .models import Trip

@login_required
def trip_completed_filter(request):
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    trips = []  # Default: empty until form is submitted
    if request.method == 'POST':
        form = CompletedTripsFilterForm(request.POST)
        if form.is_valid():
            timeframe = form.cleaned_data['timeframe']
            if timeframe == 'custom':
                # Use custom date range provided by the user
                start_date = form.cleaned_data['start_date']
                end_date = form.cleaned_data['end_date']
                trips = Trip.objects.filter(
                    status=Trip.STATUS_COMPLETED,
                    start_time__range=(start_date, end_date)
                ).select_related("truck", "driver").order_by('-end_time')
            else:
                now = timezone.now()
                if timeframe == '1_month':
                    date_from = now - relativedelta(months=1)
                elif timeframe == '3_months':
                    date_from = now - relativedelta(months=3)
                elif timeframe == '1_year':
                    date_from = now - relativedelta(years=1)
                elif timeframe == '2_years':
                    date_from = now - relativedelta(years=2)
                else:
                    date_from = None

                if date_from:
                    trips = Trip.objects.filter(
                        status=Trip.STATUS_COMPLETED,
                        end_time__gte=date_from
                    ).select_related("truck", "driver").order_by('-end_time')
                else:
                    trips = Trip.objects.filter(
                        status=Trip.STATUS_COMPLETED
                    ).select_related("truck", "driver").order_by('-end_time')
    else:
        form = CompletedTripsFilterForm()

    return render(request, 'transportation/trip_completed_filter.html', {
        'form': form,
        'trips': trips,
        'user_role': user_role,
    })




class TripDetailView(LoginRequiredMixin, DetailView):
    """
    Shows detailed information about a single trip, including financial summary, expenses, and invoices.
    """
    model = Trip
    template_name = "transportation/trip_detail.html"
    context_object_name = "trip"

    def dispatch(self, request, *args, **kwargs):
        update_gps_records_sync()
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        role = get_user_role(self.request)
        if role == 'DRIVER':
            # Limit drivers to their own trips only
            driver = getattr(getattr(self.request.user, 'staff', None), 'driver_profile', None)
            if driver:
                return qs.filter(driver=driver)
            return qs.none()
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        trip = self.get_object()
        financial, created = TripFinancial.objects.get_or_create(trip=trip)
        # Keep financials up to date so KPIs reflect latest inputs while trip is active
        try:
            financial.update_financials()
        except Exception:
            # Do not break the view if aggregation fails; fall back to stored numbers
            pass
        context['financial'] = financial
        context['expenses'] = financial.expenses.all()
        # Extract the related invoice from the Invoice table using the trip foreign key
        context['invoice'] = Invoice.objects.filter(trip_id=trip.id).first()
        # Summary KPIs
        # Distance: for active trips, compute live using latest odometer
        distance = None
        try:
            if trip.status == Trip.STATUS_IN_PROGRESS and trip.truck:
                latest_gps = GPSRecord.objects.filter(
                    truck__plate_number=trip.truck.plate_number
                ).order_by('-dt_tracker').only('odometer').first()
                if latest_gps is not None and trip.initial_kilometer is not None:
                    distance = max(0.0, float(latest_gps.odometer) - float(trip.initial_kilometer))
        except Exception:
            distance = None
        if distance is None:
            # Completed trips or fallback
            cd = trip.calculated_distance() if callable(getattr(trip, 'calculated_distance', None)) else trip.calculated_distance
            distance = float(cd or 0)

        # Duration in days. For in-progress, use now; for completed, use start->end.
        duration_days = None
        if trip.start_time:
            end_ts = trip.end_time or timezone.now()
            delta = end_ts - trip.start_time
            duration_days = round(delta.total_seconds() / 86400.0, 2)
        context.update({
            'kpi_distance': float(distance or 0),
            'kpi_duration_days': duration_days,
            'kpi_revenue': float(financial.total_revenue or 0),
            'kpi_expense': float(financial.total_expense or 0),
            'kpi_income': float(financial.income_before_tax or 0),
            'kpi_payable': float(financial.payable_receivable_amount or 0),
        })
        # Expense breakdown for a mini chart
        by_cat = {}
        for e in financial.expenses.all():
            by_cat[e.get_category_display()] = by_cat.get(e.get_category_display(), Decimal('0')) + (e.amount or Decimal('0'))
        context['expense_breakdown_json'] = json.dumps([
            {'category': k, 'amount': float(v)} for k, v in by_cat.items()
        ])
        return context


        
import base64
import urllib.parse
from datetime import datetime
from django.shortcuts import redirect, get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.contrib.staticfiles import finders
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from weasyprint import HTML, CSS

# Import your helper functions and models:
from .models import Trip, TripFinancial, Invoice
# Assume update_gps_records, check_user_role, get_user_role are imported

def get_font_data_uri(font_path):
    absolute_path = finders.find(font_path)
    if not absolute_path:
        raise Exception(f"Font file {font_path} not found.")
    with open(absolute_path, "rb") as f:
        data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")
    return f"data:font/truetype;charset=utf-8;base64,{base64_data}"
from django.utils import timezone



class TripPdfView(LoginRequiredMixin, DetailView):
    model = Trip
    template_name = "transportation/trip_pdf.html"  # Dedicated PDF template
    context_object_name = "trip"

    def dispatch(self, request, *args, **kwargs):
        update_gps_records_sync()
        # Restrict PDF generation to ADMIN/MANAGER only
        allowed, _ = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # No driver access
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        trip = self.get_object()
        financial, _ = TripFinancial.objects.get_or_create(trip=trip)
        context['financial'] = financial
        context['expenses'] = financial.expenses.all()
        invoice = Invoice.objects.filter(trip_id=trip.id).first()
        context['invoice'] = invoice

        # Build absolute URL for the invoice image
        if invoice and invoice.attached_image:
            context['absolute_invoice_image_url'] = self.request.build_absolute_uri(invoice.attached_image.url)
        else:
            context['absolute_invoice_image_url'] = None

        # Build absolute URLs for operational expense detail images
        if hasattr(financial, 'expense_details'):
            details_list = list(financial.expense_details.all())
            for detail in details_list:
                if detail.image:
                    detail.absolute_image_url = self.request.build_absolute_uri(detail.image.url)
                else:
                    detail.absolute_image_url = None
            context['operational_expense_details'] = details_list
        else:
            context['operational_expense_details'] = []

        # Add user and current time to the context
        now = timezone.now()
        context.update({
            'user': self.request.user,
            'current_time': now,
            'font_data_uri': get_font_data_uri("fonts/NotoSansEthiopic-Regular.ttf"),
            'map_data_url': self.request.GET.get('map_data_url', ''),
            'company_name': getattr(settings, 'COMPANY_NAME', 'Thermofam Trading PLC'),
            'company_tagline': getattr(settings, 'COMPANY_TAGLINE', 'Exporter of Superior Quality'),
        })
        return context

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        context = self.get_context_data()
        html_string = render_to_string(self.template_name, context, request=request)
        css_path = finders.find('css/pdf_styles.css')
        if not css_path:
            raise Exception("CSS file for PDF styling not found.")
        pdf_css = CSS(filename=css_path)
        pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(stylesheets=[pdf_css])

        # If available, embed the invoice image as a PDF attachment
        invoice = context.get('invoice')
        if PdfReader and PdfWriter and invoice and getattr(invoice, 'attached_image', None):
            try:
                reader = PdfReader(BytesIO(pdf_file))
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                filename = getattr(invoice.attached_image, 'name', 'invoice_image')
                with invoice.attached_image.open('rb') as fh:
                    writer.add_attachment(filename.split('/')[-1], fh.read())
                buf = BytesIO()
                writer.write(buf)
                pdf_file = buf.getvalue()
                buf.close()
            except Exception:
                # If embedding fails, continue with original PDF bytes
                pass

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="trip_{self.object.pk}.pdf"'
        return response



@login_required
def trip_detail(request, pk):
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    # Drivers can only view their own trips
    if user_role == 'DRIVER':
        driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
        trip = get_object_or_404(Trip.objects.filter(driver=driver), pk=pk)
    else:
        trip = get_object_or_404(Trip, pk=pk)
    return render(request, "transportation/trip_detail.html", {
        "trip": trip,
        "user_role": user_role
    })


# --------------------------------------------------------------------
# TRIP CREATE (for DRIVERS)
# --------------------------------------------------------------------

from decimal import Decimal
import pytz
from django.contrib import messages
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth.mixins import LoginRequiredMixin

class TripCreateView(LoginRequiredMixin, CreateView):
    model = Trip
    form_class = DriverTripCreateForm
    template_name = "transportation/trip_form.html"
    success_url = reverse_lazy('home')

    def dispatch(self, request, *args, **kwargs):
        update_gps_records_sync()
        allowed, user_role = check_user_role(request, ['DRIVER'])
        if not allowed:
            messages.error(request, "Only drivers can create trips this way.")
            return redirect('home')
        staff = getattr(request.user, 'staff', None)
        driver = getattr(staff, 'driver_profile', None) if staff else None
        if driver and Trip.objects.filter(driver=driver, status=Trip.STATUS_IN_PROGRESS).exists():
            messages.warning(request, "You already have an active trip. Complete it before starting a new one.")
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        trip = form.save(commit=False)

        # 1) Get current driver object from request.user
        staff = self.request.user.staff
        driver = getattr(staff, 'driver_profile', None)
        if not driver:
            messages.error(self.request, "No driver profile found for the current user.")
            return redirect(self.success_url)

        # 2) Identify the truck assigned to this driver
        truck = Truck.objects.filter(driver=driver).first()
        if not truck:
            messages.error(self.request, "No truck is currently assigned to you.")
            return redirect(self.success_url)

        # 3) Grab the latest GPS record for that truck (if available)
        latest_gps = GPSRecord.objects.filter(
            truck__plate_number=truck.plate_number
        ).order_by('-dt_tracker').first()

        ethiopia_tz = pytz.timezone('Africa/Addis_Ababa')
        current_time = timezone.now().astimezone(ethiopia_tz)

        # 4) Automatically fill the necessary trip fields
        trip.driver = driver
        trip.truck = truck
        trip.start_time = current_time
        if latest_gps:
            trip.initial_kilometer = int(latest_gps.odometer)
            # Use tracker-provided location, else reverse geocode
            if latest_gps.loc:
                start_loc_name = latest_gps.loc
            else:
                start_loc_name = reverse_geocode_location(latest_gps.lat, latest_gps.lng) or "Unknown"
            trip.start_location = start_loc_name
            trip.route = [{
                "lat": float(latest_gps.lat),
                "lng": float(latest_gps.lng),
                "loc": start_loc_name or "",
                # Use tracker time to preserve chronological ordering with subsequent points
                "timestamp": (latest_gps.dt_tracker.isoformat() if latest_gps.dt_tracker else current_time.isoformat()),
            }]
        else:
            trip.initial_kilometer = truck.mileage_km if truck.mileage_km is not None else 0
            trip.start_location = "Unknown"
            trip.route = []

        trip.status = Trip.STATUS_IN_PROGRESS
        trip.is_in_duty = True

        # 5) Save the Trip
        trip.save()

        # 6) Mark truck as in use
        truck.is_in_duty = True
        truck.status = 'IN_USE'
        truck.save(update_fields=['is_in_duty', 'status'])

        # --- NEW LOGIC TO ROLL OVER PAYABLE/RECEIVABLE ---

        # 7) Create or fetch the TripFinancial for this new trip.
        financial, _ = TripFinancial.objects.get_or_create(trip=trip)

        # 8) Identify the driver's last completed trip (if any).
        last_trip = Trip.objects.filter(
            driver=driver,
            status=Trip.STATUS_COMPLETED
        ).order_by('-end_time').first()

        if last_trip and hasattr(last_trip, 'financial'):
            leftover = last_trip.financial.payable_receivable_amount or Decimal('0.00')
            # 9) Only create a carry-over entry if leftover is not zero
            if leftover != 0:
                # Carry over leftover into the new trip’s financial record by creating a new OperationalExpenseDetail.
                OperationalExpenseDetail.objects.create(
                    financial=financial,
                    amount=leftover,
                    note=f"Carry-over from Trip #{last_trip.truck_trip_number or last_trip.pk}",
                )
                # Update financial aggregates after adding the carry-over detail
                financial.update_financials()

        messages.success(self.request, "Trip created successfully. Drive safe!")
        return redirect(self.success_url)


# --------------------------------------------------------------------
# TRIP UPDATE
# --------------------------------------------------------------------


class TripUpdateView(LoginRequiredMixin, UpdateView):
    """
    Allow ADMIN/MANAGER/DRIVER to edit cargo fields (cargo_type, cargo_load, tariff_rate).
    Drivers may only edit their own in-progress trips.
    """
    model = Trip
    form_class = DriverTripCreateForm
    template_name = "transportation/trip_form.html"
    # We'll override get_success_url().

    def dispatch(self, request, *args, **kwargs):
        update_gps_records_sync()
        # Permit admins, managers, and drivers
        allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = super().get_queryset()
        # Restrict editing to in-progress trips for all roles
        qs = qs.filter(status=Trip.STATUS_IN_PROGRESS)
        # Drivers can only edit their own trips
        raw_role = get_user_role(self.request) or ''
        role = raw_role.strip().upper()
        if role == 'DRIVER':
            staff = Staff.objects.filter(user=self.request.user).select_related('driver_profile').first()
            driver = getattr(staff, 'driver_profile', None)
            if not driver:
                return Trip.objects.none()
            return qs.filter(driver=driver)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def get_form(self, form_class=None):
        """
        If you want to hide 'truck' and other fields from the update form for drivers,
        you can pop them here. For ADMIN or MANAGER, you might want them.
        """
        form = super().get_form(form_class)
        if self.object and self.object.pk:
            # We remove 'truck' so the driver can’t change trucks
            form.fields.pop('truck', None)
        return form

    def form_valid(self, form):
        """
        After saving, recalc financials if needed, then redirect to trip detail.
        """
        response = super().form_valid(form)
        trip = self.object
        try:
            financial = trip.financial
            financial.update_financials()
        except TripFinancial.DoesNotExist:
            pass
        messages.success(self.request, "Trip details updated.")
        return response

    def form_invalid(self, form):
        """On invalid, return to dashboard (no nav buttons)."""
        messages.error(self.request, "Trip update failed due to invalid data.")
        return redirect('home')

    def get_success_url(self):
        """Send users back to dashboard on success."""
        return reverse_lazy('home')




@login_required
def trip_update(request, pk):
    """
    (Optional) Old function-based update. Could remain for ADMIN/MANAGER usage.
    """
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    trip = get_object_or_404(Trip, pk=pk)
    if request.method == "POST":
        form = TripForm(request.POST, instance=trip)
        if form.is_valid():
            form.save()
            return redirect('home')
    else:
        form = TripForm(instance=trip)

    return render(request, "transportation/trip_form.html", {
        "form": form,
        "user_role": user_role
    })


@login_required
def trip_delete(request, pk):
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    trip = get_object_or_404(Trip, pk=pk)
    if request.method == "POST":
        trip.delete()
        return redirect('home')
    return render(request, "transportation/trip_confirm_delete.html", {
        "trip": trip,
        "user_role": user_role
    })


# --------------------------------------------------------------------
# TRIP COMPLETION
# --------------------------------------------------------------------
@login_required
def trip_complete_confirmation(request, trip_id):
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    if user_role == 'DRIVER':
        driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
        trip = get_object_or_404(Trip.objects.filter(driver=driver), pk=trip_id)
    else:
        trip = get_object_or_404(Trip, pk=trip_id)
    if trip.status != Trip.STATUS_IN_PROGRESS:
        messages.error(request, "This trip cannot be completed as it is not in progress.")
        return redirect("trip_detail", trip.pk)

    return render(request, "transportation/trip_complete_confirmation.html", {
        "trip": trip,
        "user_role": user_role
    })


from django.core.mail import EmailMultiAlternatives
from email.mime.image import MIMEImage
from django.template.loader import render_to_string
from django.conf import settings
import base64
from weasyprint import HTML, CSS
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib.staticfiles import finders
from django.contrib.auth import get_user_model
from .models import Trip, GPSRecord, Staff

@login_required
def trip_complete(request, trip_id):
    update_gps_records_sync()
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    if user_role == 'DRIVER':
        driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
        trip = get_object_or_404(Trip.objects.filter(driver=driver), pk=trip_id)
    else:
        trip = get_object_or_404(Trip, pk=trip_id)

    if not hasattr(trip, 'invoice'):
        messages.error(request, "Cannot complete trip without an invoice. Please create an invoice first.")
        return redirect("trip_detail", trip.pk)

    if trip.status != Trip.STATUS_IN_PROGRESS:
        messages.error(request, "This trip cannot be completed as it is not in progress.")
        return redirect("trip_detail", trip.pk)

    latest_gps = GPSRecord.objects.filter(truck__plate_number=trip.truck.plate_number).order_by('-dt_tracker').first()
    if latest_gps:
        trip.final_kilometer = int(latest_gps.odometer)
        trip.end_time = timezone.now()
        end_loc_name = latest_gps.loc or reverse_geocode_location(latest_gps.lat, latest_gps.lng) or "Unknown"
        trip.end_location = end_loc_name
    else:
        trip.final_kilometer = trip.initial_kilometer
        trip.end_time = timezone.now()
        trip.end_location = "Unknown"

    trip.status = Trip.STATUS_COMPLETED
    trip.is_in_duty = False
    trip.save()

    # Ensure invoice has a due date; default to 10 days after completion if missing
    try:
        inv = getattr(trip, 'invoice', None)
        if inv and not getattr(inv, 'due_date', None) and trip.end_time:
            inv.due_date = (trip.end_time + timedelta(days=10)).date()
            inv.save(update_fields=['due_date'])
    except Exception:
        # Do not block trip completion due to invoice due date failure
        pass

    # Auto-start a new trip for the same driver and truck
    new_trip = None
    try:
        # Avoid duplicate active trip creation
        if trip.driver and trip.truck and not Trip.objects.filter(driver=trip.driver, status=Trip.STATUS_IN_PROGRESS).exists():
            start_gps = GPSRecord.objects.filter(truck__plate_number=trip.truck.plate_number).order_by('-dt_tracker').first()
            new_trip = Trip(
                truck=trip.truck,
                driver=trip.driver,
                start_time=timezone.now(),
                status=Trip.STATUS_IN_PROGRESS,
                is_in_duty=True,
            )
            if start_gps:
                try:
                    new_trip.initial_kilometer = int(start_gps.odometer)
                except Exception:
                    new_trip.initial_kilometer = trip.final_kilometer or trip.initial_kilometer
                start_loc = start_gps.loc or reverse_geocode_location(start_gps.lat, start_gps.lng) or "Unknown"
                new_trip.start_location = start_loc
                new_trip.route = [{
                    "lat": float(start_gps.lat),
                    "lng": float(start_gps.lng),
                    "loc": start_loc or "",
                    "timestamp": (start_gps.dt_tracker.isoformat() if start_gps.dt_tracker else timezone.now().isoformat()),
                }]
            else:
                new_trip.initial_kilometer = trip.final_kilometer or trip.initial_kilometer or 0
                new_trip.start_location = "Unknown"
                new_trip.route = []
            new_trip.save()

            # Ensure truck marked in use again
            try:
                trip.truck.status = 'IN_USE'
                trip.truck.is_in_duty = True
                trip.truck.save(update_fields=['status', 'is_in_duty'])
            except Exception:
                pass

            # Create financial record and carry over payable/receivable from completed trip
            try:
                new_financial, _ = TripFinancial.objects.get_or_create(trip=new_trip)
                if hasattr(trip, 'financial') and trip.financial:
                    leftover = trip.financial.payable_receivable_amount or Decimal('0.00')
                    if leftover != 0:
                        OperationalExpenseDetail.objects.create(
                            financial=new_financial,
                            amount=leftover,
                            note=f"Carry-over from Trip #{trip.truck_trip_number or trip.pk}",
                        )
                        new_financial.update_financials()
            except Exception:
                pass
    except Exception:
        new_trip = None

    # If auto-start didn’t happen, set truck as available; otherwise it’s already set to IN_USE
    if trip.truck and not new_trip:
        trip.truck.status = 'AVAILABLE'
        trip.truck.is_in_duty = False
        trip.truck.save(update_fields=['status', 'is_in_duty'])

    messages.success(request, "Trip has been successfully completed.")
    # Email notification is enforced at the model level on status transition
    return redirect('home')

    context = {
        'trip': trip,
        'financial': trip.financial if hasattr(trip, 'financial') else None,
        'expenses': trip.financial.expenses.all() if hasattr(trip, 'financial') else [],
        'invoice': getattr(trip, 'invoice', None),
        'user': request.user,
        'current_time': timezone.now(),
        'font_data_uri': get_font_data_uri("fonts/NotoSansEthiopic-Regular.ttf"),
        'map_data_url': '',
        'user_role': get_user_role(request),
        'company_name': getattr(settings, 'COMPANY_NAME', 'Thermofam Trading PLC'),
        'company_tagline': getattr(settings, 'COMPANY_TAGLINE', 'Exporter of Superior Quality'),
    }

    # Create absolute URL for the invoice image
    if context['invoice'] and context['invoice'].attached_image:
        context['absolute_invoice_image_url'] = request.build_absolute_uri(context['invoice'].attached_image.url)
    else:
        context['absolute_invoice_image_url'] = None

    # Create absolute URLs for driver expenses images
    for expense in context['expenses']:
        if hasattr(expense, 'image') and expense.image:
            expense.absolute_image_url = request.build_absolute_uri(expense.image.url)
        else:
            expense.absolute_image_url = None

    # Build a list for operational expense details with the absolute image URL
    if context.get('financial') and hasattr(context['financial'], 'expense_details'):
        details_list = list(context['financial'].expense_details.all())
        for detail in details_list:
            if detail.image:
                detail.absolute_image_url = request.build_absolute_uri(detail.image.url)
            else:
                detail.absolute_image_url = None
        context['operational_expense_details'] = details_list
    else:
        context['operational_expense_details'] = []

    # Render the PDF template
    html_string = render_to_string("transportation/trip_pdf_email.html", context, request=request)

    css_path = finders.find('css/pdf_styles.css')
    if not css_path:
        raise Exception("CSS file for PDF styling not found.")
    pdf_css = CSS(filename=css_path)
    pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf(stylesheets=[pdf_css])

    # If available, embed the invoice image as a PDF attachment (email PDF as well)
    invoice = context.get('invoice')
    if PdfReader and PdfWriter and invoice and getattr(invoice, 'attached_image', None):
        try:
            reader = PdfReader(BytesIO(pdf_file))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            filename = getattr(invoice.attached_image, 'name', 'invoice_image')
            with invoice.attached_image.open('rb') as fh:
                writer.add_attachment(filename.split('/')[-1], fh.read())
            buf = BytesIO()
            writer.write(buf)
            pdf_file = buf.getvalue()
            buf.close()
        except Exception:
            # Gracefully fall back if embedding fails
            pass

    # Determine email recipients
    User = get_user_model()
    superuser_emails = {user.email for user in User.objects.filter(is_superuser=True) if user.email}
    staff_emails = {staff.user.email for staff in Staff.objects.filter(role__in=['ADMIN', 'MANAGER']) if staff.user.email}
    recipients_emails = list(superuser_emails.union(staff_emails))

    logo_path = finders.find('images/Thermologo.jpg')

    inline_css = """
    <style>
      html, body { height: 100%; margin: 0; padding: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background-color: #f9f9f9; color: #333; line-height: 1.4; }
      .header { background-color: #017335; padding: 1rem 2rem; text-align: center; }
      .header h1 { color: #fff; font-size: 2rem; margin: 0; }
      .content { padding: 2rem; }
      .detail { margin-bottom: 1rem; }
      .detail strong { color: #017335; }
      .footer { background-color: #017335; color: #fff; text-align: center; padding: 1rem 0; margin-top: 2rem; }
    </style>
    """

    subject = f"Trip Completed: Trip #{trip.truck_trip_number or trip.pk}"
    html_body = f"""
    <html>
      <head>
        <meta charset="UTF-8">
        {inline_css}
      </head>
      <body>
        <div class="header">
          <img src="cid:logo" alt="Thermo Fam Trading PLC" style="max-width: 150px; border: 2px solid #fff; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.3); margin-bottom: 10px;">
          <h1>Thermofam Trading PLC</h1>
        </div>
        <div class="content">
          <p>Dear Admin/Manager,</p>
          <p>We are pleased to inform you that <strong>Trip #{trip.truck_trip_number or trip.pk}</strong> has been successfully completed.</p>
          <div class="detail">
            <p><strong>Truck:</strong> {trip.truck.plate_number}</p>
            <p><strong>Driver:</strong> {trip.driver.staff_profile.user.username if trip.driver else 'N/A'}</p>
            <p><strong>Route:</strong> {trip.start_location} → {trip.end_location}</p>
          </div>
    """
    if trip.financial:
        html_body += f"""
          <div class="detail">
            <p><strong>Total Revenue:</strong> {trip.financial.total_revenue} ETB</p>
            <p><strong>Total Expense:</strong> {trip.financial.total_expense} ETB</p>
            <p><strong>Profit Before Tax:</strong> {trip.financial.income_before_tax} ETB</p>
            <p><strong>Net Profit Margin:</strong> {trip.financial.net_profit_margin if trip.financial.net_profit_margin else 'N/A'}%</p>
            <p><strong>Payable/Receivable:</strong> {trip.financial.payable_receivable_amount} ETB</p>
          </div>
        """
    else:
        html_body += "<div class='detail'><p>Financial data is not available.</p></div>"
    html_body += f"""
          <p>For full details, please refer to the attached PDF, which includes route maps, expense breakdowns, and additional trip information.</p>
          <p>Regards,<br>Your Fleet Management System</p>
        </div>
        <div class="footer">
          <p>&copy; {timezone.now().year} Fleet Management System</p>
        </div>
      </body>
    </html>
    """

    email = EmailMultiAlternatives(
        subject=subject,
        body="Please view the HTML version of this email.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients_emails
    )
    email.attach_alternative(html_body, "text/html")
    email.attach(f"trip_{trip.pk}.pdf", pdf_file, "application/pdf")

    if logo_path:
        with open(logo_path, "rb") as lf:
            logo = MIMEImage(lf.read())
            logo.add_header('Content-ID', '<logo>')
            logo.add_header('Content-Disposition', 'inline', filename='Thermologo.jpg')
            email.attach(logo)

    email.send()

    return redirect('home')


# --------------------------------
# 12. Trip Financial Views
# --------------------------------


class OperationalExpenseDetailCreateView(LoginRequiredMixin, CreateView):
    model = OperationalExpenseDetail
    form_class = OperationalExpenseDetailForm
    template_name = "transportation/trip_financial_form.html"

    def dispatch(self, request, *args, **kwargs):
        allowed, _user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_financial(self):
        trip_id = self.kwargs.get('trip_id')
        self.trip = get_object_or_404(Trip, pk=trip_id)
        financial, created = TripFinancial.objects.get_or_create(trip=self.trip)
        return financial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Make sure we pass the trip and/or financial object to the template
        context["trip"] = getattr(self, "trip", None) or self.get_financial().trip
        context["financial"] = self.get_financial()
        context["user_role"] = get_user_role(self.request)
        return context

    def form_valid(self, form):
        financial = self.get_financial()
        self.object = form.save(commit=False)
        self.object.financial = financial
        self.object.save()
        financial.update_financials()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('home')

class OperationalExpenseDetailUpdateView(LoginRequiredMixin, UpdateView):
    model = OperationalExpenseDetail
    form_class = OperationalExpenseDetailForm  # Dedicated form for individual expense detail
    template_name = "transportation/trip_financial_form.html"  # Reuse shared template

    def dispatch(self, request, *args, **kwargs):
        allowed, _user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def form_valid(self, form):
        self.object = form.save()
        # Update the parent financial record to refresh aggregates.
        self.object.financial.update_financials()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('home')


# --------------------------------
# 13. Expense Views
# --------------------------------
class ExpenseCreateView(LoginRequiredMixin, CreateView):
    """
    Creates a new Expense associated with an existing TripFinancial record.
    """
    model = Expense
    form_class = ExpenseForm
    template_name = "transportation/expense_form.html"

    # Restrict to ADMIN, MANAGER, DRIVER (with ownership for drivers)
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        if user_role == 'DRIVER':
            fin_id = kwargs.get('financial_id')
            financial = get_object_or_404(TripFinancial, pk=fin_id)
            driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
            if not driver or financial.trip.driver_id != getattr(driver, 'id', None):
                messages.error(request, "You cannot add expenses for this trip.")
                return redirect('trip_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def form_valid(self, form):
        financial_id = self.kwargs.get("financial_id")
        trip_financial = get_object_or_404(TripFinancial, pk=financial_id)
        form.instance.trip_financial = trip_financial
        response = super().form_valid(form)
        trip_financial.update_financials()
        return response

    def get_success_url(self):
        return reverse_lazy('home')


class ExpenseUpdateView(LoginRequiredMixin, UpdateView):
    """
    Updates an existing Expense record.
    """
    model = Expense
    form_class = ExpenseForm
    template_name = "transportation/expense_form.html"

    # Restrict to ADMIN, MANAGER, DRIVER (with ownership for drivers)
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        if user_role == 'DRIVER':
            obj = self.get_object()
            trip = obj.trip_financial.trip
            driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
            if not driver or trip.driver_id != getattr(driver, 'id', None):
                messages.error(request, "You cannot modify expenses for this trip.")
                return redirect('trip_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.trip_financial.update_financials()
        return response

    def get_success_url(self):
        return reverse_lazy('home')


@login_required
def expense_delete(request, pk):
    # ADMIN, MANAGER, DRIVER (with ownership for drivers)
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
    if not allowed:
        return redirect('home')

    expense = get_object_or_404(Expense, pk=pk)
    if user_role == 'DRIVER':
        driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
        if not driver or expense.trip_financial.trip.driver_id != getattr(driver, 'id', None):
            messages.error(request, "You cannot modify expenses for this trip.")
            return redirect('trip_list')
    trip_financial = expense.trip_financial
    if request.method == "POST":
        expense.delete()
        trip_financial.update_financials()
        return redirect('home')
    return render(request, "transportation/expense_confirm_delete.html", {
        "expense": expense,
        "user_role": user_role
    })


# --------------------------------
# 14. Invoice Views
# --------------------------------


class InvoiceCreateView(LoginRequiredMixin, CreateView):
    """
    Creates a new Invoice for a Trip.
    """
    model = Invoice
    form_class = InvoiceForm
    template_name = "transportation/invoice_form.html"

    # Allow ADMIN/MANAGER; allow DRIVER only for own trip
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        if user_role == 'DRIVER':
            trip_id = kwargs.get('trip_id')
            trip = get_object_or_404(Trip, pk=trip_id)
            driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
            if not driver or trip.driver_id != getattr(driver, 'id', None):
                messages.error(request, "You can only attach an invoice for your own trip.")
                return redirect('trip_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def get_initial(self):
        initial = super().get_initial()
        # If the trip is already completed (rare), preset due_date to end_time + 10 days
        trip_id = self.kwargs.get("trip_id")
        try:
            trip = Trip.objects.filter(pk=trip_id).only('end_time').first()
            if trip and trip.end_time:
                initial['due_date'] = (trip.end_time + timedelta(days=10)).date()
        except Exception:
            pass
        return initial

    def form_valid(self, form):
        # Retrieve the trip object using the trip_id from the URL
        trip_id = self.kwargs.get("trip_id")
        trip = get_object_or_404(Trip, pk=trip_id)
        form.instance.trip = trip

        # Calculate the amount_due based on the trip's tariff_rate and cargo_load
        if trip.tariff_rate is not None and trip.cargo_load is not None:
            form.instance.amount_due = trip.tariff_rate * trip.cargo_load
        else:
            # Optionally, you can raise an error if the required fields are missing
            raise ValidationError("Trip tariff rate or cargo load is missing.")

        # If driver doesn't provide due_date, leave it for auto-set on completion
        # However, if trip already has an end_time (completed by admin flow), set default now
        if not form.instance.due_date and trip.end_time:
            form.instance.due_date = (trip.end_time + timedelta(days=10)).date()

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('home')


@login_required
def mark_invoice_paid(request, invoice_id):
    # Only ADMIN/MANAGER can mark invoices paid
    allowed, _role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    invoice.is_paid = True
    invoice.save()
    return redirect('home')


class InvoiceUpdateView(LoginRequiredMixin, UpdateView):
    """
    Updates an existing Invoice record.
    """
    model = Invoice
    form_class = InvoiceForm
    template_name = "transportation/invoice_form.html"

    # Allow ADMIN/MANAGER; allow DRIVER only for own trip's invoice
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        if user_role == 'DRIVER':
            invoice = self.get_object()
            trip = invoice.trip
            driver = getattr(getattr(request.user, 'staff', None), 'driver_profile', None)
            if not driver or trip.driver_id != getattr(driver, 'id', None):
                messages.error(request, "You can only edit the invoice for your own trip.")
                return redirect('trip_list')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        return context

    def get_success_url(self):
        return reverse_lazy('home')


# ------------------------------------------------------
# ADDITIONAL: Report Views
# ------------------------------------------------------
@login_required
def report_index(request):
    """All-in-one Reports hub (single page).
    Shows YTD KPIs, selected month summary, monthly trends, top trucks, and expense breakdown.
    Accepts optional GET params: year=YYYY and month=YYYY-MM.
    """
    allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
    if not allowed:
        return redirect('home')

    tz = timezone.get_current_timezone()
    now = timezone.now()

    # Parse target year and month
    year_param = request.GET.get('year')
    try:
        year = int(year_param) if year_param else now.year
    except Exception:
        year = now.year

    month_str = request.GET.get('month')  # format YYYY-MM
    if month_str:
        try:
            y, m = map(int, month_str.split('-'))
            month_year, month = y, m
        except Exception:
            month_year, month = now.year, now.month
    else:
        month_year, month = now.year, now.month
        month_str = f"{month_year}-{month:02d}"

    # Periods (timezone-aware)
    y_start_naive = datetime(year, 1, 1, 0, 0, 0)
    y_end_naive = datetime(year, 12, 31, 23, 59, 59)
    y_start = timezone.make_aware(y_start_naive, tz)
    y_end = timezone.make_aware(y_end_naive, tz)

    m_start_naive = datetime(month_year, month, 1, 0, 0, 0)
    last_day = monthrange(month_year, month)[1]
    m_end_naive = datetime(month_year, month, last_day, 23, 59, 59)
    m_start = timezone.make_aware(m_start_naive, tz)
    m_end = timezone.make_aware(m_end_naive, tz)

    # YTD financials
    ytd_qs = TripFinancial.objects.select_related('trip__truck').filter(
        trip__end_time__gte=y_start,
        trip__end_time__lte=y_end,
    )

    def d0(x):
        return x or Decimal('0.00')

    ytd_totals = ytd_qs.aggregate(
        revenue=Sum('total_revenue'),
        expense=Sum('total_expense'),
        income=Sum('income_before_tax'),
    )
    ytd_revenue = d0(ytd_totals.get('revenue'))
    ytd_expense = d0(ytd_totals.get('expense'))
    ytd_income = d0(ytd_totals.get('income'))
    ytd_margin = (ytd_income / ytd_revenue * Decimal('100')) if ytd_revenue else Decimal('0')

    # Monthly financials (selected month)
    m_qs = ytd_qs.filter(trip__end_time__gte=m_start, trip__end_time__lte=m_end)
    m_totals = m_qs.aggregate(
        revenue=Sum('total_revenue'),
        expense=Sum('total_expense'),
        income=Sum('income_before_tax'),
    )
    m_revenue = d0(m_totals.get('revenue'))
    m_expense = d0(m_totals.get('expense'))
    m_income = d0(m_totals.get('income'))
    m_margin = (m_income / m_revenue * Decimal('100')) if m_revenue else Decimal('0')

    # Monthly trend arrays for the year
    months_labels = []
    revenue_series, income_series, expense_series = [], [], []
    for i in range(1, 13):
        first = timezone.make_aware(datetime(year, i, 1, 0, 0, 0), tz)
        last = monthrange(year, i)[1]
        last_dt = timezone.make_aware(datetime(year, i, last, 23, 59, 59), tz)
        agg = ytd_qs.filter(trip__end_time__gte=first, trip__end_time__lte=last_dt).aggregate(
            r=Sum('total_revenue'), e=Sum('total_expense'), inc=Sum('income_before_tax')
        )
        revenue_series.append(float(d0(agg['r'])))
        expense_series.append(float(d0(agg['e'])))
        income_series.append(float(d0(agg['inc'])))
        months_labels.append(datetime(year, i, 1).strftime('%b'))

    # Top trucks by income YTD
    truck_map = {}
    for fin in ytd_qs:
        truck = fin.trip.truck
        if not truck:
            continue
        obj = truck_map.setdefault(truck.pk, {
            'truck_plate': truck.plate_number,
            'revenue': Decimal('0'),
            'expense': Decimal('0'),
            'income': Decimal('0'),
        })
        obj['revenue'] += d0(fin.total_revenue)
        obj['expense'] += d0(fin.total_expense)
        obj['income'] += d0(fin.income_before_tax)
    top_trucks = sorted(truck_map.values(), key=lambda x: x['income'], reverse=True)[:5]

    # Expense breakdown by category YTD
    exp_by_cat = {}
    for fin in ytd_qs.prefetch_related('expenses'):
        for exp in fin.expenses.all():
            exp_by_cat[exp.category] = exp_by_cat.get(exp.category, Decimal('0')) + d0(exp.amount)
    expense_breakdown = [{'category': k, 'amount': float(v)} for k, v in exp_by_cat.items()]

    context = {
        'user_role': user_role,
        'year': year,
        'month_str': month_str,
        # KPI cards
        'ytd_revenue': ytd_revenue,
        'ytd_expense': ytd_expense,
        'ytd_income': ytd_income,
        'ytd_margin': ytd_margin,
        'm_revenue': m_revenue,
        'm_expense': m_expense,
        'm_income': m_income,
        'm_margin': m_margin,
        # Charts data
        'months_labels_json': json.dumps(months_labels),
        'series_revenue_json': json.dumps(revenue_series),
        'series_income_json': json.dumps(income_series),
        'series_expense_json': json.dumps(expense_series),
        'expense_breakdown_json': json.dumps(expense_breakdown),
        'top_trucks_json': json.dumps([
            {
                'truck_plate': t['truck_plate'],
                'revenue': float(t['revenue']),
                'expense': float(t['expense']),
                'income': float(t['income']),
            } for t in top_trucks
        ]),
    }

    return render(request, 'transportation/reports_hub.html', context)


class MonthlyReportView(LoginRequiredMixin, TemplateView):
    template_name = "transportation/monthly_report.html"

    # Restrict to ADMIN or MANAGER only
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)

        # Parse the month parameter (format: YYYY-MM)
        month_str = self.request.GET.get('month')
        if month_str:
            try:
                year, month = map(int, month_str.split('-'))
            except Exception:
                now = timezone.now()
                year, month = now.year, now.month
        else:
            now = timezone.now()
            year, month = now.year, now.month

        tz = timezone.get_current_timezone()
        start_date = timezone.make_aware(datetime(year, month, 1, 0, 0, 0), tz)
        end_date = timezone.make_aware(datetime(year, month, monthrange(year, month)[1], 23, 59, 59), tz)

        # Get financials for the month
        financials = TripFinancial.objects.filter(
            trip__end_time__gte=start_date,
            trip__end_time__lte=end_date
        )

        # Overall totals (for the month)
        overall = financials.aggregate(
            total_revenue=Sum('total_revenue'),
            total_expense=Sum('total_expense'),
            income_before_tax=Sum('income_before_tax')
        )
        if overall.get('total_revenue'):
            overall['net_profit_margin'] = (overall['income_before_tax'] / overall['total_revenue']) * 100
        else:
            overall['net_profit_margin'] = 0

        # Build truck-wise financial summary
        truck_data = {}
        for fin in financials:
            truck = fin.trip.truck
            if not truck:
                continue
            if truck.pk not in truck_data:
                truck_data[truck.pk] = {
                    'truck_plate': truck.plate_number,
                    'total_revenue': fin.total_revenue or 0,
                    'total_expense': fin.total_expense or 0,
                    'income_before_tax': fin.income_before_tax or 0,
                }
            else:
                truck_data[truck.pk]['total_revenue'] += fin.total_revenue or 0
                truck_data[truck.pk]['total_expense'] += fin.total_expense or 0
                truck_data[truck.pk]['income_before_tax'] += fin.income_before_tax or 0

        truck_data_list = []
        for data in truck_data.values():
            if data['total_revenue'] > 0:
                data['net_profit_margin'] = (data['income_before_tax'] / data['total_revenue']) * 100
            else:
                data['net_profit_margin'] = 0
            truck_data_list.append(data)

        # -------------------------------------------------
        # Compute raw expense data by truck and category for the month
        # -------------------------------------------------
        raw_expense_data = {}  # key: (truck_plate, category) -> total expense
        for fin in financials:
            truck = fin.trip.truck
            if not truck:
                continue
            truck_plate = truck.plate_number
            for expense in fin.expenses.all():
                key = (truck_plate, expense.category)
                raw_expense_data[key] = raw_expense_data.get(key, Decimal('0.00')) + (expense.amount or Decimal('0.00'))
        raw_expense_list = []
        for (truck_plate, category), total in raw_expense_data.items():
            raw_expense_list.append({
                'truck_plate': truck_plate,
                'category': category,
                'expense': float(total)
            })

        # Inject data into context
        context['month_str'] = f"{year}-{month:02d}"
        context['overall_totals'] = overall
        context['truck_data_list'] = truck_data_list
        context['truck_chart_data'] = json.dumps(truck_data_list, default=float)
        context['raw_expense_chart_data'] = json.dumps(raw_expense_list)
        context['overall_totals_jslon'] = json.dumps(overall, default=float)
        # For the monthly report, we use one label (the month string)
        context['months'] = [f"{year}-{month:02d}"]
        context['months_json'] = json.dumps(context['months'])
        return context






class AnnualReportView(LoginRequiredMixin, TemplateView):
    template_name = "transportation/annual_report.html"

    # Restrict to ADMIN or MANAGER only
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_role = get_user_role(self.request)
        context['user_role'] = user_role

        # ---------------------------
        # 1. Determine the year
        # ---------------------------
        year_param = self.request.GET.get('year')
        if year_param:
            try:
                year = int(year_param)
            except ValueError:
                year = timezone.now().year
        else:
            year = timezone.now().year

        tz = timezone.get_current_timezone()
        start_date = timezone.make_aware(datetime(year, 1, 1, 0, 0, 0), tz)
        end_date = timezone.make_aware(datetime(year, 12, 31, 23, 59, 59), tz)

        # ---------------------------
        # 2. Query Financials
        # ---------------------------
        financials = TripFinancial.objects.filter(
            trip__end_time__gte=start_date,
            trip__end_time__lte=end_date
        )

        # ---------------------------
        # 3. Overall Structures
        # ---------------------------
        overall_totals = {
            'total_revenue': Decimal('0.00'),
            'total_expense': Decimal('0.00'),
            'income_before_tax': Decimal('0.00'),
        }
        overall_monthly = {
            'total_revenue': [Decimal('0.00')] * 12,
            'total_expense': [Decimal('0.00')] * 12,
            'income_before_tax': [Decimal('0.00')] * 12,
            'profit_margin': [Decimal('0.00')] * 12,
        }

        # ---------------------------
        # 4. Per-Truck Structures
        # ---------------------------
        truck_monthly = {}  # monthly revenue/expense/income for each truck
        truck_expense_by_category = {}  # { truck_id: {category: [12 months of Decimals]} }

        # ---------------------------
        # 5. Also, build "overall" expense_by_category for the entire chart
        # ---------------------------
        expense_by_category = {}  # For the ENTIRE system (all trucks) in this year

        # ---------------------------
        # 6. Aggregate Data
        # ---------------------------
        for fin in financials:
            # Ensure there's a valid start_time
            if not fin.trip.start_time:
                continue
            month_index = fin.trip.start_time.month - 1

            # Retrieve or default zero
            total_rev = fin.total_revenue or Decimal('0.00')
            total_exp = fin.total_expense or Decimal('0.00')
            inc_b4_tax = fin.income_before_tax or Decimal('0.00')

            # Update Overall Totals
            overall_totals['total_revenue'] += total_rev
            overall_totals['total_expense'] += total_exp
            overall_totals['income_before_tax'] += inc_b4_tax

            overall_monthly['total_revenue'][month_index] += total_rev
            overall_monthly['total_expense'][month_index] += total_exp
            overall_monthly['income_before_tax'][month_index] += inc_b4_tax

            # Per-Truck Aggregation
            truck = fin.trip.truck
            if not truck:
                continue
            truck_id = truck.pk
            if truck_id not in truck_monthly:
                truck_monthly[truck_id] = {
                    'truck_plate': truck.plate_number,
                    'monthly_revenue': [Decimal('0.00')] * 12,
                    'monthly_expense': [Decimal('0.00')] * 12,
                    'monthly_income': [Decimal('0.00')] * 12,
                    'yearly_total_revenue': Decimal('0.00'),
                    'yearly_total_expense': Decimal('0.00'),
                    'yearly_income': Decimal('0.00'),
                }
            truck_monthly[truck_id]['monthly_revenue'][month_index] += total_rev
            truck_monthly[truck_id]['monthly_expense'][month_index] += total_exp
            truck_monthly[truck_id]['monthly_income'][month_index] += inc_b4_tax

            truck_monthly[truck_id]['yearly_total_revenue'] += total_rev
            truck_monthly[truck_id]['yearly_total_expense'] += total_exp
            truck_monthly[truck_id]['yearly_income'] += inc_b4_tax

            # Iterate over all Expense line items for this TripFinancial
            for expense in fin.expenses.all():
                cat = expense.category
                amt = expense.amount or Decimal('0.00')

                # 6a. Overall expense_by_category
                if cat not in expense_by_category:
                    expense_by_category[cat] = [Decimal('0.00')] * 12
                expense_by_category[cat][month_index] += amt

                # 6b. Truck-level expense_by_category
                if truck_id not in truck_expense_by_category:
                    truck_expense_by_category[truck_id] = {}
                if cat not in truck_expense_by_category[truck_id]:
                    truck_expense_by_category[truck_id][cat] = [Decimal('0.00')] * 12
                truck_expense_by_category[truck_id][cat][month_index] += amt

        # ---------------------------
        # 7. Compute Overall Profit Margins
        # ---------------------------
        for i in range(12):
            rev = overall_monthly['total_revenue'][i]
            inc = overall_monthly['income_before_tax'][i]
            if rev > 0:
                overall_monthly['profit_margin'][i] = (inc / rev) * Decimal('100.00')
            else:
                overall_monthly['profit_margin'][i] = Decimal('0.00')

        # 7a. Overall totals profit margin
        if overall_totals['total_revenue'] > 0:
            overall_margin = (overall_totals['income_before_tax'] / overall_totals['total_revenue']) * Decimal('100.00')
        else:
            overall_margin = Decimal('0.00')

        overall_totals = {
            'total_revenue': float(overall_totals['total_revenue']),
            'total_expense': float(overall_totals['total_expense']),
            'income_before_tax': float(overall_totals['income_before_tax']),
            'profit_margin': float(overall_margin),
        }

        # ---------------------------
        # 8. Build Per-Truck Data
        # ---------------------------
        truck_data_list = []
        for t_id, t_data in truck_monthly.items():
            # Yearly profit margin for this truck
            if t_data['yearly_total_revenue'] > 0:
                t_profit_margin = (t_data['yearly_income'] / t_data['yearly_total_revenue']) * Decimal('100.00')
            else:
                t_profit_margin = Decimal('0.00')

            # Convert the truck-level category dict into a list for Chart.js
            cat_map = truck_expense_by_category.get(t_id, {})
            expense_categories_list = []
            for cat, monthly_exp in cat_map.items():
                expense_categories_list.append({
                    'category': cat,
                    'monthly_expense': [float(x) for x in monthly_exp]
                })

            # Build dictionary for JSON
            truck_data_list.append({
                'truck_plate': t_data['truck_plate'],
                'total_revenue': float(t_data['yearly_total_revenue']),
                'total_expense': float(t_data['yearly_total_expense']),
                'income_before_tax': float(t_data['yearly_income']),
                'profit_margin': float(t_profit_margin),
                'monthly_revenue': [float(x) for x in t_data['monthly_revenue']],
                'monthly_expense': [float(x) for x in t_data['monthly_expense']],
                'monthly_income': [float(x) for x in t_data['monthly_income']],
                'monthly_profit_margin': [
                    float((t_data['monthly_income'][i] / t_data['monthly_revenue'][i]) * 100)
                    if t_data['monthly_revenue'][i] != Decimal('0.00') else 0
                    for i in range(12)
                ],
                'expense_categories': expense_categories_list,
            })

        # ---------------------------
        # 9. Convert overall_monthly to float lists
        # ---------------------------
        for key in overall_monthly:
            overall_monthly[key] = [float(x) for x in overall_monthly[key]]

        # ---------------------------
        # 10. Build Overall expense_chart_data EXACTLY as your expense JS expects
        # ---------------------------
        expense_chart_data = []
        for cat, monthly_vals in expense_by_category.items():
            expense_chart_data.append({
                'category': cat,
                'monthly_expense': [float(x) for x in monthly_vals],
            })

        # ---------------------------
        # 11. Inject into Template Context
        # ---------------------------
        context['year'] = year
        context['overall_totals'] = overall_totals
        context['overall_monthly'] = overall_monthly
        context['truck_data_list'] = truck_data_list

        # JSON for Chart.js
        context['overall_chart_data'] = json.dumps(overall_monthly)
        context['truck_chart_data'] = json.dumps(truck_data_list)
        context['expense_chart_data'] = json.dumps(expense_chart_data)  # <--- for your overall expenseChart
        context['months'] = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        context['months_json'] = json.dumps(context['months'])

        return context





# -----------------------------------------------------
# ADDITIONAL: Office Usage Views (class-based + mixin)
# -----------------------------------------------------
class OfficeUsageListView(LoginRequiredMixin, ListView):
    model = OfficeUsage
    template_name = "transportation/office_usage_list.html"
    context_object_name = "usages"

    # Restrict to ADMIN or MANAGER only
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        qs = OfficeUsage.objects.select_related('truck', 'user').order_by('-start_time')
        truck_id = self.kwargs.get('truck_id')
        if truck_id:
            qs = qs.filter(truck_id=truck_id)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        truck_id = self.kwargs.get('truck_id')
        if truck_id:
            truck = get_object_or_404(Truck, pk=truck_id)
            context['truck'] = truck
        return context


class OfficeUsageDetailView(LoginRequiredMixin, DetailView):
    model = OfficeUsage
    template_name = "transportation/office_usage_detail.html"
    context_object_name = "usage"

    # Restrict to ADMIN or MANAGER only
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        context['truck'] = self.object.truck
        return context


class OfficeUsageCreateView(LoginRequiredMixin, CreateView):
    model = OfficeUsage
    form_class = OfficeUsageForm
    template_name = "transportation/office_usage_form.html"

    # Restrict to ADMIN or MANAGER only
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        truck_id = self.kwargs.get('truck_id')
        if truck_id:
            truck = get_object_or_404(Truck, pk=truck_id)
            context['truck'] = truck
        return context

    def form_valid(self, form):
        truck = get_object_or_404(Truck, pk=self.kwargs.get('truck_id'))
        form.instance.truck = truck
        if hasattr(self.request.user, 'staff'):
            form.instance.user = self.request.user.staff
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('home')


class OfficeUsageUpdateView(LoginRequiredMixin, UpdateView):
    model = OfficeUsage
    form_class = OfficeUsageForm
    template_name = "transportation/office_usage_form.html"

    # Restrict to ADMIN, MANAGER, DRIVER
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        context['truck'] = self.object.truck
        return context

    def get_success_url(self):
        return reverse_lazy('home')


class OfficeUsageDeleteView(LoginRequiredMixin, DeleteView):
    model = OfficeUsage
    template_name = "transportation/office_usage_confirm_delete.html"

    # Restrict to ADMIN, MANAGER, DRIVER
    def dispatch(self, request, *args, **kwargs):
        allowed, user_role = check_user_role(request, ['ADMIN', 'MANAGER', 'DRIVER'])
        if not allowed:
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_role'] = get_user_role(self.request)
        context['truck'] = self.object.truck
        return context

    def get_success_url(self):
        return reverse_lazy('home')
