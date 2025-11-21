from django.urls import path
from . import views


app_name = "cash_management"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("summary/", views.cash_summary, name="cash_summary"),
    path("banks/", views.banks, name="banks"),
    path("banks/register/", views.bank_register, name="bank_register"),
    path("banks/<str:name>/", views.bank_detail, name="bank_detail"),
    path("daily/", views.daily, name="daily"),
    path("live/", views.live_cash, name="live"),
    path("live/feed/", views.live_cash_feed, name="live_feed"),
    path("accounts/<int:pk>/", views.account_ledger, name="account_ledger"),
    path("accounts/new/", views.account_new, name="account_new"),
    path("accounts/<int:pk>/edit/", views.account_edit, name="account_edit"),
    path("transactions/new/", views.new_transaction, name="new_transaction"),
    path("transactions/<int:tx_id>/reverse/", views.reverse_transaction, name="reverse_transaction"),
    path("analytics/", views.analytics, name="analytics"),
]
