from django.contrib import admin

from .models import BinCardTransaction, BinCardEntry, SeedTypeBalance, DailyRecord, CleanedStockOut


@admin.register(BinCardTransaction)
class BinCardTransactionAdmin(admin.ModelAdmin):
    list_display = ("ts", "movement", "commodity", "warehouse", "lot", "qty_kg")
    list_filter = ("movement", "commodity", "warehouse", "lot", "ts")
    search_fields = ("note",)


@admin.register(BinCardEntry)
class BinCardEntryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seed_type",
        "warehouse",
        "unloading_rate_etb_per_qtl",
        "loading_rate_etb_per_qtl",
        "raw_balance_kg",
        "cleaned_total_kg",
        "rejects_total_kg",
        "last_cleaned_at",
    )
    list_filter = ("warehouse", "seed_type")


@admin.register(DailyRecord)
class DailyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "operation_type",
        "warehouse",
        "lot",
        "weight_in",
        "weight_out",
    )
    list_filter = ("operation_type", "warehouse")
    filter_horizontal = ("workers",)


@admin.register(SeedTypeBalance)
class SeedTypeBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "warehouse",
        "owner",
        "seed_type",
        "purity",
        "cleaned_kg",
        "rejects_kg",
        "updated_at",
    )
    list_filter = ("warehouse", "owner", "seed_type", "purity")


@admin.register(CleanedStockOut)
class CleanedStockOutAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "owner",
        "seed_type",
        "weight",
        "loading_rate_etb_per_qtl",
        "date",
    )
