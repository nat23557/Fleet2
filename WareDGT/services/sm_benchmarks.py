from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum
from WareDGT.models import Warehouse, BinCardEntry, PurchaseOrder, QualityAnalysis


def collect():
    rows = []
    week_ago = timezone.now() - timedelta(days=7)
    for w in Warehouse.objects.all():
        qty = (
            BinCardEntry.objects.filter(warehouse=w).aggregate(q=Sum("balance"))["q"]
            or 0
        )
        cap = getattr(w, "capacity_quintals", None)
        util = float(qty / cap * 100) if cap else 0
        open_pos = (
            PurchaseOrder.objects.filter(company_warehouse=w)
            .exclude(status__in=["COMPLETED", "CANCELLED"])
            .count()
        )
        ontime = getattr(w, "on_time_inbound_pct", 0) or 0
        qc_fail = (
            QualityAnalysis.objects.filter(
                movement__warehouse=w,
                first_purity_percent__lt=90,
                movement__ticket_date__gte=week_ago.date(),
            ).count()
        )
        rows.append(
            {
                "name": w.name,
                "capacity_utilization": util,
                "stock_qtl": float(qty),
                "open_pos": open_pos,
                "on_time_inbound": ontime,
                "qc_fail_7d": qc_fail,
            }
        )
    return rows
