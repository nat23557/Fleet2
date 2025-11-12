from django.contrib import admin

from .models import BankAccount, Transaction, ExchangeRate


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "bank_name", "currency", "created_at")
    search_fields = ("name", "bank_name")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "date",
        "account",
        "description",
        "debit",
        "credit",
        "created_by",
        "created_at",
        "modified_by",
        "modified_at",
    )
    list_filter = ("account", "date")
    search_fields = ("description", "reference")

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Enforce immutability in admin
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if 'delete_selected' in actions:
            del actions['delete_selected']
        return actions


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ("date", "currency", "rate", "source", "created_at")
    list_filter = ("date", "currency")
    search_fields = ("currency",)
