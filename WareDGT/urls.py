from django.urls import path
from django.contrib.auth import views as auth_views
from . import views, dashboard_views

urlpatterns = [
    # Auth & Dashboard
    path('',                views.dashboard,        name='dashboard'),
    # Use global site auth routes; keep warehouse login path as alias if needed
    # path('login/',          views.login_view,       name='warehouse_login'),
    # path('logout/',         views.logout_view,      name='warehouse_logout'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='WareDGT/password_reset_form.html',
        email_template_name='WareDGT/password_reset_email.html',
        html_email_template_name='emails/password_reset.html'
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='WareDGT/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.PasswordSetupConfirmView.as_view(
        template_name='WareDGT/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='WareDGT/password_reset_complete.html'
    ), name='password_reset_complete'),

    # Header links
    path('notifications/',  views.notifications,    name='notifications'),
    path('messages/',       views.messages_view,    name='messages'),

    # Sidebar links
    path('stock-movements/',   views.stock_movements,   name='stock_movements'),
    path('borrowed-stocks/',   views.borrowed_stocks,   name='borrowed_stocks'),
    path('borrowed-stocks/export/', views.borrowed_stocks_export, name='borrowed_stocks_export'),
    path('ecx-movements/<int:pk>/weigh/', views.ecx_movement_weigh, name='ecx_movement_weigh'),
    path('ecx-shipments/<int:pk>/weigh/', views.ecx_shipment_weigh, name='ecx_shipment_weigh'),
    path('daily-records/',  views.daily_records,  name='daily_records'),
    # Hourly purity quick-add (no start/stop)
    path('daily-records/<int:pk>/hourly-purity/', views.add_hourly_purity, name='daily_record_hourly_purity'),
    path('daily-records/<int:pk>/weigh/', views.dailyrecord_reject_weighing, name='dailyrecord_reject_weighing'),
    path('ajax/load-seed-types/', views.load_seed_types, name='ajax_load_seed_types'),
    path('ajax/load-lots/', views.load_lots, name='ajax_load_lots'),
    path('ajax/lot-details/', views.lot_details, name='ajax_lot_details'),
    path('daily-records/<int:pk>/qc/add/', views.add_qc, name='daily_record_qc_add'),
    path('bincards/<int:lot_id>/', views.bincard_detail, name='bincard_detail'),
    path('bincards/<int:entry_id>/pdf/', views.bincard_pdf_view, name='bincard-pdf'),
    path('purchase-orders/',   views.purchase_orders,   name='purchase_orders'),
    path('bin-cards/',         views.bin_cards,         name='bin_cards'),
    path('bin-cards/export/',  views.bincards_export,   name='bincards_export'),
    path('requests/',        views.RequestListView.as_view(), name='request_list'),
    path('bin-cards/requests/<int:pk>/', views.bincard_request_review, name='bincard_request_review'),
    path('bin-cards/approve/<int:pk>/', views.approve_bincard_request, name='approve_bincard_request'),
    path('bin-cards/decline/<int:pk>/', views.decline_bincard_request, name='decline_bincard_request'),
    path('stock-out/requests/<int:pk>/', views.stockout_request_review, name='stockout_request_review'),
    path('stock-out/requests-sm/<int:pk>/', views.stockout_request_review_sm, name='stockout_request_review_sm'),
    path('stock-out/requests/<int:pk>/attach-weighbridge/', views.attach_stockout_weighbridge, name='attach_stockout_weighbridge'),
    path('stock-out/approve/<int:pk>/', views.approve_stockout_request, name='approve_stockout_request'),
    path('stock-out/approve-sm/<int:pk>/', views.approve_stockout_request_sm, name='approve_stockout_request_sm'),
    path('stock-out/decline/<int:pk>/', views.decline_stockout_request, name='decline_stockout_request'),
    path('stock-out/decline-sm/<int:pk>/', views.decline_stockout_request_sm, name='decline_stockout_request_sm'),
    path('stock-levels/',      views.stock_levels,      name='stock_levels'),
    path('reports/',           views.reports,           name='reports'),
    path('ecx-console/',       views.ecx_console,      name='ecx_console'),
    path('ecx-movements/',    views.EcxMovementListView.as_view(), name='ecxmovement_list'),
    path('contract-movements/', views.contract_movements, name='contract_movement_list'),
    path('local-purchases/',    views.local_purchases,   name='local_purchases'),
    path('sesame-contract/',   views.sesame_contract,  name='sesame_contract'),
    path('coffee-details/',    views.coffee_details,   name='coffee_details'),
    path('bean-contract/',     views.bean_contract,    name='bean_contract'),
    path('users/',             views.UserListView.as_view(),  name='user_list'),
    path('users/create/',      views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:user_id>/toggle/', views.user_toggle_active, name='user_toggle'),
    path('master-data/',       views.master_data,       name='master_data'),
    path('config/',            views.system_config,     name='system_config'),
    path('system-manager/dashboard/', dashboard_views.system_manager_dashboard, name='sm_dashboard'),

    # CRUD views
    path('purchase-orders/list/',   views.PurchaseOrderListView.as_view(),   name='purchaseorder_list'),
    path('purchase-orders/create/', views.PurchaseOrderCreateView.as_view(), name='purchaseorder_create'),
    path('stock-movements/create/', views.StockMovementCreateView.as_view(), name='stockmovement_create'),
    # Dummy list route for StockMovementCreateView success redirect
    path('stock-movements/list/',   views.StockMovementListView.as_view(),  name='stockmovement_list'),
    path('ecx-trades/list/',        views.EcxTradeListView.as_view(),       name='ecxtrade_list'),
    path('ecx-trades/create/',      views.EcxTradeCreateView.as_view(),     name='ecxtrade_create'),
    path('ecx-trades/<int:pk>/pdf/', views.ecx_trade_pdf,                    name='ecxtrade_pdf'),
    path('ecx-trades/requests/',    views.EcxTradeRequestListView.as_view(), name='ecxtrade_request_list'),
    path('ecx-trades/requests/<uuid:pk>/', views.EcxTradeRequestReviewView.as_view(), name='ecxtrade_request_review'),
    path('ecx-trades/requests/export/', views.ecxtrade_request_export, name='ecxtrade_request_export'),
    path('ecx-loads/create/',      views.EcxLoadCreateView.as_view(),     name='ecxload_create'),
    path('ecx-loads/requests/<uuid:pk>/', views.EcxLoadRequestReviewView.as_view(), name='ecxload_request_review'),
    path('ecx-loads/request-from-map/', views.ecx_load_request_from_map, name='ecx_load_request_from_map'),
    path('warehouses/list/',        views.WarehouseListView.as_view(),      name='warehouse_list'),
    path('warehouses/create/',      views.WarehouseCreateView.as_view(),    name='warehouse_create'),
    path('seed-types/list/',        views.SeedTypeDetailListView.as_view(), name='seedtypedetail_list'),
    path('seed-types/create/',      views.SeedTypeDetailCreateView.as_view(), name='seedtypedetail_create'),
    path('item-types/list/',        views.PurchasedItemTypeListView.as_view(), name='itemtype_list'),
    path('item-types/create/',      views.PurchasedItemTypeCreateView.as_view(), name='itemtype_create'),
    path('contractmovement/requests/', views.ContractMovementRequestListView.as_view(), name='contract_movement_request_list'),
    path('contractmovement/request/<uuid:pk>/', views.ContractMovementRequestReviewView.as_view(), name='contract_movement_request_review'),

    # Accountant overview
    path('accountant/overview/', views.AccountantOverviewView.as_view(), name='accountant_overview'),
]
