# models.py

import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.db import models, transaction
try:
    from django.db.models import JSONField
except Exception:
    from django.contrib.postgres.fields import JSONField
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.crypto import get_random_string

TOLERANCE_SHRINKAGE = Decimal("0.01")
TOLERANCE_BALANCE = Decimal("0.0025")
# Allow minor differences when grouping by purity
PURITY_TOLERANCE = Decimal("2.0")


def _dec(x):
    """Ensure Decimal conversion with string for precision."""
    return Decimal(str(x)) if x is not None else None


#
# ——————————————————————————————————————
# Core Lookups
# ——————————————————————————————————————
#
class Company(models.Model):
    """DGT, BestWay, ECX, or any third-party client."""
    id   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class SeedType(models.Model):
    """E.g. WHSS, WOLS, GMB, Niger, Soya, Chickpea…"""
    code = models.CharField(max_length=10, primary_key=True)
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} – {self.name}"


class SeedTypeDetail(models.Model):
    """Detailed ECX seed type information and handling procedures."""

    id = models.BigAutoField(primary_key=True)
    COFFEE = "COFFEE"
    SESAME = "SESAME"
    BEANS = "BEANS"
    OTHER = "OTHER"
    CATEGORY_CHOICES = [
        (COFFEE, "Coffee"),
        (SESAME, "Sesame"),
        (BEANS, "Beans"),
        (OTHER, "Other"),
    ]
    LOCAL_WASHED = "LOCAL_WASHED"
    LOCAL_UNWASHED = "LOCAL_UNWASHED"
    EXPORT_COMMERCIAL_UNWASHED = "EXPORT_COMMERCIAL_UNWASHED"
    EXPORT_SPECIALTY_UNWASHED = "EXPORT_SPECIALTY_UNWASHED"
    EXPORT_COMMERCIAL_WASHED = "EXPORT_COMMERCIAL_WASHED"
    EXPORT_SPECIALTY_WASHED = "EXPORT_SPECIALTY_WASHED"
    COFFEE_TYPE_CHOICES = [
        (LOCAL_WASHED, "Local Washed"),
        (LOCAL_UNWASHED, "Local Unwashed"),
        (EXPORT_COMMERCIAL_UNWASHED, "Export Commercial Unwashed"),
        (EXPORT_SPECIALTY_UNWASHED, "Export Specialty Unwashed"),
        (EXPORT_COMMERCIAL_WASHED, "Export Commercial Washed"),
        (EXPORT_SPECIALTY_WASHED, "Export Specialty Washed"),
    ]
    category = models.CharField(
        max_length=10,
        choices=CATEGORY_CHOICES,
        default=SESAME,
        help_text="Commodity category",
    )
    coffee_type = models.CharField(
        max_length=30,
        choices=COFFEE_TYPE_CHOICES,
        blank=True,
        null=True,
        help_text="Coffee grouping tag",
    )
    symbol = models.CharField(max_length=10)
    name = models.CharField(max_length=100)
    delivery_location = models.ForeignKey(
        "Warehouse",
        on_delete=models.PROTECT,
        related_name="seed_type_details",
    )
    grade = models.CharField(max_length=20)
    origin = models.TextField()
    handling_procedure = models.TextField(blank=True)

    class Meta:
        ordering = ["symbol"]
        unique_together = ("symbol", "delivery_location")

    def __str__(self):
        return f"{self.symbol} – {self.name}"

    def grade_for_purity(self, purity):
        """Return grade name based on achieved purity."""
        purity = _dec(purity) or Decimal("0")
        param = (
            self.grading_parameters
            .filter(min_purity__lte=purity)
            .order_by("-min_purity")
            .first()
        )
        if param and param.max_purity and purity > param.max_purity:
            return None
        return param.grade if param else None


class SeedGradeParameter(models.Model):
    """Grading thresholds for a seed type based on purity."""

    seed_type = models.ForeignKey(
        SeedTypeDetail,
        on_delete=models.CASCADE,
        related_name="grading_parameters",
    )
    grade = models.CharField(max_length=20)
    min_purity = models.DecimalField("Min purity (%)", max_digits=5, decimal_places=2)
    max_purity = models.DecimalField(
        "Max purity (%)", max_digits=5, decimal_places=2, null=True, blank=True
    )

    class Meta:
        ordering = ["seed_type", "-min_purity"]
        unique_together = ("seed_type", "grade")

    def __str__(self):
        return f"{self.seed_type.symbol} grade {self.grade} ≥{self.min_purity}%"


class Warehouse(models.Model):
    """DGT or ECX warehouse with geolocation."""
    DGT = "DGT"
    ECX = "ECX"
    TYPE_CHOICES = [
        (DGT, "DGT"),
        (ECX, "ECX"),
    ]

    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code           = models.CharField(max_length=50, unique=True)
    name           = models.CharField(max_length=100)
    description    = models.TextField(blank=True)
    warehouse_type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    owner          = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="warehouses",
    )
    capacity_quintals = models.DecimalField(max_digits=12, decimal_places=2)
    footprint_m2      = models.DecimalField(max_digits=12, decimal_places=2,
                                            null=True, blank=True)
    zone_geojson      = models.JSONField(null=True, blank=True)
    latitude          = models.DecimalField(max_digits=9, decimal_places=6)
    longitude         = models.DecimalField(max_digits=9, decimal_places=6)

    class Meta:
        ordering = ["warehouse_type", "code"]

    def __str__(self):
        return f"{self.code} ({self.get_warehouse_type_display()})"


#
# ——————————————————————————————————————
# Users & Roles
# ——————————————————————————————————————
#
class UserProfile(models.Model):
    """Extend Django’s User with a role for permissions."""
    WAREHOUSE_OFFICER   = "WAREHOUSE_OFFICER"
    ECX_OFFICER         = "ECX_OFFICER"
    ECX_AGENT           = "ECX_AGENT"
    WEIGHBRIDGE_OPERATOR = "WEIGHBRIDGE_OPERATOR"
    OPERATIONS_MANAGER  = "OPERATIONS_MANAGER"
    ADMIN               = "ADMIN"
    ACCOUNTANT          = "ACCOUNTANT"
    ROLE_CHOICES = [
        (WAREHOUSE_OFFICER,  "Warehouse Officer"),
        (ECX_OFFICER,        "ECX Officer"),
        (ECX_AGENT,         "ECX Agent"),
        (WEIGHBRIDGE_OPERATOR, "Weighbridge Operator"),
        (OPERATIONS_MANAGER, "Logistics Manager"),
        (ADMIN,              "System Manager"),
        (ACCOUNTANT,         "Accountant"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    timezone = models.CharField(max_length=50, default='UTC')
    preferences = models.JSONField(default=dict, blank=True)
    warehouses = models.ManyToManyField(
        'Warehouse',
        blank=True,
        related_name='assigned_users',
        limit_choices_to={"warehouse_type": "ECX"},
    )

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


#
# ----------------------------------------------------------------------
# ECX Trading Models
# ----------------------------------------------------------------------
#
class Commodity(models.Model):
    """Item traded on the ECX, defined by type, origin and grade."""
    seed_type = models.ForeignKey(SeedType, on_delete=models.PROTECT)
    origin = models.CharField(max_length=255)
    grade = models.CharField(max_length=50)

    class Meta:
        unique_together = ("seed_type", "origin", "grade")
        ordering = ["seed_type", "origin", "grade"]

    def __str__(self):
        return f"{self.seed_type.code}-{self.origin}-{self.grade}"


class PurchasedItemType(models.Model):
    """Item type purchased via ECX for inbound movements."""

    seed_type = models.CharField(max_length=50)
    origin = models.CharField(max_length=255)
    grade = models.CharField(max_length=50)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ("seed_type", "origin", "grade")
        ordering = ["seed_type", "origin", "grade"]

    @property
    def code(self) -> str:
        return f"{self.seed_type}-{self.origin}-{self.grade}"

    def __str__(self):
        return self.code


class EcxTrade(models.Model):
    """Record of a purchase executed on the ECX trading floor."""

    warehouse = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.ECX},
        on_delete=models.PROTECT,
        related_name="ecx_trades",
    )
    commodity = models.ForeignKey(Commodity, on_delete=models.PROTECT)
    net_obligation_receipt_no = models.CharField(max_length=100)
    warehouse_receipt_no = models.CharField(max_length=100)
    warehouse_receipt_version = models.PositiveIntegerField(default=1)
    quantity_quintals = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_date = models.DateField(default=timezone.now)
    loaded = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_ecx_trades",
    )
    owner = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="owned_ecx_trades",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-purchase_date", "commodity"]
        unique_together = ("warehouse_receipt_no", "warehouse_receipt_version")

    def __str__(self):
        return f"{self.commodity} @ {self.warehouse} ({self.quantity_quintals} qtls)"

    @property
    def last_pickup_date(self):
        """Calculated deadline for collecting purchased commodity."""
        return self.purchase_date + timedelta(days=5)

    @property
    def is_overdue(self) -> bool:
        """Return True if the trade has not been loaded and the pickup deadline has passed."""
        from django.utils import timezone
        return (not self.loaded) and (self.last_pickup_date < timezone.localdate())


class EcxTradeReceiptFile(models.Model):
    """Files (image or PDF) associated with an ECX trade's receipts."""

    trade = models.ForeignKey(
        EcxTrade,
        on_delete=models.CASCADE,
        related_name="receipt_files",
    )
    file = models.FileField(upload_to="ecx_receipts/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Receipt for {self.trade.net_obligation_receipt_no}"


# ----------------------------------------------------------------------
# ECX Trade Approval Requests (pending until Accountant approves)
# ----------------------------------------------------------------------
class EcxTradeRequest(models.Model):
    """A pending request to register one or more ECX trades.

    Stores the batch context (NOR, symbol/grade, etc.) and the per-receipt
    lines as JSON until an Accountant approves. On approval, concrete
    EcxTrade rows are created from this request.
    """

    STATUS_PENDING  = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_DECLINED = "DECLINED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DECLINED, "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_ecx_trade_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    owner = models.ForeignKey(Company, on_delete=models.PROTECT, null=True, blank=True)
    category = models.CharField(max_length=30, blank=True)
    symbol = models.CharField(max_length=10)
    grade = models.CharField(max_length=20)
    warehouse = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.ECX},
        on_delete=models.PROTECT,
        related_name="ecx_trade_requests",
    )
    net_obligation_receipt_no = models.CharField(max_length=100)
    purchase_date = models.DateField(default=timezone.now)
    # Example: [{"warehouse_receipt_no": "WR123", "quantity": "10.5"}, ...]
    receipt_lines = models.JSONField(default=list)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_ecx_trade_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    # Token to embed in the approval email link for quick verify
    approval_token = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ECX Trade Request {self.net_obligation_receipt_no} ({self.symbol}-{self.grade})"

    @property
    def total_quantity(self):
        """Total quantity across all receipt lines as Decimal or 0."""
        try:
            from decimal import Decimal
            return sum(Decimal(str(l.get("quantity") or 0)) for l in (self.receipt_lines or []))
        except Exception:
            return 0

    @property
    def warehouses_display(self):
        """Comma separated list of warehouses referenced by receipt lines.

        Falls back to the request's top-level warehouse if lines don't carry
        a specific warehouse id.
        """
        ids = []
        for l in (self.receipt_lines or []):
            wid = l.get("warehouse")
            if wid and str(wid) not in ids:
                ids.append(str(wid))
        if not ids and self.warehouse_id:
            ids = [str(self.warehouse_id)]
        if not ids:
            return ""
        names = list(
            Warehouse.objects.filter(id__in=ids).values_list("name", flat=True)
        )
        return ", ".join(sorted(names))


class EcxTradeRequestFile(models.Model):
    request = models.ForeignKey(
        EcxTradeRequest,
        on_delete=models.CASCADE,
        related_name="files",
    )
    file = models.FileField(upload_to="ecx_trade_requests/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"File for request {self.request_id}"


# ----------------------------------------------------------------------
# Contract Movement Accountant Approval Requests
# ----------------------------------------------------------------------


def generate_cmr_token():
    return get_random_string(48)


class ContractMovementRequest(models.Model):
    """Pending contract movement awaiting Accountant approval."""

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("DECLINED", "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_contract_movement_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    approval_token = models.CharField(
        max_length=64, db_index=True, unique=True, default=generate_cmr_token
    )

    owner = models.ForeignKey(Company, on_delete=models.PROTECT, null=True, blank=True)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True)
    direction = models.CharField(max_length=8, choices=[("IN", "IN"), ("OUT", "OUT")], default="IN")
    payload = JSONField()
    dispatch_image = models.FileField(upload_to="contract_dispatch/%Y/%m/%d/", blank=True)

    decision_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_contract_movement_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


# ----------------------------------------------------------------------
# Contract Farming Movements (non-ECX)
# ----------------------------------------------------------------------
class ContractMovement(models.Model):
    """Logistics-registered contract farming stock records while in movement.

    These entries represent dispatched stocks not purchased from ECX. They are
    later selected by the Warehouse Officer during bin card registration.
    """

    IN_TRANSIT = "IN_TRANSIT"
    CONSUMED = "CONSUMED"
    STATUS_CHOICES = [
        (IN_TRANSIT, "In Transit"),
        (CONSUMED, "Consumed"),
    ]

    id = models.AutoField(primary_key=True)
    owner = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="contract_movements",
        null=True,
        blank=True,
        help_text="Owning company (defaults to DGT if omitted)",
    )
    category = models.CharField(max_length=10, choices=SeedTypeDetail.CATEGORY_CHOICES)
    symbol = models.CharField(max_length=10, help_text="Seed symbol (e.g., WHSS, WOLS)")
    origin = models.CharField(max_length=255, blank=True)
    agent_name = models.CharField(max_length=100, blank=True)
    agent_phone = models.CharField(max_length=50, blank=True)
    advice_number = models.CharField(max_length=100, blank=True)
    dispatch_number = models.CharField(max_length=100)
    dispatch_image = models.FileField(
        upload_to="contract_dispatch/%Y/%m/%d/",
        blank=True,
    )
    quantity_quintals = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Registered load quantity (qtls)"
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=IN_TRANSIT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_contract_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)
    consumed_by = models.ForeignKey(
        'BinCardEntry', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='consumed_contract_movements'
    )

    class Meta:
        ordering = ["-created_at", "symbol"]
        indexes = [
            models.Index(fields=["status", "symbol"]),
            models.Index(fields=["dispatch_number"]),
        ]

    def __str__(self):
        base = f"{self.symbol} {self.dispatch_number}"
        if self.origin:
            base += f" – {self.origin}"
        return base

    @property
    def is_available(self) -> bool:
        return self.status == self.IN_TRANSIT and self.consumed_by_id is None


#
# ——————————————————————————————————————
# Purchasing & Stock Movements
# ——————————————————————————————————————
#
class PurchaseOrder(models.Model):
    """
    ECX purchases (seed_type) → company_warehouse,
    with a 5-day pickup deadline.
    """
    id                 = models.AutoField(primary_key=True)
    ecx_warehouse      = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.ECX},
        on_delete=models.PROTECT,
        related_name="outgoing_purchases"
    )
    company_warehouse  = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.DGT},
        on_delete=models.PROTECT,
        related_name="incoming_purchases"
    )
    seed_type          = models.ForeignKey(SeedType, on_delete=models.PROTECT)
    purchaser          = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="purchases")
    quantity_quintals  = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_date      = models.DateField(default=timezone.now)
    pickup_deadline    = models.DateField(editable=False)
    status             = models.CharField(max_length=20, default="PENDING")

    class Meta:
        ordering = ["-purchase_date", "seed_type"]

    def save(self, *args, **kwargs):
        if not self.pickup_deadline:
            self.pickup_deadline = self.purchase_date + timedelta(days=5)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"PO#{self.id}: {self.quantity_quintals} {self.seed_type.code}"


class StockMovement(models.Model):
    """
    Records every inbound or outbound movement via the third-party weighbridge.
    """
    INBOUND  = "IN"
    OUTBOUND = "OUT"
    MOVE_CHOICES = [(INBOUND, "Inbound"), (OUTBOUND, "Outbound")]

    id             = models.AutoField(primary_key=True)
    movement_type  = models.CharField(max_length=3, choices=MOVE_CHOICES)
    ticket_no      = models.CharField(max_length=50, unique=True)
    ticket_date    = models.DateField()
    enter_time     = models.DateTimeField()
    exit_time      = models.DateTimeField()
    plate_no       = models.CharField(max_length=20)
    supplier       = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="supplied_movements")
    receiver       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_movements"
    )
    warehouse      = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements")
    seed_type      = models.ForeignKey(SeedType, on_delete=models.PROTECT)
    owner          = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="stock_movements")
    gross_weight   = models.DecimalField(max_digits=12, decimal_places=2)
    tare_weight    = models.DecimalField(max_digits=12, decimal_places=2)
    net_weight     = models.DecimalField(max_digits=12, decimal_places=2)
    num_bags       = models.IntegerField()
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements"
    )

    class Meta:
        unique_together = ("movement_type", "ticket_no")
        ordering        = ["-ticket_date"]

    def __str__(self):
        return f"{self.get_movement_type_display()} #{self.ticket_no} ({self.net_weight} qtls)"


class WeighbridgeSlipImage(models.Model):
    """
    Stores scanned/photographed images of the
    third-party weighbridge slip for each StockMovement.
    """
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    movement    = models.ForeignKey(
        StockMovement,
        on_delete=models.CASCADE,
        related_name="slip_images"
    )
    image       = models.ImageField(
        upload_to="weighbridge_slips/%Y/%m/%d/",
        help_text="Scan or photo of the weighbridge slip"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_slip_images"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional note (e.g. 'inbound slip', 'outbound slip')"
    )

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "Weighbridge Slip Image"
        verbose_name_plural = "Weighbridge Slip Images"

    def __str__(self):
        return f"SlipImage {self.id} for {self.movement.ticket_no}"


class EcxMovement(models.Model):
    """Registration of ECX purchase movements."""

    warehouse = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.ECX},
        on_delete=models.PROTECT,
        related_name="ecx_movements",
    )
    item_type = models.ForeignKey(PurchasedItemType, on_delete=models.PROTECT)
    net_obligation_receipt_no = models.CharField(max_length=100)
    warehouse_receipt_no = models.CharField(max_length=100)
    quantity_quintals = models.DecimalField(max_digits=12, decimal_places=2)
    purchase_date = models.DateField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_ecx_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="owned_ecx_movements",
        null=True,
        blank=True,
    )
    # Optional parent truck/shipment to group per-grade movements
    shipment = models.ForeignKey(
        'EcxShipment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movements'
    )
    weighbridge_certificate = models.FileField(
        upload_to="ecx_movements/weighbridge/%Y/%m/%d/",
        blank=True,
    )
    weighed = models.BooleanField(default=False)
    weighed_at = models.DateTimeField(null=True, blank=True)
    loaded = models.BooleanField(default=False)
    loaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-purchase_date", "warehouse"]

    def __str__(self):
        return f"{self.item_type.code} @ {self.warehouse} ({self.quantity_quintals} qtls)"


class EcxMovementReceiptFile(models.Model):
    movement = models.ForeignKey(
        EcxMovement,
        on_delete=models.CASCADE,
        related_name="receipt_files",
    )
    # Accept both images and PDFs (the UI allows application/pdf)
    # Using FileField avoids server errors when non-image files are uploaded.
    image = models.FileField(upload_to="ecx_movement_receipts/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Receipt for {self.movement.net_obligation_receipt_no}"


class EcxShipment(models.Model):
    """A truck/shipment grouping one or more ECX movements (often mixed grades)."""

    id = models.AutoField(primary_key=True)
    warehouse = models.ForeignKey(
        Warehouse,
        limit_choices_to={"warehouse_type": Warehouse.ECX},
        on_delete=models.PROTECT,
        related_name="ecx_shipments",
    )
    symbol = models.CharField(
        max_length=10,
        help_text="Seed symbol (e.g., WHGSS)",
        blank=True,
        null=True,
    )
    total_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    loading_date = models.DateTimeField(null=True, blank=True)
    # Trip-level vehicle details (common across mixed-grade loads)
    truck_plate_no = models.CharField(max_length=20, blank=True)
    trailer_plate_no = models.CharField(max_length=20, blank=True)
    truck_image = models.ImageField(upload_to="ecx/trucks/", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        symbol = f"{self.symbol} " if self.symbol else ""
        return (
            f"Shipment {self.id} – {symbol}@ {self.warehouse}"
            f" ({self.total_quantity} qtls)"
        )


#
# ----------------------------------------------------------------------
# ECX Load / Dispatch Records
# ----------------------------------------------------------------------
#
class EcxLoad(models.Model):
    """Record the dispatch/loading of ECX trades to company warehouses."""

    tracking_no = models.CharField(max_length=50)
    voucher_no = models.CharField(max_length=50)
    voucher_weight = models.DecimalField(max_digits=12, decimal_places=2)
    commodity_type = models.ForeignKey(SeedType, on_delete=models.PROTECT)
    gross_weight = models.DecimalField(max_digits=12, decimal_places=2)
    net_weight = models.DecimalField(max_digits=12, decimal_places=2)
    truck_plate_no = models.CharField(max_length=20)
    trailer_plate_no = models.CharField(max_length=20)
    no_of_plomps = models.IntegerField()
    trailer_no_of_plomps = models.IntegerField()
    scale_ticket_no = models.CharField(max_length=50)
    driver_name = models.CharField(max_length=100)
    driver_license_no = models.CharField(max_length=50)
    driver_license_image = models.ImageField(upload_to="driver_licenses/%Y/%m/%d/")
    no_of_bags = models.IntegerField()
    production_year = models.IntegerField()
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    region = models.CharField(max_length=100)
    zone = models.CharField(max_length=100)
    woreda = models.CharField(max_length=100)
    specific_area = models.CharField(max_length=100)
    date_received = models.DateField()
    supervisor_name = models.CharField(max_length=100)
    supervisor_signed_date = models.DateField()
    client_name = models.CharField(max_length=100)
    client_signed_date = models.DateField()
    dispatch_document = models.FileField(upload_to="dispatch_docs/%Y/%m/%d/")
    weight_certificate = models.FileField(upload_to="weight_certificates/%Y/%m/%d/")
    trades = models.ManyToManyField(EcxTrade, related_name="loads")

    class Meta:
        ordering = ["-date_received", "warehouse"]

    def __str__(self):
        return f"Load {self.tracking_no} ({self.warehouse})"


class EcxLoadRequest(models.Model):
    """A pending request to mark ECX trades as loaded."""

    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_DECLINED = "DECLINED"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DECLINED, "Declined"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_ecx_load_requests",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="ecx_load_requests",
    )
    trades = models.ManyToManyField(EcxTrade, related_name="load_requests")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_ecx_load_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    approval_token = models.CharField(max_length=64, unique=True)
    payload = JSONField(default=dict, blank=True)
    shipment = models.ForeignKey(
        'EcxShipment',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='load_requests'
    )
    plombs_count = models.PositiveIntegerField(default=0)
    has_trailer = models.BooleanField(default=False)
    trailer_count = models.PositiveIntegerField(default=0)
    truck_image = models.ImageField(upload_to="ecx/trucks/", null=True, blank=True)
    # Added to capture vehicle identity for the trip
    truck_plate_no = models.CharField(max_length=20, blank=True)
    trailer_plate_no = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ECX Load Request {self.id}"


class EcxLoadRequestReceiptFile(models.Model):
    """Optional receipt images attached to an ECX load request by grade."""

    request = models.ForeignKey(
        EcxLoadRequest,
        on_delete=models.CASCADE,
        related_name="receipt_files",
    )
    origin = models.CharField(max_length=100)
    grade = models.CharField(max_length=20)
    file = models.FileField(upload_to="ecx_load_request_receipts/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"Receipt for {self.origin} / {self.grade}"


class BinCardEntryRequest(models.Model):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    STATUS_CHOICES = [(PENDING, "Pending"), (APPROVED, "Approved"), (DECLINED, "Declined")]
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="bcr_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    approval_token = models.CharField(max_length=64, unique=True)
    reason = models.TextField(null=True, blank=True)
    payload = JSONField()
    warehouse = models.ForeignKey("Warehouse", on_delete=models.PROTECT, null=True, blank=True)
    direction = models.CharField(max_length=8, choices=[("IN", "IN"), ("OUT", "OUT")])
    warehouse_document = models.FileField(
        upload_to="bincard/warehouse_docs/%Y/%m/%d/", blank=True
    )
    weighbridge_certificate = models.FileField(
        upload_to="bincard/weighbridge/%Y/%m/%d/", blank=True
    )
    quality_form = models.FileField(
        upload_to="bincard/quality_forms/%Y/%m/%d/", blank=True
    )
    pdf_file = models.FileField(
        upload_to="bincard_drafts/%Y/%m/%d/",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("-created_at",)


#
# Stock-out request approval flow for API-driven stock deductions
#
class StockOutRequest(models.Model):
    PENDING = "PENDING"
    PENDING_SM = "PENDING_SM"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    RETURNED = "RETURNED"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (PENDING_SM, "Pending – System Manager"),
        (APPROVED, "Approved"),
        (DECLINED, "Declined"),
        (RETURNED, "Returned"),
    ]

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="stockout_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    approval_token = models.CharField(max_length=64, unique=True)
    reason = models.TextField(null=True, blank=True)
    payload = JSONField()
    warehouse = models.ForeignKey("Warehouse", on_delete=models.PROTECT)
    owner = models.ForeignKey("Company", on_delete=models.PROTECT, null=True, blank=True)
    warehouse_document = models.FileField(
        upload_to="stockout/warehouse_docs/%Y/%m/%d/", blank=True
    )
    weighbridge_certificate = models.FileField(
        upload_to="stockout/weighbridge/%Y/%m/%d/", blank=True
    )
    pdf_file = models.FileField(
        upload_to="stockout_requests/%Y/%m/%d/",
        null=True,
        blank=True,
    )
    # Optional idempotency key to prevent duplicate pending requests from rapid resubmits
    idempotency_key = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        unique=True,
        help_text="Client-supplied key to deduplicate submissions",
    )
    # Exceptional loan-out flow
    is_borrow = models.BooleanField(default=False, help_text="If true, this outflow is a temporary loan to another company.")
    borrower = models.ForeignKey(
        "Company", on_delete=models.PROTECT, null=True, blank=True, related_name="stock_loans"
    )
    borrower_name = models.CharField(max_length=120, blank=True, null=True)
    lm_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="stockout_lm_approvals"
    )
    lm_approved_at = models.DateTimeField(null=True, blank=True)
    sm_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="stockout_sm_approvals"
    )
    sm_approved_at = models.DateTimeField(null=True, blank=True)
    borrowed_outstanding_kg = models.DecimalField(max_digits=14, decimal_places=3, default=Decimal("0.000"))

    class Meta:
        ordering = ("-created_at",)


#
# ——————————————————————————————————————
# Quality & Quantity Analysis
# ——————————————————————————————————————
#
class QualityAnalysis(models.Model):
    """
    When a load arrives, sample for purity & foreign matter.
    """
    id                    = models.AutoField(primary_key=True)
    movement              = models.OneToOneField(StockMovement, on_delete=models.CASCADE)
    first_sound_weight    = models.DecimalField(max_digits=10, decimal_places=2)
    first_foreign_weight  = models.DecimalField(max_digits=10, decimal_places=2)
    first_purity_percent  = models.DecimalField(max_digits=5, decimal_places=2)
    second_test_datetime  = models.DateTimeField()
    second_sound_weight   = models.DecimalField(max_digits=10, decimal_places=2)
    second_foreign_weight = models.DecimalField(max_digits=10, decimal_places=2)
    total_bags            = models.IntegerField()
    sampled_bags          = models.IntegerField()
    second_purity_percent = models.DecimalField(max_digits=5, decimal_places=2)
    comment               = models.TextField(blank=True)

    def __str__(self):
        return f"QC for {self.movement.ticket_no} → {self.first_purity_percent}%"


#
# ——————————————————————————————————————
# Daily Processing & Follow-Up
# ——————————————————————————————————————
#


#
# ——————————————————————————————————————
# Bin-Card & Labor
# ——————————————————————————————————————
#
class BinCard(models.Model):
    """Unique bin card per owner and commodity."""

    owner = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="bin_cards")
    commodity = models.ForeignKey(
        Commodity, on_delete=models.CASCADE, related_name="bin_cards"
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="bin_cards",
        limit_choices_to={"warehouse_type": "DGT"},
    )

    class Meta:
        unique_together = ("owner", "commodity", "warehouse")

    def __str__(self):
        return f"{self.owner} – {self.commodity} @ {self.warehouse}"


class BinCardTransaction(models.Model):
    """Immutable ledger transaction tied to a specific lot."""

    RAW_OUT = "RAW_OUT"
    CLEANED_IN = "CLEANED_IN"
    REJECT_OUT = "REJECT_OUT"
    CLEANED_OUT = "CLEANED_OUT"
    MOVEMENT_CHOICES = [
        (RAW_OUT, "Raw Out"),
        (CLEANED_IN, "Cleaned In"),
        (REJECT_OUT, "Reject Out"),
        (CLEANED_OUT, "Cleaned Out"),
    ]

    ts = models.DateTimeField(auto_now_add=True)
    commodity = models.ForeignKey(SeedTypeDetail, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, null=True, blank=True)
    lot = models.ForeignKey(
        'BinCardEntry', on_delete=models.CASCADE, related_name='transactions'
    )
    daily_record = models.ForeignKey(
        'DailyRecord', on_delete=models.CASCADE, null=True, blank=True,
        related_name='transactions'
    )
    movement = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    qty_kg = models.DecimalField(max_digits=12, decimal_places=3)
    grade_before = models.CharField(max_length=50, null=True, blank=True)
    grade_after = models.CharField(max_length=50, null=True, blank=True)
    note = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["lot", "ts"]),
            models.Index(fields=["commodity", "warehouse", "ts"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["daily_record", "movement"],
                name="uniq_daily_record_movement",
                condition=models.Q(daily_record__isnull=False),
            ),
        ]
        ordering = ["ts", "id"]

    def __str__(self):
        return f"{self.movement} {self.qty_kg}kg on lot {self.lot_id}"


class BinCardEntry(models.Model):
    """
    Per-item perpetual inventory ledger.
    """
    id        = models.AutoField(primary_key=True)
    seed_type = models.ForeignKey(
        SeedTypeDetail,
        on_delete=models.PROTECT,
    )
    grade     = models.CharField(max_length=50, blank=True)
    owner     = models.ForeignKey(Company, on_delete=models.PROTECT)
    date      = models.DateField(auto_now_add=True)
    in_out_no = models.CharField(
        max_length=50,
        blank=True,
        validators=[RegexValidator(r"^\d+$", "In/out number must be numeric")],
    )
    description = models.CharField(max_length=255, blank=True)
    weight      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    remark      = models.CharField(max_length=255, blank=True)
    cleaned_weight = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Total weight cleaned from this lot",
    )
    raw_weight_remaining = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="Raw weight remaining to be processed",
    )

    raw_balance_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Raw balance (quintals)",
    )
    cleaned_total_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Total cleaned stock (quintals)",
    )
    rejects_total_kg = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Total reject stock (quintals)",
    )
    last_cleaned_at  = models.DateTimeField(null=True, blank=True)
    initial_stock_balance_type_qtl  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    initial_stock_balance_grade_qtl = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    ECX = "ECX"
    CONTRACT = "CONTRACT"
    LOCAL = "LOCAL"
    SOURCE_CHOICES = [
        (ECX, "ECX"),
        (CONTRACT, "Contract Farming"),
        (LOCAL, "Local Purchase"),
    ]
    source_type = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=CONTRACT
    )
    warehouse = models.ForeignKey(
        "Warehouse",
        on_delete=models.PROTECT,
        related_name="bin_card_entries",
        limit_choices_to={"warehouse_type": "DGT"},
    )
    ecx_movement = models.ForeignKey(
        "EcxMovement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bin_card_entries",
    )
    num_bags = models.IntegerField(default=0)
    car_plate_number = models.CharField(max_length=20, blank=True)
    warehouse_document_number = models.CharField(max_length=50, blank=True)
    purity = models.DecimalField("Purity (%)", max_digits=5, decimal_places=2, default=0)
    unloading_rate_etb_per_qtl = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Labor cost per quintal (ETB) for unloading",
    )
    loading_rate_etb_per_qtl = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Labor cost per quintal (ETB) for loading",
    )
    weighbridge_certificate = models.FileField(
        upload_to="bincard/weighbridge/%Y/%m/%d/",
        blank=True,
    )
    warehouse_document = models.FileField(
        upload_to="bincard/warehouse_docs/%Y/%m/%d/",
        blank=True,
    )
    quality_form = models.FileField(
        upload_to="bincard/quality_forms/%Y/%m/%d/",
        blank=True,
    )
    pdf_file = models.FileField(
        upload_to="bincard/pdfs/%Y/%m/%d/",
        blank=True,
        editable=False,
    )
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    pdf_dirty = models.BooleanField(default=False)
    pdf_fingerprint = models.CharField(max_length=64, blank=True)

    # Tracking scope: full for DGT-owned, limited for third-party owners
    FULL = "FULL"
    LIMITED = "LIMITED"
    TRACKING_SCOPE_CHOICES = [
        (FULL, "Full"),
        (LIMITED, "Limited"),
    ]
    tracking_scope = models.CharField(
        max_length=10, choices=TRACKING_SCOPE_CHOICES, default=FULL
    )

    # Third-party specific references and rates
    pl_no = models.CharField(max_length=50, blank=True)
    r_no = models.CharField(max_length=50, blank=True)
    service_rate_etb_per_qtl = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    storage_rate_etb_per_day = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    storage_days = models.IntegerField(null=True, blank=True)
    storage_fee_etb = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )

    class Meta:
        unique_together = ("seed_type", "owner", "warehouse", "in_out_no")
        ordering        = ["seed_type", "date"]

    def save(self, *args, **kwargs):
        if not self.in_out_no or not self.in_out_no.isdigit():
            # Number lots sequentially per seed type, owner, and warehouse so
            # stock-in and stock-out entries share one sequence for each owner.
            self.in_out_no = next_in_out_no(
                self.seed_type, owner=self.owner, warehouse=self.warehouse
            )
        if not self.grade and self.ecx_movement:
            self.grade = self.ecx_movement.item_type.grade
        if self.pk is None:
            # Determine last balance across the seed symbol (not strictly the
            # exact SeedTypeDetail row). Historically, multiple SeedTypeDetail
            # records share the same symbol; using the symbol keeps the running
            # balance consistent and prevents cross-id aggregation anomalies.
            last = (
                BinCardEntry.objects.filter(
                    seed_type__symbol=getattr(self.seed_type, "symbol", None),
                    owner=self.owner,
                    warehouse=self.warehouse,
                )
                .order_by("-id")
                .first()
            )
            last_balance = last.balance if last else Decimal("0")
            self.balance = last_balance + self.weight
            # Initialise raw balances only for true raw stock-in rows.
            # A "true raw stock-in" is defined as a positive weight entry
            # where cleaned/reject deltas are both zero. This avoids treating
            # borrow returns of cleaned/reject as raw availability.
            def _is_true_raw_in(entry):
                try:
                    w = Decimal(entry.weight)
                except Exception:
                    w = Decimal("0")
                try:
                    c = Decimal(entry.cleaned_total_kg or 0)
                except Exception:
                    c = Decimal("0")
                try:
                    r = Decimal(entry.rejects_total_kg or 0)
                except Exception:
                    r = Decimal("0")
                return (w > 0) and (c == 0) and (r == 0)

            if _is_true_raw_in(self):
                if self.raw_weight_remaining == 0:
                    try:
                        w = Decimal(self.weight)
                    except Exception:
                        w = Decimal("0")
                    self.raw_weight_remaining = w if w > 0 else Decimal("0")
                if self.raw_balance_kg == 0:
                    try:
                        w = Decimal(self.weight)
                    except Exception:
                        w = Decimal("0")
                    self.raw_balance_kg = w if w > 0 else Decimal("0")
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.warehouse:
            raise ValidationError("Warehouse is required for all bin card entries.")
        if getattr(self.warehouse, "warehouse_type", None) != "DGT":
            raise ValidationError("Only DGT warehouses are allowed for bin card entries.")

    @property
    def unloading_labor_total_etb(self):
        if self.unloading_rate_etb_per_qtl is None or self.weight is None:
            return None
        return (
            Decimal(self.unloading_rate_etb_per_qtl) * Decimal(abs(self.weight))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def loading_labor_total_etb(self):
        if self.loading_rate_etb_per_qtl is None or self.weight is None:
            return None
        return (
            Decimal(self.loading_rate_etb_per_qtl) * Decimal(abs(self.weight))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"{self.seed_type} | {self.in_out_no} → {self.balance}"


def compute_balances_as_of_creation(entry):
    from .pdf_utils import compute_balances_as_of
    agg = compute_balances_as_of(entry, entry.grade, timezone.now())
    return agg["stock_type"], agg["stock_tg"]


@transaction.atomic
def finalize_entry_on_create(entry):
    t, g = compute_balances_as_of_creation(entry)
    entry.initial_stock_balance_type_qtl = t
    entry.initial_stock_balance_grade_qtl = g
    # Avoid triggering post-save signals twice by updating in place
    type(entry).objects.filter(pk=entry.pk).update(
        initial_stock_balance_type_qtl=t,
        initial_stock_balance_grade_qtl=g,
    )


class BinCardAttachment(models.Model):
    class Kind(models.TextChoices):
        ECX_RECEIPT = "ecx_receipt", "ECX receipt"
        WEIGHBRIDGE = "weighbridge", "Weighbridge"
        WAREHOUSE_DOC = "warehouse_doc", "Warehouse Doc"
        QUALITY_FORM = "quality_form", "Quality Form"

    entry = models.ForeignKey("BinCardEntry", related_name="attachments", on_delete=models.CASCADE)
    kind = models.CharField(max_length=32, choices=Kind.choices)
    file = models.FileField(upload_to="bincard/attachments/%Y/%m/%d/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["entry", "kind"])]


@receiver(post_save, sender=BinCardEntry)
def snapshot_initial_balances(sender, instance, created, **kwargs):
    """Snapshot balances on creation without retriggering signals."""
    if created:
        finalize_entry_on_create(instance)


@receiver(post_save, sender=BinCardEntry)
def remove_ecx_movement(sender, instance, created, **kwargs):
    """Attach ECX receipts then delete movement."""
    if created and instance.ecx_movement_id:
        from .services.bincard import link_ecx_receipts_and_delete_movement
        link_ecx_receipts_and_delete_movement(instance)


class CleanedStockOut(models.Model):
    seed_type = models.ForeignKey(SeedTypeDetail, on_delete=models.PROTECT)
    owner = models.ForeignKey(Company, on_delete=models.PROTECT, null=True, blank=True)
    warehouse = models.ForeignKey(
        "WareDGT.Warehouse",
        on_delete=models.PROTECT,
        limit_choices_to={"warehouse_type": "DGT"},
    )
    date = models.DateField(auto_now_add=True)
    in_out_no = models.CharField(
        max_length=50,
        blank=True,
        validators=[RegexValidator(r"^\d+$", "In/out number must be numeric")],
    )
    weight = models.DecimalField(max_digits=12, decimal_places=2)
    num_bags = models.IntegerField(default=0)
    car_plate_number = models.CharField(max_length=20, blank=True)
    warehouse_document_number = models.CharField(max_length=50, blank=True)
    weighbridge_certificate = models.FileField(
        upload_to="bincard/weighbridge/%Y/%m/%d/",
        blank=True,
    )
    warehouse_document = models.FileField(
        upload_to="bincard/warehouse_docs/%Y/%m/%d/",
        blank=True,
    )
    loading_rate_etb_per_qtl = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="Labor cost per quintal (ETB) for loading",
    )

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if not self.in_out_no or not self.in_out_no.isdigit():
            self.in_out_no = next_in_out_no(
                self.seed_type, owner=self.owner, warehouse=self.warehouse
            )
        super().save(*args, **kwargs)

    @property
    def loading_labor_total_etb(self):
        if self.loading_rate_etb_per_qtl is None or self.weight is None:
            return None
        return (
            Decimal(self.loading_rate_etb_per_qtl)
            * (Decimal(self.weight) / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def next_in_out_no(seed_type, owner=None, warehouse=None):
    from django.db.models import Max, IntegerField
    from django.db.models.functions import Cast

    symbol = getattr(seed_type, "symbol", seed_type)

    filters = {"seed_type__symbol": symbol}
    if owner is not None:
        filters["owner"] = owner
    if warehouse is not None:
        filters["warehouse"] = warehouse

    qs = (
        BinCardEntry.objects
        .filter(**filters)
        .filter(in_out_no__regex=r"^\d+$")  # count only numeric series
        .annotate(num=Cast("in_out_no", IntegerField()))
    )

    last_num = qs.aggregate(m=Max("num")).get("m") or 0
    return str(last_num + 1)


class SeedTypeBalance(models.Model):
    """Denormalized running totals per seed type and owner/purity."""

    warehouse = models.ForeignKey("WareDGT.Warehouse", on_delete=models.PROTECT)
    owner = models.ForeignKey("WareDGT.Company", on_delete=models.PROTECT, null=True, blank=True)
    seed_type = models.ForeignKey("WareDGT.SeedTypeDetail", on_delete=models.PROTECT)
    purity = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cleaned_kg = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Cleaned stock (quintals)",
    )
    rejects_kg = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Reject stock (quintals)",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("warehouse", "owner", "seed_type", "purity")]


class StockOut(models.Model):
    """Generic stock-out record reducing SeedTypeBalance."""

    CLEANED = "cleaned"
    REJECT = "reject"
    CLASS_CHOICES = [(CLEANED, "Cleaned"), (REJECT, "Reject")]

    seed_type = models.ForeignKey("WareDGT.SeedTypeDetail", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(
        "WareDGT.Warehouse",
        on_delete=models.PROTECT,
        limit_choices_to={"warehouse_type": "DGT"},
    )
    owner = models.ForeignKey("WareDGT.Company", on_delete=models.PROTECT, null=True, blank=True)
    stock_class = models.CharField(max_length=7, choices=CLASS_CHOICES)
    quantity_kg = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        help_text="Quantity in quintals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-created_at", "-id"]


class DailyRecord(models.Model):
    """Tracks warehouse operations on a given lot per day."""

    CLEANING = "CLEANING"
    RECLEANING = "RECLEANING"
    UNLOADING = "UNLOADING"
    LOADING = "LOADING"
    REJECT_WEIGHING = "REJECT_WEIGHING"
    RELOCATION = "RELOCATION"
    WEIGHBRIDGE = "WEIGHBRIDGE"
    OPERATION_CHOICES = [
        (CLEANING, "Cleaning"),
        (RECLEANING, "Re cleaning"),
        (UNLOADING, "Unloading"),
        (LOADING, "Loading"),
        (REJECT_WEIGHING, "Reject Weighing"),
        (RELOCATION, "Relocation"),
        (WEIGHBRIDGE, "Weighbridge Net"),
    ]

    STATUS_DRAFT = "DRAFT"
    STATUS_READY = "READY"
    STATUS_POSTED = "POSTED"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft / Awaiting reject weight"),
        (STATUS_READY, "Ready to post"),
        (STATUS_POSTED, "Posted"),
    ]

    id = models.BigAutoField(primary_key=True)
    date = models.DateField(default=timezone.now)
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="daily_records"
    )
    plant = models.CharField(max_length=100, blank=True)
    owner = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="processing_logs"
    )
    seed_type = models.ForeignKey(SeedTypeDetail, on_delete=models.PROTECT)
    lot = models.ForeignKey(
        BinCardEntry, on_delete=models.PROTECT, related_name="daily_records"
    )
    operation_type = models.CharField(
        max_length=20, choices=OPERATION_CHOICES, default=CLEANING
    )
    target_purity = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Desired final purity in %, e.g., 97.00/98.00/99.00/100.00.",
    )
    weight_in = models.DecimalField(max_digits=12, decimal_places=2)
    weight_out = models.DecimalField(max_digits=12, decimal_places=2)
    rejects = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    REJECT_WASTE = "WASTE"
    REJECT_FEED = "FEED"
    REJECT_REWORK = "REWORK"
    REJECT_DISPOSITION_CHOICES = [
        (REJECT_WASTE, "Waste"),
        (REJECT_FEED, "Feed"),
        (REJECT_REWORK, "Rework"),
    ]
    reject_disposition = models.CharField(
        max_length=10,
        choices=REJECT_DISPOSITION_CHOICES,
        default=REJECT_WASTE,
    )
    purity_before = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    purity_after = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    shrink_margin = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("100")
    )
    passes = models.SmallIntegerField(default=1)
    remarks = models.TextField(blank=True)
    cleaning_equipment = models.CharField(max_length=100, blank=True)
    chemicals_used = models.TextField(blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    laborers = models.PositiveIntegerField(default=0)
    labor_rate_per_qtl = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reject_labor_payment_per_qtl = models.DecimalField(
        max_digits=12, decimal_places=2, default=0
    )
    cleaning_labor_rate_etb_per_qtl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Labor cost per quintal (ETB) for cleaning",
    )
    reject_weighing_rate_etb_per_qtl = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Labor cost per quintal (ETB) for reject weighing",
    )
    labor_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, editable=False
    )
    pieces = models.PositiveIntegerField(default=0)
    workers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="daily_cleaning_workers",
    )
    recleaning_reason = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="daily_records"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_posted = models.BooleanField(default=False)
    posted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_daily_records",
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    actual_reject_weight = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Measured rejects weight (qtl/kg as per system unit).",
    )
    expected_reject_weight = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="System expected rejects based on purity/weight.",
    )
    combined_expected_reject_weight = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Weighted combo of purity-based and diff-based estimators.",
    )
    deviation_pct = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="|actual - expected_adj| / weight_in (in fraction, not %).",
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    is_fishy = models.BooleanField(default=False)
    reject_weighed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reject_weighings",
    )
    reject_weighed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-id"]
        permissions = [
            ("can_post_daily_record", "Can post daily record"),
            ("can_reverse_daily_record", "Can reverse posted daily record"),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.operation_type not in {self.CLEANING, self.RECLEANING}:
            # Do not force weight_out to mirror weight_in for non-cleaning ops.
            self.purity_after = self.purity_before
            self.rejects = Decimal("0")
        if self.operation_type == self.CLEANING:
            if self.target_purity is None:
                raise ValidationError({"target_purity": "This field is required."})
            if self.purity_before and self.target_purity < self.purity_before:
                raise ValidationError({"target_purity": "Must be >= purity_before"})
            if self.target_purity and self.target_purity > Decimal("100.00"):
                raise ValidationError({"target_purity": "Must be <= 100.00"})
        if self.operation_type == self.RECLEANING and not self.recleaning_reason:
            raise ValidationError({"recleaning_reason": "This field is required."})
        if (
            self.weight_in is None
            or self.weight_out is None
            or self.rejects is None
        ):
            errors = {}
            if self.weight_in is None:
                errors["weight_in"] = "This field is required."
            if self.weight_out is None:
                errors["weight_out"] = "This field is required."
            if self.rejects is None:
                errors["rejects"] = "This field is required."
            raise ValidationError(errors)
        if self.weight_in <= 0 or self.weight_out < 0 or self.rejects < 0:
            raise ValidationError("Weights must be non-negative and weight_in positive")
        if self.actual_reject_weight is not None:
            diff = abs(self.weight_in - (self.weight_out + self.rejects))
            tolerance = self.weight_in * TOLERANCE_BALANCE
            if diff > tolerance:
                raise ValidationError(
                    "weight_in must equal weight_out + rejects within 0.25%"
                )
        if self.lot_id and self.weight_in > self.lot.raw_weight_remaining:
            raise ValidationError("Cannot process more than remaining raw weight")
        if self.purity_after < self.purity_before:
            raise ValidationError("purity_after must be >= purity_before")

    def compute_estimations(self):
        """Compute expected reject weights and deviation."""
        if not self.weight_in or not self.purity_before:
            return

        weight_in = _dec(self.weight_in)
        purity_before = _dec(self.purity_before)
        target = _dec(self.target_purity) or _dec(self.purity_after) or purity_before
        purity_before = max(Decimal("0.00"), min(purity_before, Decimal("100.00")))
        target = max(Decimal("0.01"), min(target, Decimal("100.00")))

        ideal_frac = Decimal("1.0") - (purity_before / target)
        ideal_frac = max(Decimal("0.0"), ideal_frac)
        ideal_reject = (weight_in * ideal_frac).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

        loss_pct = _dec(getattr(settings, "DAILYREC_PROCESS_LOSS_PCT", 0.005))
        purity_expected = (ideal_reject + (weight_in * loss_pct)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )

        diff_based = None
        if self.weight_out:
            diff_based = (weight_in - _dec(self.weight_out)).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            diff_based = max(Decimal("0.000"), diff_based)

        alpha = _dec(getattr(settings, "DAILYREC_COMBINE_ALPHA", 0.90))
        if diff_based is not None:
            combined = (
                alpha * purity_expected + (Decimal("1.0") - alpha) * diff_based
            ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        else:
            combined = purity_expected

        self.expected_reject_weight = purity_expected
        self.combined_expected_reject_weight = combined

        if self.actual_reject_weight:
            actual = _dec(self.actual_reject_weight)
            tol = _dec(getattr(settings, "DAILYREC_TOLERANCE_PCT", 0.0075))
            deviation = (abs(actual - combined) / weight_in) if weight_in > 0 else Decimal("0.0")
            self.deviation_pct = deviation.quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            self.is_fishy = deviation > tol

    def save(self, *args, **kwargs):
        if (
            self.operation_type in {self.CLEANING, self.RECLEANING}
            and self.status == self.STATUS_DRAFT
        ):
            orig_wo = self.weight_out
            self.weight_out = None
            self.compute_estimations()
            self.weight_out = orig_wo

        super().save(*args, **kwargs)

    @property
    def yield_percent(self):
        """Return processing yield percentage."""
        if not self.weight_in:
            return Decimal("0")
        return (self.weight_out / self.weight_in) * Decimal("100")

    @property
    def purity_delta(self):
        """Difference between final and initial purity."""
        return (self.purity_after or Decimal("0")) - (
            self.purity_before or Decimal("0")
        )

    @property
    def cleaning_balance(self):
        """Alias for cleaned stock weight to surface "weight out" as balance."""
        return self.weight_out

    def balance_estimates(self):
        """Return cleaning balance estimates before, during and after operation.

        The method implements three complementary estimators to guard against
        stock manipulation:

        * **pre_operation** – forecast expected cleaned balance using the
          difference between target and initial purity and incorporating a
          default 0.75%% process loss (dust and spills).
        * **in_operation** – mid-operation estimate which averages the user's
          claimed output with a projection based on the average purity of the
          quality checks recorded so far.  This reflects the "practical" claim
          and the purity-based expectation without the extra loss factor.
        * **post_operation** – derived from the reject weight evidence.  Rejects
          plus cleaned balance should reconcile with the original weight in.

        A flag is returned when the spread between any available estimates (or
        the actual cleaned weight) exceeds the configured tolerance (default
        0.75%% of the input weight), signalling a potentially suspicious record.
        """

        weight_in = _dec(self.weight_in) or Decimal("0")
        purity_before = _dec(self.purity_before) or Decimal("0")
        target = _dec(self.target_purity) or purity_before

        # 1. Pre-operation estimate: purity delta plus 0.75%% loss allowance.
        purity_delta = max(target - purity_before, Decimal("0")) / Decimal("100")
        pre_loss = purity_delta + Decimal("0.0075")
        pre_operation = (weight_in * (Decimal("1") - pre_loss)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        ) if weight_in else None

        # 2. In-operation estimate: average of claimed balance and purity based
        # projection using QC samples (no 0.75%% loss factor).
        claimed = _dec(self.weight_out) or Decimal("0")
        qc_purities = list(
            self.quality_checks.values_list("purity_percent", flat=True)
        )
        in_operation = None
        if qc_purities:
            avg_qc = sum(Decimal(str(p)) for p in qc_purities) / len(qc_purities)
            purity_proj = (weight_in * (avg_qc / Decimal("100"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            in_operation = ((claimed + purity_proj) / Decimal("2")).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # 3. Post-operation estimate: based on reject evidence.
        post_operation = None
        if self.actual_reject_weight is not None:
            post_operation = (weight_in - _dec(self.actual_reject_weight)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )

        # Flag when estimates diverge beyond configured tolerance of input weight.
        tol_pct = _dec(getattr(settings, "DAILYREC_TOLERANCE_PCT", 0.01))
        tolerance = (weight_in * tol_pct).quantize(Decimal("0.01")) if weight_in else Decimal("0")
        candidates = [pre_operation, in_operation, post_operation, claimed]
        available = [c for c in candidates if c is not None]
        flagged = False
        spread = Decimal("0")
        if len(available) > 1:
            spread = max(available) - min(available)
            flagged = spread > tolerance

        reason = (
            f"Spread {spread} exceeds tolerance {tolerance}"
            if flagged
            else f"Spread {spread} within tolerance {tolerance}"
        )

        return {
            "pre_operation": pre_operation,
            "in_operation": in_operation,
            "post_operation": post_operation,
            "tolerance": tolerance,
            "spread": spread,
            "flagged": flagged,
            "reason": reason,
        }

    def post(self, user: User):
        from .services.cleaning import post_daily_record
        return post_daily_record(self.pk, user)


class QualityCheck(models.Model):
    daily_record = models.ForeignKey(
        'DailyRecord', related_name='quality_checks', on_delete=models.CASCADE
    )
    index = models.PositiveIntegerField()
    timestamp = models.DateTimeField(default=timezone.now, editable=False)

    sample_weight_g = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('30.00'))
    piece_quintals = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('50.00'))
    machine_rate_kgph = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('50.00'))

    weight_sound_g = models.DecimalField(max_digits=8, decimal_places=2)
    weight_reject_g = models.DecimalField(max_digits=8, decimal_places=2)

    purity_percent = models.DecimalField(max_digits=5, decimal_places=2, editable=False)

    class Meta:
        unique_together = ('daily_record', 'index')
        ordering = ['index']

    def save(self, *args, **kwargs):
        total = (self.weight_sound_g or 0) + (self.weight_reject_g or 0)
        self.purity_percent = Decimal('0')
        if total:
            self.purity_percent = (Decimal(self.weight_sound_g) / Decimal(total)) * Decimal('100')
        if not self.pk and not self.index:
            last = QualityCheck.objects.filter(daily_record=self.daily_record).order_by('-index').values_list('index', flat=True).first()
            self.index = (last or 0) + 1
        super().save(*args, **kwargs)


class DailyRecordAssessment(models.Model):
    """Stores balance estimate snapshots for a DailyRecord."""

    daily_record = models.OneToOneField(
        'DailyRecord', related_name='assessment', on_delete=models.CASCADE
    )
    pre_operation = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    in_operation = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    post_operation = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    tolerance = models.DecimalField(max_digits=12, decimal_places=2)
    spread = models.DecimalField(max_digits=12, decimal_places=2)
    flagged = models.BooleanField(default=False)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ['daily_record']


class LaborPayment(models.Model):
    """
    Tracks daily labor output and payment balance.
    """
    id                    = models.AutoField(primary_key=True)
    date                  = models.DateField()
    seed_type             = models.ForeignKey(SeedType, on_delete=models.PROTECT)
    owner                 = models.ForeignKey(Company, on_delete=models.PROTECT)
    degami_second_clean   = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    yetemezene_weighting  = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gravity_cleaning      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    rebag_quantity        = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sabiyan_quantity      = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_balance       = models.DecimalField(max_digits=12, decimal_places=2)
    remark                = models.TextField(blank=True)

    class Meta:
        unique_together = ("date", "seed_type", "owner")
        ordering        = ["date", "seed_type"]

    def __str__(self):
        return f"{self.date} | {self.seed_type.code} | {self.payment_balance}"


class StockSeries(models.Model):
    """Database view exposing per-day stock balances and flows."""

    owner_id = models.UUIDField()
    warehouse_id = models.UUIDField()
    seed_type = models.CharField(max_length=10)
    grade = models.CharField(max_length=50, blank=True)
    ts = models.DateField()
    balance_kg = models.DecimalField(max_digits=12, decimal_places=2)
    inflow_kg = models.DecimalField(max_digits=12, decimal_places=2)
    outflow_kg = models.DecimalField(max_digits=12, decimal_places=2)
    purity_wavg = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    doc_integrity = models.FloatField()

    class Meta:
        managed = False
        db_table = "v_bincard_stock_series"


class AuthEvent(models.Model):
    """Authentication event log."""

    ts = models.DateTimeField(auto_now_add=True)
    username = models.CharField(max_length=150)
    event = models.CharField(max_length=32)
    meta = models.JSONField(default=dict, blank=True)


class UserEvent(models.Model):
    """Tracks user lifecycle and role changes."""

    ts = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="+", on_delete=models.CASCADE
    )
    event = models.CharField(max_length=32)
    meta = models.JSONField(default=dict, blank=True)


class DashboardConfig(models.Model):
    """Per-role widget toggles for dashboards."""

    role = models.CharField(max_length=30, unique=True)
    widgets = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    updated_at = models.DateTimeField(auto_now=True)
