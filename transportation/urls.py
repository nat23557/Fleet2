# transportation/urls.py

from django.urls import path
from . import views
# urls.py
from django.urls import path
from .views import (
    accident_list, accident_detail, accident_create, accident_update, accident_delete,
    service_list, service_detail, service_create, service_update, service_delete,
    replaced_item_list, replaced_item_detail, replaced_item_create, replaced_item_update, replaced_item_delete, trip_complete_confirmation, trip_complete
)

from .views import report_index, MonthlyReportView, AnnualReportView


# urls.py
from django.urls import path
from .views import (
     TripDetailView, TripCreateView, TripUpdateView, ExpenseCreateView, ExpenseUpdateView,
    InvoiceCreateView, InvoiceUpdateView, mark_invoice_paid, TripPdfView, OperationalExpenseDetailCreateView,
    OperationalExpenseDetailUpdateView
)

from django.urls import path
from .views import (
    OfficeUsageListView, OfficeUsageDetailView,
    OfficeUsageCreateView, OfficeUsageUpdateView, OfficeUsageDeleteView
)
from . import views as tviews


urlpatterns = [



 # User-related functionalities
    path('profile/', views.user_profile, name='user-profile'),
    path('profile/update/', views.update_profile, name='update-profile'),
    path('profile/change-password/', views.change_password, name='change-password'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    # Dashboard data (live refresh)
    path('dashboard/data/', views.dashboard_data, name='dashboard-data'),
    path('api/live/trips/', views.live_trips_status, name='live-trips-status'),
    path('api/trip/<int:trip_id>/route/', views.trip_route, name='trip-route'),
    # Hubs
    path('operations/', tviews.operations_hub, name='operations_hub'),
    path('people/', tviews.people_hub, name='people_hub'),
    # Driver home (map/GPS-free)
    path('driver/', tviews.driver_home, name='driver_home'),

    # Simple landing hub and focused pages
    path('hub/', views.home_hub, name='home_hub'),
    path('map/', views.fleet_map_page, name='fleet_map_page'),
    path('trips/active/', views.active_trips_overview, name='active_trips_overview'),
    path('trips/completed/matrix/', views.completed_trips_matrix, name='completed_trips_matrix'),
    path('drivers/performance/', views.driver_performance, name='driver_performance'),
    # Avoid Django admin catch-all; expose actions at a neutral path
    path('actions/', views.admin_actions_hub, name='admin_actions_hub'),






    # INDEX / HOME
    path('', views.index, name='home'),









    # STAFF
    path('staff/', views.staff_list, name='staff-list'),
    path('staff/<int:pk>/', views.staff_detail, name='staff-detail'),
    path('staff/create/', views.staff_create, name='staff-create'),
    path('staff/<int:pk>/update/', views.staff_update, name='staff-update'),
    path('staff/<int:pk>/delete/', views.staff_delete, name='staff-delete'),

    # DRIVER
    path('drivers/', views.driver_list, name='driver-list'),
    path('drivers/<int:pk>/', views.driver_detail, name='driver-detail'),
    path('drivers/create/', views.driver_create, name='driver-create'),
    path('drivers/<int:pk>/update/', views.driver_update, name='driver-update'),
    path('drivers/<int:pk>/delete/', views.driver_delete, name='driver-delete'),

    # TRUCK
    path('trucks/', views.truck_list, name='truck-list'),
    path('trucks/<int:pk>/', views.truck_detail, name='truck-detail'),
    path('trucks/<int:pk>/status/', views.truck_status, name='truck-status'),
    path('trucks/status/', views.truck_status, name='truck-status-all'),
    path('trucks/create/', views.truck_create, name='truck-create'),
    path('trucks/<int:pk>/update/', views.truck_update, name='truck-update'),
    path('trucks/<int:pk>/delete/', views.truck_delete, name='truck-delete'),

    # CARGO
    path('cargo/', views.cargo_list, name='cargo-list'),
    path('cargo/<int:pk>/', views.cargo_detail, name='cargo-detail'),
    path('cargo/create/', views.cargo_create, name='cargo-create'),
    path('cargo/<int:pk>/update/', views.cargo_update, name='cargo-update'),
    path('cargo/<int:pk>/delete/', views.cargo_delete, name='cargo-delete'),

   

    

    # MajorAccident
    path('accidents/<int:truck_id>/list', accident_list, name='accident-list'),
    path('accidents/<int:pk>/detail', accident_detail, name='accident-detail'),
    path('accidents/<int:truck_id>/create/', accident_create, name='accident-create'),
    path('accidents/<int:pk>/update/', accident_update, name='accident-update'),
    path('accidents/<int:pk>/delete/', accident_delete, name='accident-delete'),

    # ServiceRecord
    path('services/<int:truck_id>/list', service_list, name='service-list'),
    path('services/<int:pk>/detail', service_detail, name='service-detail'),
    path('services/<int:truck_id>/create/', service_create, name='service-create'),
    path('services/<int:pk>/update/', service_update, name='service-update'),
    path('services/<int:pk>/delete/', service_delete, name='service-delete'),

    # ReplacedItem
    path('replaced-items/<int:truck_id>/list', replaced_item_list, name='replaced-item-list'),
    path('replaced-items/<int:pk>/detail', replaced_item_detail, name='replaced-item-detail'),
    path('replaced-items/<int:truck_id>/create/', replaced_item_create, name='replaced-item-create'),
    path('replaced-items/<int:pk>/update/', replaced_item_update, name='replaced-item-update'),
    path('replaced-items/<int:pk>/delete/', replaced_item_delete, name='replaced-item-delete'),

    # Trip URLs
    path('trips/', views.trip_list, name='trip_list'),
    path('trips/create/', TripCreateView.as_view(), name='trip_create'),
    path('trip/<int:pk>/', TripDetailView.as_view(), name='trip_detail'),
    path('trips/completed-filter/', views.trip_completed_filter, name='trip_completed_filter'),
    path('trips/<int:pk>/update/', TripUpdateView.as_view(), name='trip_update'),
    path('trip/<int:pk>/pdf/', TripPdfView.as_view(), name='trip_pdf'),

    # Trip Financial URL
    path('trip/<int:trip_id>/operational-expense/add/', OperationalExpenseDetailCreateView.as_view(), name='operational_expense_add'),
    
    # URL for editing an existing operational expense detail; pk corresponds to the expense detail record.
    path('operational-expense/<int:pk>/edit/', OperationalExpenseDetailUpdateView.as_view(), name='operational_expense_edit'),

    # Expense URLs
    path('financial/<int:financial_id>/expense/create/', ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/update/', ExpenseUpdateView.as_view(), name='expense_update'),
    path("expense/<int:pk>/delete/", views.expense_delete, name="expense_delete"),

    # Invoice URLs
    path('trips/<int:trip_id>/invoice/create/', InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoice/<int:pk>/update/', InvoiceUpdateView.as_view(), name='invoice_update'),
    path('invoice/<int:invoice_id>/mark_paid/', mark_invoice_paid, name='mark_invoice_paid'),
    path("trip/<int:trip_id>/complete/confirm/", trip_complete_confirmation, name="trip_complete_confirmation"),
    path("trip/<int:trip_id>/complete/", trip_complete, name="trip_complete"),
    # reports/urls.py

    path('reports/', report_index, name='report_index'),
    # Zero-to-one: manager-friendly weekly narrative report
    path('reports/weekly-story/', views.weekly_story_mode, name='weekly_story_mode'),

    path('reports/monthly/', MonthlyReportView.as_view(), name='monthly-report'),
    path('reports/annual/', AnnualReportView.as_view(), name='annual-report'),
  
# urls.py
    path('office-usage/<int:truck_id>/', OfficeUsageListView.as_view(), name='office_usage_list'),
# urls.py
    path('office-usage/create/<int:truck_id>/', OfficeUsageCreateView.as_view(), name='office_usage_create'),
    path('office-usage/<int:pk>/', OfficeUsageDetailView.as_view(), name='office_usage_detail'),
    path('office-usage/<int:pk>/edit/', OfficeUsageUpdateView.as_view(), name='office_usage_update'),
    path('office-usage/<int:pk>/delete/', OfficeUsageDeleteView.as_view(), name='office_usage_delete'),

    # Geofence events (email notifications) + persistence
    path('geofence/event/', views.geofence_event, name='geofence_event'),
    path('geofence/<int:truck_id>/list/', views.geofence_list, name='geofence_list'),
    path('geofence/<int:truck_id>/create/', views.geofence_create, name='geofence_create'),
    path('geofence/<int:truck_id>/clear/', views.geofence_clear, name='geofence_clear'),
]
