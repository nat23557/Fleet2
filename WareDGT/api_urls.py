from rest_framework.routers import DefaultRouter
from . import views, dashboard_views
from .dashboard_views import sm_benchmarks_view, sm_risk_view

router = DefaultRouter()
router.register("warehouses", views.WarehouseViewSet)
router.register("purchased-item-types", views.PurchasedItemTypeViewSet)
router.register("load-requests", views.LoadRequestViewSet, basename="load-request")
router.register("ecx/movements", views.EcxMovementViewSet)
router.register("contract/movements", views.ContractMovementViewSet)
router.register("seed-types", views.SeedTypeViewSet)
router.register("seed-type-details", views.SeedTypeDetailViewSet)
router.register("bincards", views.BinCardViewSet)
router.register("bincard-transactions", views.BinCardTransactionViewSet)
router.register("daily-records", views.DailyRecordViewSet)
router.register("seed-type-balances", views.SeedTypeBalanceViewSet)
router.register("lots", views.BinCardEntryViewSet)

from django.urls import path

urlpatterns = router.urls + [
    path("stock-series/", views.stock_series, name="stock-series"),
    path("stock-events/", views.stock_events, name="stock-events"),
    path("stock-filters/", views.stock_filters, name="stock-filters"),
    path("ecx/owners/", views.ecx_owners, name="ecx-owners"),
    path("stock/seed-types/available", views.stock_seed_types_available),
    path("stock/owners/available", views.stock_owners_available),
    path("stock/classes/available", views.stock_classes_available),
    path("stock/specs/available", views.stock_specs_available),
    path("stock/validate-out", views.validate_stock_out),
    path("stock/out", views.register_stock_out),
    path("stock/borrow/return", views.register_borrow_return),
    path("dashboard/system-manager/kpis/", dashboard_views.sm_kpis),
    path("dashboard/system-manager/activity/", dashboard_views.sm_activity),
    path("dashboard/system-manager/anomalies/", dashboard_views.sm_anomalies),
    path("dashboard/system-manager/config/", dashboard_views.sm_config),
    path("dashboard/system-manager/benchmarks/", sm_benchmarks_view, name="sm_benchmarks"),
    path("dashboard/system-manager/risk-score/", sm_risk_view, name="sm_risk"),
]
