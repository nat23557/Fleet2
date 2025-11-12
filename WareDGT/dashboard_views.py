"""Views for System Manager dashboard."""

import json
from datetime import timedelta
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.utils import timezone
from django.core.cache import cache
from django.db.models import Sum, Count

from .models import (
    BinCardEntry,
    PurchaseOrder,
    Warehouse,
    UserProfile,
    AuthEvent,
    UserEvent,
    DashboardConfig,
)
from .services.dashboard_anomalies import get_anomaly_alerts
from .services import sm_benchmarks, sm_risk


def admin_required(view):
    @login_required
    def _wrapped(request, *args, **kwargs):
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != UserProfile.ADMIN:
            return JsonResponse({"detail": "Forbidden"}, status=403)
        return view(request, *args, **kwargs)

    return _wrapped


@login_required
def system_manager_dashboard(request):
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role != UserProfile.ADMIN:
        raise Http404()
    return render(request, "dashboard/system_manager.html")


def _kpi_payload():
    now = timezone.now()
    total_qty = BinCardEntry.objects.aggregate(total=Sum("balance"))["total"] or 0
    total_cap = Warehouse.objects.aggregate(total=Sum("capacity_quintals"))["total"] or 0
    backlog = PurchaseOrder.objects.exclude(status__in=["COMPLETED", "CANCELLED"]).count()
    cap_util = float(total_qty / total_cap * 100) if total_cap else 0
    cards = [
        {
            "key": "total_inventory_qty_qtl",
            "label": "Total Inventory",
            "value": float(total_qty),
            "unit": "qtl",
            "trend": {"pct_7d": 0},
        },
        {
            "key": "total_inventory_value_etb",
            "label": "Inventory Value",
            "value": 0.0,
            "unit": "ETB",
            "note": "NA if price missing",
        },
        {
            "key": "order_backlog",
            "label": "Open POs",
            "value": backlog,
            "unit": "po",
        },
        {
            "key": "on_time_inbound_rate",
            "label": "On-Time Inbound",
            "value": 0.0,
            "unit": "%",
        },
        {
            "key": "capacity_utilization",
            "label": "Capacity Used",
            "value": float(cap_util),
            "unit": "%",
        },
    ]

    anomalies = get_anomaly_alerts()
    severity = {}
    for a in anomalies["alerts"]:
        severity[a["severity"]] = severity.get(a["severity"], 0) + 1
    top_risks = [
        {"title": f"{k.title()} risks", "severity": k, "count": v}
        for k, v in severity.items()
    ][:3]
    return {
        "generated_at": now.isoformat(),
        "cards": cards,
        "top_risks": top_risks,
    }


def _activity_payload():
    start = timezone.now() - timedelta(days=30)
    created = UserEvent.objects.filter(event="CREATE", ts__gte=start).count()
    deactivated = UserEvent.objects.filter(event="DEACTIVATE", ts__gte=start).count()
    role_changed = UserEvent.objects.filter(event="ROLE_CHANGE", ts__gte=start).count()
    login_failed = AuthEvent.objects.filter(event="LOGIN_FAIL", ts__gte=start).count()
    top_failed = list(
        AuthEvent.objects.filter(event="LOGIN_FAIL", ts__gte=start)
        .values("username")
        .annotate(count=Count("id"))
        .order_by("-count")[:5]
    )
    recent = []
    for e in UserEvent.objects.filter(ts__gte=start).order_by("-ts")[:5]:
        recent.append(
            {
                "ts": e.ts.isoformat(),
                "actor": getattr(e.actor, "username", ""),
                "type": e.event,
                "desc": "",
            }
        )
    for e in AuthEvent.objects.filter(ts__gte=start).order_by("-ts")[:5]:
        recent.append(
            {
                "ts": e.ts.isoformat(),
                "actor": e.username,
                "type": e.event,
                "desc": "",
            }
        )
    recent.sort(key=lambda x: x["ts"], reverse=True)
    return {
        "window_days": 30,
        "users_created": created,
        "users_deactivated": deactivated,
        "roles_changed": role_changed,
        "login_failed": login_failed,
        "login_failed_top_users": top_failed,
        "recent_events": recent[:5],
    }


@admin_required
def sm_kpis(request):
    key = f"sm-kpis:{request.user.profile.role}"
    data = cache.get(key)
    if not data:
        data = _kpi_payload()
        cache.set(key, data, 60)
    return JsonResponse(data)


@admin_required
def sm_activity(request):
    key = f"sm-activity:{request.user.profile.role}"
    data = cache.get(key)
    if not data:
        data = _activity_payload()
        cache.set(key, data, 60)
    return JsonResponse(data)


@admin_required
def sm_anomalies(request):
    key = f"sm-anom:{request.user.profile.role}"
    data = cache.get(key)
    if not data:
        data = get_anomaly_alerts()
        cache.set(key, data, 60)
    return JsonResponse(data)


@admin_required
def sm_config(request):
    if request.method == "GET":
        role = request.GET.get("role", request.user.profile.role)
        cfg, _ = DashboardConfig.objects.get_or_create(role=role)
        return JsonResponse({"role": cfg.role, "widgets": cfg.widgets})
    else:
        body = json.loads(request.body.decode() or "{}")
        role = body.get("role")
        widgets = body.get("widgets", {})
        cfg, _ = DashboardConfig.objects.update_or_create(
            role=role,
            defaults={"widgets": widgets, "updated_by": request.user},
        )
        return JsonResponse({"role": cfg.role, "widgets": cfg.widgets})


def is_admin(user):
    profile = getattr(user, "profile", None)
    return bool(profile and profile.role == UserProfile.ADMIN) or getattr(user, "is_superuser", False)


@user_passes_test(is_admin)
def sm_benchmarks_view(request):
    rows = sm_benchmarks.collect()
    return JsonResponse({"rows": rows})


@user_passes_test(is_admin)
def sm_risk_view(request):
    payload = sm_risk.score()
    return JsonResponse(payload)

