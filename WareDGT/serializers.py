from rest_framework import serializers
from django.db.models import Sum
from django.utils import timezone
from decimal import Decimal
from .models import (
    Warehouse,
    PurchasedItemType,
    EcxMovement,
    EcxMovementReceiptFile,
    ContractMovement,
    SeedType,
    SeedTypeDetail,
    BinCard,
    BinCardTransaction,
    DailyRecord,
    SeedTypeBalance,
    BinCardEntry,
)


class WarehouseSerializer(serializers.ModelSerializer):
    stock_totals = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "code",
            "name",
            "description",
            "warehouse_type",
            "capacity_quintals",
            "footprint_m2",
            "latitude",
            "longitude",
            "zone_geojson",
            "stock_totals",
        ]

    def get_stock_totals(self, obj):
        """Aggregate ECX trade quantities for the selected filters."""
        request = self.context.get("request")
        category = request.query_params.get("category") if request else None
        symbol = request.query_params.get("symbol") if request else None
        grade = request.query_params.get("grade") if request else None
        owner = request.query_params.get("owner") if request else None

        # Available stock must reflect what the load endpoint can actually use,
        # which is the pool of ECX trades that are not yet marked as loaded.
        # Using only unloaded trades keeps the UI consistent with the POST /load/
        # validation (which also filters by loaded=False) and avoids inflation
        # when historical data lacks matching movement rows.
        trades = obj.ecx_trades.filter(loaded=False)
        if owner:
            trades = trades.filter(owner_id=owner)

        if category:
            symbols = (
                SeedTypeDetail.objects.filter(category=category)
                .values_list("symbol", flat=True)
            )
            symbols = list(symbols)
            trades = trades.filter(commodity__seed_type__code__in=symbols)
        if symbol:
            trades = trades.filter(commodity__seed_type__code=symbol)
        if grade:
            trades = trades.filter(commodity__grade__icontains=grade)
        total = trades.aggregate(total=Sum("quantity_quintals"))["total"] or 0

        if total <= 0:
            return {}

        detail = None
        if symbol:
            detail = obj.seed_type_details.filter(symbol=symbol).first()
        if not detail and symbol:
            detail = SeedTypeDetail.objects.filter(symbol=symbol).first()

        name = detail.name if detail else symbol
        disp_grade = grade if grade else "All"
        key = f"{name} - {symbol} - {disp_grade}" if symbol else "Total"

        return {key: float(total)}


class SeedTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeedType
        fields = ["code", "name"]


class PurchasedItemTypeSerializer(serializers.ModelSerializer):
    code = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PurchasedItemType
        fields = ["id", "seed_type", "origin", "grade", "description", "code"]

    def get_code(self, obj):
        return obj.code


class SeedTypeDetailSerializer(serializers.ModelSerializer):
    delivery_location = serializers.PrimaryKeyRelatedField(
        queryset=Warehouse.objects.all()
    )

    class Meta:
        model = SeedTypeDetail
        fields = [
            "id",
            "category",
            "coffee_type",
            "symbol",
            "name",
            "delivery_location",
            # Expose the configured grade(s) so clients can
            # populate grade filters and cascaded selects.
            "grade",
            "origin",
            "handling_procedure",
        ]


class LoadStockSerializer(serializers.Serializer):
    stockline_id = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))
    truck_plate = serializers.CharField(max_length=20, required=False, allow_blank=True)
    symbol = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    grade = serializers.IntegerField(required=False, allow_null=True)


class EcxMovementReceiptFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EcxMovementReceiptFile
        fields = ["id", "image", "uploaded_at"]


class EcxMovementSerializer(serializers.ModelSerializer):
    # Accept images or PDFs
    receipt_images = serializers.ListField(
        child=serializers.FileField(), write_only=True, required=False
    )
    files = EcxMovementReceiptFileSerializer(
        many=True, read_only=True, source="receipt_files"
    )
    display = serializers.SerializerMethodField()
    weighbridge_certificate = serializers.FileField(required=False, allow_null=True)

    class Meta:
        model = EcxMovement
        fields = [
            "id",
            "warehouse",
            "item_type",
            "owner",
            "net_obligation_receipt_no",
            "warehouse_receipt_no",
            "quantity_quintals",
            "purchase_date",
            "created_by",
            "receipt_images",
            "files",
            "display",
            "weighbridge_certificate",
            "weighed",
            "weighed_at",
            "loaded",
            "loaded_at",
        ]
        read_only_fields = ["created_by", "loaded", "loaded_at", "weighed", "weighed_at"]

    def create(self, validated_data):
        images = validated_data.pop("receipt_images", [])
        request = self.context.get("request")
        if request and not validated_data.get("created_by"):
            validated_data["created_by"] = request.user
        movement = EcxMovement.objects.create(**validated_data)
        for img in images:
            EcxMovementReceiptFile.objects.create(movement=movement, image=img)
        return movement

    def update(self, instance, validated_data):
        if validated_data.get("weighbridge_certificate"):
            if not instance.loaded:
                instance.loaded = True
                instance.loaded_at = timezone.now()
            if not instance.weighed:
                instance.weighed = True
                instance.weighed_at = timezone.now()
        return super().update(instance, validated_data)

    def get_display(self, obj):
        return str(obj)


class ContractMovementSerializer(serializers.ModelSerializer):
    display = serializers.SerializerMethodField()

    class Meta:
        model = ContractMovement
        fields = [
            "id",
            "owner",
            "category",
            "symbol",
            "origin",
            "agent_name",
            "agent_phone",
            "advice_number",
            "dispatch_number",
            "dispatch_image",
            "quantity_quintals",
            "status",
            "created_at",
            "display",
        ]
        read_only_fields = ["status", "created_at"]

    def get_display(self, obj):
        parts = [obj.symbol, obj.dispatch_number]
        if obj.origin:
            parts.append(obj.origin)
        if obj.quantity_quintals:
            parts.append(f"{obj.quantity_quintals} qtl")
        return " – ".join([p for p in parts if p])


class BinCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = BinCard
        fields = ["id", "owner", "commodity", "warehouse"]


class BinCardTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BinCardTransaction
        fields = ["id", "bin_card", "date", "qty_in", "qty_out", "balance", "reference"]
        read_only_fields = ["date", "balance"]


class DailyRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyRecord
        fields = [
            "id",
            "date",
            "warehouse",
            "plant",
            "owner",
            "seed_type",
            "lot",
            "operation_type",
            "target_purity",
            "weight_in",
            "weight_out",
            "rejects",
            "purity_before",
            "purity_after",
            "shrink_margin",
            "passes",
            "remarks",
            "cleaning_equipment",
            "chemicals_used",
            "start_time",
            "end_time",
            "workers",
            "labor_rate_per_qtl",
            "cleaning_labor_rate_etb_per_qtl",
            "reject_weighing_rate_etb_per_qtl",
            "reject_labor_payment_per_qtl",
            "labor_cost",
            "recleaning_reason",
            "recorded_by",
            "created_at",
            "updated_at",
            "is_posted",
            "posted_by",
            "posted_at",
            "actual_reject_weight",
            "expected_reject_weight",
            "combined_expected_reject_weight",
            "deviation_pct",
            "status",
            "is_fishy",
            "reject_weighed_by",
            "reject_weighed_at",

        ]
        read_only_fields = [
            "labor_cost",
            "created_at",
            "updated_at",
            "is_posted",
            "posted_by",
            "posted_at",
            "recorded_by",
            "expected_reject_weight",
            "combined_expected_reject_weight",
            "deviation_pct",
            "is_fishy",
        ]

    def create(self, validated_data):
        request = self.context.get("request")
        if request and not validated_data.get("recorded_by"):
            validated_data["recorded_by"] = request.user
        return super().create(validated_data)


class SeedTypeBalanceSerializer(serializers.ModelSerializer):
    seed_type_name = serializers.CharField(source="seed_type.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)

    class Meta:
        model = SeedTypeBalance
        fields = [
            "warehouse",
            "warehouse_name",
            "seed_type",
            "seed_type_name",
            "purity",
            "cleaned_kg",
            "rejects_kg",
            "updated_at",
        ]


class BinCardEntrySerializer(serializers.ModelSerializer):
    seed_type_name = serializers.CharField(source="seed_type.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    unloading_labor_total_etb = serializers.SerializerMethodField()

    class Meta:
        model = BinCardEntry
        fields = [
            "id",
            "seed_type",
            "seed_type_name",
            "warehouse",
            "warehouse_name",
            "raw_balance_kg",
            "cleaned_total_kg",
            "rejects_total_kg",
            "last_cleaned_at",
            "unloading_rate_etb_per_qtl",
            "unloading_labor_total_etb",
        ]

    def get_unloading_labor_total_etb(self, obj):
        return obj.unloading_labor_total_etb


class StockOutSerializer(serializers.Serializer):
    """Validate stock-out requests.

    Accepts both legacy ``class`` and new ``stock_class`` keys and works for
    JSON or form submissions.
    """

    seed_type = serializers.CharField()
    stock_class = serializers.ChoiceField(choices=("cleaned", "reject", "raw"))
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    owner = serializers.UUIDField()
    warehouse = serializers.UUIDField()
    loading_rate_etb_per_qtl = serializers.DecimalField(
        max_digits=12, decimal_places=4, required=False, allow_null=True
    )
    num_bags = serializers.IntegerField(required=False, allow_null=True)
    car_plate_number = serializers.CharField(allow_blank=True, required=False)
    warehouse_document_number = serializers.CharField(
        allow_blank=True, required=False
    )
    # Optional for validation endpoint; required at submit time in view logic
    weighbridge_certificate = serializers.FileField(required=False)
    warehouse_document = serializers.FileField(required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    # Optional idempotency key to deduplicate rapid duplicate submissions
    idempotency_key = serializers.CharField(required=False, allow_blank=True)

    def to_internal_value(self, data):
        # Allow legacy clients to send ``class`` instead of ``stock_class``.
        if "class" in data and "stock_class" not in data:
            data = {**data, "stock_class": data["class"]}
        return super().to_internal_value(data)
