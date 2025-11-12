"""Simple deterministic anomaly rules for system manager dashboard."""

from datetime import timedelta
from django.utils import timezone
from django.db.models import Q

from WareDGT.models import BinCardEntry, PurchaseOrder


def get_anomaly_alerts():
    alerts = []

    # ANOM_NEG_STOCK
    for entry in BinCardEntry.objects.filter(balance__lt=0)[:20]:
        alerts.append(
            {
                "id": "ANOM_NEG_STOCK",
                "severity": "high",
                "title": "Negative stock",
                "entity": f"Lot {entry.in_out_no}",
                "qty": float(entry.balance),
            }
        )

    # ANOM_PO_OVERDUE
    grace = timezone.now().date() - timedelta(days=1)
    overdue = PurchaseOrder.objects.filter(
        Q(pickup_deadline__lt=grace), Q(movements__isnull=True)
    )
    for po in overdue:
        alerts.append(
            {
                "id": "ANOM_PO_OVERDUE",
                "severity": "medium",
                "title": "PO overdue",
                "entity": f"PO#{po.id}",
            }
        )

    return {"rules_version": "v1", "alerts": alerts}

