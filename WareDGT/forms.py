from django import forms
from django.contrib.auth.models import User
from django.forms import ClearableFileInput
from django.db.models import F, ExpressionWrapper, DateField
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import re
from difflib import get_close_matches


from .models import (
    Company,
    SeedType,
    Warehouse,
    UserProfile,
    PurchaseOrder,
    StockMovement,
    WeighbridgeSlipImage,
    QualityAnalysis,
    DailyRecord,
    BinCardEntry,
    BinCardAttachment,
    CleanedStockOut,
    LaborPayment,
    Commodity,
    EcxTrade,
    EcxTradeReceiptFile,
    EcxLoad,
    EcxMovement,
    PurchasedItemType,
    ContractMovement,
    SeedTypeDetail,
    QualityCheck,
    next_in_out_no,
)
from .pdf_utils import get_or_build_bincard_pdf


def get_default_owner():
    """Return the default "DGT" company, creating it if missing."""
    owner, _ = Company.objects.get_or_create(name="DGT", defaults={"description": ""})
    return owner


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "Company Name"})}


class SeedTypeForm(forms.ModelForm):
    class Meta:
        model = SeedType
        fields = ["code", "name"]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "Seed Code"}),
            "name": forms.TextInput(attrs={"placeholder": "Seed Name"}),
        }


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = [
            "code",
            "name",
            "description",
            "warehouse_type",
            "capacity_quintals",
            "footprint_m2",
            "latitude",
            "longitude",
            "zone_geojson",
        ]
        labels = {
            "warehouse_type": "Owner",
        }
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "Warehouse Code"}),
            "name": forms.TextInput(attrs={"placeholder": "Warehouse Name"}),
            # Custom textarea with a distinctive style for warehouse description
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Describe the warehouse in detail",
                    "class": "description-field",
                }
            ),
            "capacity_quintals": forms.NumberInput(attrs={"step": "0.01"}),
            "footprint_m2": forms.NumberInput(attrs={"step": "0.01"}),
            "latitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "longitude": forms.NumberInput(attrs={"step": "0.000001"}),
            "zone_geojson": forms.Textarea(attrs={"rows": 2}),
        }


class SeedTypeDetailForm(forms.ModelForm):
    category = forms.ChoiceField(
        choices=SeedTypeDetail.CATEGORY_CHOICES,
        help_text="Select the commodity category (Coffee/Beans/Sesame/Other)",
    )
    coffee_type = forms.ChoiceField(
        choices=[("", "— None —")] + list(SeedTypeDetail.COFFEE_TYPE_CHOICES),
        required=False,
        help_text="For Coffee category only",
    )
    class Meta:
        model = SeedTypeDetail
        fields = [
            "category",
            "coffee_type",
            "symbol",
            "name",
            "delivery_location",
            "grade",
            "origin",
            "handling_procedure",
        ]
        widgets = {
            "symbol": forms.TextInput(attrs={"placeholder": "Symbol"}),
            "name": forms.TextInput(attrs={"placeholder": "Name"}),
            "grade": forms.TextInput(attrs={"placeholder": "Grade"}),
            "origin": forms.Textarea(attrs={"rows": 2, "placeholder": "Origin"}),
            "handling_procedure": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Handling Procedure"}
            ),
        }

    def clean_symbol(self):
        sym = (self.cleaned_data.get("symbol") or "").upper().strip()
        if not sym:
            raise forms.ValidationError("Symbol is required")
        return sym


class PurchasedItemTypeForm(forms.ModelForm):
    class Meta:
        model = PurchasedItemType
        fields = ["seed_type", "origin", "grade", "description"]
        widgets = {
            "origin": forms.TextInput(attrs={"placeholder": "Origin"}),
            "grade": forms.TextInput(attrs={"placeholder": "Grade"}),
            "description": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Optional description"}
            ),
        }


class CommodityForm(forms.ModelForm):
    class Meta:
        model = Commodity
        fields = ["seed_type", "origin", "grade"]
        widgets = {
            "origin": forms.TextInput(attrs={"placeholder": "Origin"}),
            "grade": forms.TextInput(attrs={"placeholder": "Grade"}),
        }


class EcxTradeForm(forms.Form):
    """Form for registering ECX trades with one or more receipt/qty pairs."""

    # Additional fields for the cascading seed type selection. These are
    # populated on the client via JavaScript.
    owner = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        required=True,
        label="Owner",
    )
    # Allow selecting seed types without pre-filtering by category (e.g. Niger).
    category = forms.ChoiceField(
        choices=list(SeedTypeDetail.CATEGORY_CHOICES) + [("OTHER", "Other")],
        required=False,
        label="Seed Category",
    )
    # These selects are populated on the client via JavaScript. Using a
    # ``CharField`` with ``Select`` widget avoids server-side choice
    # validation while keeping the dropdown UI intact.
    symbol = forms.CharField(
        required=False,
        label="Seed Type",
        widget=forms.Select(),
    )
    grade = forms.CharField(
        required=False,
        widget=forms.Select(),
    )

    # Allow any warehouse value coming from the client-side dropdown without
    # server-side choice validation. The actual Warehouse instance will be
    # looked up when processing the form.
    warehouse = forms.CharField(
        required=False,
        label="Warehouse",
        widget=forms.Select(),
    )
    # Optional: a second warehouse for split purchases with the same NOR
    warehouse2 = forms.CharField(
        required=False,
        label="Second Warehouse (optional)",
        widget=forms.Select(),
    )
    # Independent seed selection for second warehouse
    category2 = forms.ChoiceField(
        choices=list(SeedTypeDetail.CATEGORY_CHOICES) + [("OTHER", "Other")],
        required=False,
        label="Seed Category (2nd)",
    )
    symbol2 = forms.CharField(
        required=False,
        label="Seed Type (2nd)",
        widget=forms.Select(),
    )
    grade2 = forms.CharField(
        required=False,
        label="Grade (2nd)",
        widget=forms.Select(),
    )
    net_obligation_receipt_no = forms.CharField(label="Net Obligation Receipt No")
    purchase_date = forms.DateField(widget=forms.SelectDateWidget)
    receipt_file = forms.FileField(
        widget=ClearableFileInput(),
        required=False,
        help_text="Upload an image or PDF of the Net Obligation Receipt",
    )
    receipt_entries = forms.CharField(
        label="Receipt & Qty Pairs",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "WRN1:10.5\nWRN2:5",
            }
        ),
        help_text="One pair per line as 'receipt:qty'.",
    )
    # Optional entries for the second warehouse
    receipt_entries2 = forms.CharField(
        label="Receipt & Qty Pairs (2nd Warehouse)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "WRN3:7\nWRN4:3 (optional)",
            }
        ),
        help_text="Only if using a second warehouse above.",
    )

    # Dynamic multi-warehouse payload (JSON), built by the client-side UI.
    groups_json = forms.CharField(required=False, widget=forms.HiddenInput())

    field_order = [
        "owner",
        "net_obligation_receipt_no",
        # The dynamic UI handles per-warehouse seed + warehouse selection.
        # Keep legacy fields out of the main order.
        "groups_json",
        # Legacy/fallback fields will still be accepted server-side.
        "category2",
        "symbol2",
        "grade2",
        "warehouse2",
        "receipt_entries2",
        "purchase_date",
        "receipt_file",
    ]

    def __init__(self, *args, **kwargs):
        default_owner = get_default_owner()
        if args:
            data = args[0].copy()
            if not data.get("owner"):
                data["owner"] = str(default_owner.pk)
            args = (data,) + args[1:]
        else:
            kwargs.setdefault("data", None)
            if kwargs["data"] is not None:
                data = kwargs["data"].copy()
                if not data.get("owner"):
                    data["owner"] = str(default_owner.pk)
                kwargs["data"] = data
            kwargs.setdefault("initial", {})
            kwargs["initial"].setdefault("owner", default_owner.pk)
        super().__init__(*args, **kwargs)
        self.fields["owner"].initial = default_owner.pk


class EcxTradeReceiptFileForm(forms.ModelForm):
    class Meta:
        model = EcxTradeReceiptFile
        fields = ["trade", "file"]
        widgets = {"file": ClearableFileInput(attrs={"multiple": False})}


class UserProfileForm(forms.ModelForm):
    user = forms.ModelChoiceField(queryset=User.objects.all())

    class Meta:
        model = UserProfile
        fields = ["user", "role"]
        widgets = {"role": forms.Select()}


class PurchaseOrderForm(forms.ModelForm):
    purchase_date = forms.DateField(widget=forms.SelectDateWidget)

    class Meta:
        model = PurchaseOrder
        fields = [
            "ecx_warehouse",
            "company_warehouse",
            "seed_type",
            "purchaser",
            "quantity_quintals",
            "purchase_date",
            "status",
        ]
        widgets = {
            "quantity_quintals": forms.NumberInput(attrs={"step": "0.01"}),
            "status": forms.Select(),
        }


class StockMovementForm(forms.ModelForm):
    ticket_date = forms.DateField(widget=forms.SelectDateWidget)
    enter_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    exit_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )

    class Meta:
        model = StockMovement
        fields = [
            "movement_type",
            "ticket_no",
            "ticket_date",
            "enter_time",
            "exit_time",
            "plate_no",
            "supplier",
            "receiver",
            "warehouse",
            "seed_type",
            "owner",
            "gross_weight",
            "tare_weight",
            "net_weight",
            "num_bags",
            "purchase_order",
        ]
        widgets = {
            "num_bags": forms.NumberInput(),
            "gross_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "tare_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "net_weight": forms.NumberInput(attrs={"step": "0.01"}),
        }


class EcxMovementWeighForm(forms.ModelForm):
    class Meta:
        model = EcxMovement
        fields = ["weighbridge_certificate"]

    def save(self, commit=True):
        mv = super().save(commit=False)
        if not mv.loaded:
            mv.loaded = True
            mv.loaded_at = timezone.now()
        if not mv.weighed:
            mv.weighed = True
            mv.weighed_at = timezone.now()
        if commit:
            mv.save()
        return mv


class EcxShipmentWeighForm(forms.Form):
    weighbridge_certificate = forms.FileField()

class WeighbridgeSlipImageForm(forms.ModelForm):
    class Meta:
        model = WeighbridgeSlipImage
        fields = ["movement", "image", "description"]
        widgets = {"image": ClearableFileInput()}


class SlipImageUploadForm(forms.Form):
    movement = forms.ModelChoiceField(queryset=StockMovement.objects.all())
    images = forms.ImageField(widget=ClearableFileInput(attrs={"multiple": False}))
    description = forms.CharField(required=False)


class EcxLoadForm(forms.Form):
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.filter(warehouse_type=Warehouse.ECX))
    trades = forms.ModelMultipleChoiceField(
        queryset=EcxTrade.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        help_text="Select receipts to include in this load",
    )
    plombs_count = forms.IntegerField(min_value=0, initial=0, required=True, help_text="Number of plombs/seals")
    has_trailer = forms.BooleanField(required=False, initial=False)
    trailer_count = forms.IntegerField(min_value=0, initial=0, required=False, help_text="0 if none")
    truck_image = forms.ImageField(required=False)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        qs = EcxTrade.objects.filter(loaded=False)
        qs = qs.annotate(
            last_pickup=ExpressionWrapper(
                F("purchase_date") + timedelta(days=5), output_field=DateField()
            )
        ).filter(last_pickup__gte=today)
        if self.user and hasattr(self.user, "profile") and self.user.profile.role == UserProfile.ECX_AGENT:
            allowed = self.user.profile.warehouses.all()
            self.fields["warehouse"].queryset = self.fields["warehouse"].queryset.filter(id__in=allowed)
            qs = qs.filter(warehouse__in=allowed)

        wh = self.data.get("warehouse") or self.initial.get("warehouse")
        if wh:
            qs = qs.filter(warehouse_id=wh)

        self.fields["trades"].queryset = qs.select_related("warehouse", "commodity")

    def clean(self):
        cleaned = super().clean()
        wh = cleaned.get("warehouse")
        trades = cleaned.get("trades") or []
        if trades:
            warehouses = {t.warehouse_id for t in trades}
            if len(warehouses) > 1:
                raise forms.ValidationError(
                    "Selected trades must be from one warehouse"
                )
            if wh and warehouses and wh.id not in warehouses:
                raise forms.ValidationError(
                    "Trades do not belong to the selected warehouse"
                )
            for t in trades:
                if t.is_overdue:
                    raise forms.ValidationError("Cannot load overdue trades")
            if not cleaned.get("warehouse"):
                cleaned["warehouse"] = trades[0].warehouse

        if cleaned.get("has_trailer") is False:
            cleaned["trailer_count"] = 0
        if cleaned.get("has_trailer") and (cleaned.get("trailer_count") is None or cleaned.get("trailer_count") < 1):
            raise forms.ValidationError("If the truck has a trailer, trailer count must be at least 1.")
        return cleaned


class QualityAnalysisForm(forms.ModelForm):
    second_test_datetime = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )

    class Meta:
        model = QualityAnalysis
        fields = [
            "movement",
            "first_sound_weight",
            "first_foreign_weight",
            "first_purity_percent",
            "second_test_datetime",
            "second_sound_weight",
            "second_foreign_weight",
            "total_bags",
            "sampled_bags",
            "second_purity_percent",
            "comment",
        ]
        widgets = {
            "first_sound_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "first_foreign_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "first_purity_percent": forms.NumberInput(attrs={"step": "0.01"}),
            "second_sound_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "second_foreign_weight": forms.NumberInput(attrs={"step": "0.01"}),
            "second_purity_percent": forms.NumberInput(attrs={"step": "0.01"}),
        }


class DailyRecordForm(forms.ModelForm):
    entry_date = forms.DateField(
        required=False,
        label="Entry Date (optional)",
        input_formats=["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"type": "date", "placeholder": "YYYY-MM-DD"}),
    )
    class Meta:
        model = DailyRecord
        fields = [
            "owner",
            "seed_type",
            "operation_type",
            "lot",
            # Non-model field rendered in form; saved to model.date if provided
            # (kept out of Meta.fields to avoid direct model binding)
            # Included via field_order below for placement.
            "target_purity",
            "weight_in",
            "purity_before",
            "labor_rate_per_qtl",
            "cleaning_labor_rate_etb_per_qtl",
            "reject_weighing_rate_etb_per_qtl",
            "start_time",
            "end_time",
            "cleaning_equipment",
            "chemicals_used",
            "workers",
            "recleaning_reason",
        ]
        widgets = {
            # Allow editing weight_in so officers can clean a partial amount
            "weight_in": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "purity_before": forms.NumberInput(attrs={"step": "0.01", "readonly": "readonly"}),
            "target_purity": forms.NumberInput(attrs={"step": "0.01"}),
            "labor_rate_per_qtl": forms.NumberInput(attrs={"step": "0.01"}),
            "cleaning_labor_rate_etb_per_qtl": forms.NumberInput(attrs={"step": "0.01"}),
            "reject_weighing_rate_etb_per_qtl": forms.NumberInput(attrs={"step": "0.01"}),
            "recleaning_reason": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "recleaning_reason": "Reason",
        }
    field_order = [
        "owner",
        "seed_type",
        "operation_type",
        "lot",
        "entry_date",
        "target_purity",
        "weight_in",
        "purity_before",
        "labor_rate_per_qtl",
        "cleaning_labor_rate_etb_per_qtl",
        "reject_weighing_rate_etb_per_qtl",
        "start_time",
        "end_time",
        "cleaning_equipment",
        "chemicals_used",
        "workers",
        "recleaning_reason",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restrict operation type choices to Cleaning and Recleaning only
        if "operation_type" in self.fields:
            self.fields["operation_type"].choices = [
                (DailyRecord.CLEANING, "Cleaning"),
                (DailyRecord.RECLEANING, "Re cleaning"),
            ]
        # These fields are filled automatically based on the selected lot or
        # operation type, so they should not be required in the form submission.
        for f in [
            "weight_in",
            "purity_before",
            "recleaning_reason",
            "target_purity",
            "start_time",
            "end_time",
            "cleaning_equipment",
            "chemicals_used",
            "workers",
        ]:
            if f in self.fields:
                self.fields[f].required = False
        # Ensure weight_in is editable even if a browser caches the readonly attr
        try:
            if "readonly" in (self.fields["weight_in"].widget.attrs or {}):
                self.fields["weight_in"].widget.attrs.pop("readonly", None)
        except Exception:
            pass
        # Owners with existing bin card entries
        self.fields["owner"].queryset = Company.objects.filter(
            bincardentry__isnull=False
        ).distinct()

        owner = self.data.get("owner") or self.initial.get("owner")
        if owner:
            seed_ids = (
                BinCardEntry.objects.filter(owner_id=owner)
                .values_list("seed_type_id", flat=True)
                .distinct()
            )
            self.fields["seed_type"].queryset = SeedTypeDetail.objects.filter(
                id__in=seed_ids
            )
        else:
            self.fields["seed_type"].queryset = SeedTypeDetail.objects.none()

        seed_type = self.data.get("seed_type") or self.initial.get("seed_type")
        op = self.data.get("operation_type") or self.initial.get("operation_type")
        if owner and seed_type:
            qs = BinCardEntry.objects.filter(
                owner_id=owner, seed_type_id=seed_type
            )
            if op == DailyRecord.CLEANING:
                # Allow partial cleaning: any lot with remaining raw weight
                # is a valid candidate, regardless of prior cleaned weight.
                # Exclude stock-out rows which may have negative signed weights.
                qs = qs.filter(raw_weight_remaining__gt=0, weight__gt=0)
            elif op == DailyRecord.RECLEANING:
                qs = qs.filter(cleaned_weight__gt=0)
            self.fields["lot"].queryset = qs
        else:
            self.fields["lot"].queryset = BinCardEntry.objects.none()

    def clean(self):
        cleaned = super().clean()

        lot = cleaned.get("lot")
        if lot:
            # Default weight_in to remaining raw weight if user did not override.
            # Allow partial cleaning: validate positive and not exceeding remaining.
            user_weight_in = cleaned.get("weight_in")
            if user_weight_in in (None, ""):
                cleaned["weight_in"] = lot.raw_weight_remaining
            else:
                try:
                    # Coerce to Decimal-compatible number via float-like value
                    val = Decimal(str(user_weight_in))
                except Exception:
                    self.add_error("weight_in", "Enter a valid weight.")
                    val = None
                if val is not None:
                    if val <= 0:
                        self.add_error("weight_in", "Weight must be positive.")
                    elif lot.raw_weight_remaining is not None and val > lot.raw_weight_remaining:
                        self.add_error(
                            "weight_in",
                            f"Cannot exceed remaining lot weight ({lot.raw_weight_remaining}).",
                        )
                    cleaned["weight_in"] = val
            cleaned["purity_before"] = lot.purity
            # Guard against accidental negative/zero raw weights (e.g. if a
            # stock-out entry slipped through). Keep the error user-facing.
            if cleaned["weight_in"] is None or cleaned["weight_in"] <= 0:
                self.add_error("lot", "Selected lot has no remaining raw weight to process.")
        op = cleaned.get("operation_type")
        if op not in {DailyRecord.CLEANING, DailyRecord.RECLEANING}:
            # For non-cleaning operations default derived fields.
            cleaned["weight_out"] = cleaned.get("weight_in")
            cleaned["purity_after"] = cleaned.get("purity_before")
            cleaned["rejects"] = Decimal("0")
            cleaned["recleaning_reason"] = ""
            cleaned["target_purity"] = cleaned.get("purity_before")
        else:
            # For cleaning operations these values start at zero and are
            # incrementally updated as quality checks are recorded.
            cleaned["weight_out"] = Decimal("0")
            cleaned["purity_after"] = cleaned.get("purity_before")
            cleaned["rejects"] = Decimal("0")
            cleaned["target_purity"] = cleaned.get("target_purity") or cleaned.get("purity_before")
            if op == DailyRecord.RECLEANING and not cleaned.get("recleaning_reason"):
                self.add_error("recleaning_reason", "This field is required.")
        cleaned["shrink_margin"] = Decimal("100")

        # Ensure instance is updated with computed values
        self.instance.weight_in = cleaned.get("weight_in")
        self.instance.purity_before = cleaned.get("purity_before")
        self.instance.weight_out = cleaned.get("weight_out")
        self.instance.purity_after = cleaned.get("purity_after")
        self.instance.shrink_margin = cleaned.get("shrink_margin")
        self.instance.target_purity = cleaned.get("target_purity")
        self.instance.recleaning_reason = cleaned.get("recleaning_reason")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.lot_id and not instance.warehouse_id:
            instance.warehouse = instance.lot.warehouse
        # Optional backdate
        ed = self.cleaned_data.get("entry_date")
        if ed:
            instance.date = ed
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class QualityCheckForm(forms.ModelForm):
    class Meta:
        model = QualityCheck
        fields = (
            "weight_sound_g",
            "weight_reject_g",
            "sample_weight_g",
            "piece_quintals",
            "machine_rate_kgph",
        )


class ContractMovementForm(forms.ModelForm):
    """Form for Logistics Manager to register contract farming stocks in movement."""

    # Make symbol a selectable dropdown; choices populated client-side and validated server-side
    symbol = forms.CharField(label="Symbol", widget=forms.Select())

    class Meta:
        model = ContractMovement
        fields = [
            "owner",
            "category",
            "symbol",
            "quantity_quintals",
            "origin",
            "agent_name",
            "agent_phone",
            "advice_number",
            "dispatch_number",
            "dispatch_image",
            "notes",
        ]
        widgets = {
            "category": forms.Select(),
            "origin": forms.TextInput(attrs={"placeholder": "e.g., Humera"}),
            "agent_phone": forms.TextInput(attrs={"placeholder": "+251..."}),
            "notes": forms.Textarea(attrs={"rows": 2}),
            "quantity_quintals": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default owner to DGT when present
        default_owner = get_default_owner()
        self.fields["owner"].required = False
        if not self.initial.get("owner"):
            self.initial["owner"] = default_owner

    def clean_symbol(self):
        sym = (self.cleaned_data.get("symbol") or "").strip()
        if not sym:
            raise forms.ValidationError("Seed symbol is required")
        return sym.upper()

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get("category")
        sym = (cleaned.get("symbol") or "").upper()
        if cat and sym:
            exists = SeedTypeDetail.objects.filter(category=cat, symbol=sym).exists()
            if not exists:
                self.add_error("symbol", "Select a valid symbol for the chosen category")
        q = cleaned.get("quantity_quintals")
        if q is None or q <= 0:
            self.add_error("quantity_quintals", "Enter a positive load quantity (qtls)")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.owner:
            instance.owner = get_default_owner()
        if commit:
            instance.save()
        return instance


class BinCardEntryForm(forms.ModelForm):
    entry_date = forms.DateField(
        required=False,
        label="Entry Date (optional)",
        input_formats=["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"type": "date", "placeholder": "YYYY-MM-DD"}),
    )
    ecx_movement = forms.ModelChoiceField(
        queryset=EcxMovement.objects.none(),
        required=False,
        label="ECX Stock",
    )
    contract_movement = forms.ModelChoiceField(
        queryset=ContractMovement.objects.none(),
        required=False,
        label="Contract Stock",
    )
    # Local purchase support: allow direct seed selection (used when source_type=LOCAL)
    seed_type = forms.ModelChoiceField(
        queryset=SeedTypeDetail.objects.all(),
        required=False,
        label="Seed Type",
    )
    # Local purchase UX: category + symbol selection (filtered client-side)
    category = forms.ChoiceField(
        choices=list(SeedTypeDetail.CATEGORY_CHOICES) + [("OTHER", "Other")],
        required=False,
        label="Seed Category",
    )
    symbol = forms.CharField(
        required=False,
        label="Seed Type",
        widget=forms.Select(),
    )
    # Third-party limited tracking fields
    r_no = forms.CharField(required=False, label="R No.")
    service_rate_etb_per_qtl = forms.DecimalField(
        required=False, min_value=0, label="Service Rate (ETB/qtl)",
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )
    storage_rate_etb_per_day = forms.DecimalField(
        required=False, min_value=0, label="Storage Rate (ETB/day)",
        widget=forms.NumberInput(attrs={"step": "0.01"}),
    )
    storage_days = forms.IntegerField(required=False, min_value=0, label="Storage Days")
    new_owner_name = forms.CharField(required=False, label="Company Name")
    new_owner_description = forms.CharField(
        required=False, label="Company Description", widget=forms.Textarea
    )
    unloading_rate_etb_per_qtl = forms.DecimalField(
        required=False,
        min_value=0,
        label="Unloading labor (ETB per qtl)",
        help_text="Labor cost per quintal for this operation.",
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "e.g. 35.00"}),
    )

    field_order = [
        "owner",
        "warehouse",
        "new_owner_name",
        "new_owner_description",
        "source_type",
        "category",
        "symbol",
        "ecx_movement",
        "contract_movement",
        "weight",
        "entry_date",
        "unloading_rate_etb_per_qtl",
        "num_bags",
        "car_plate_number",
        "purity",
        "weighbridge_certificate",
        "warehouse_document_number",
        "warehouse_document",
        "quality_form",
        "remark",
    ]

    class Meta:
        model = BinCardEntry
        fields = [
            "owner",
            "warehouse",
            "source_type",
            "ecx_movement",
            "contract_movement",
            # Limited/Contract inputs
            "r_no",
            "service_rate_etb_per_qtl",
            "storage_rate_etb_per_day",
            "storage_days",
            "weight",
            "unloading_rate_etb_per_qtl",
            "num_bags",
            "car_plate_number",
            "purity",
            "weighbridge_certificate",
            "warehouse_document_number",
            "warehouse_document",
            "quality_form",
            "remark",
        ]
        widgets = {
            "weight": forms.NumberInput(attrs={"step": "0.01"}),
            "purity": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        default_owner = get_default_owner()
        if args:
            data = args[0].copy()
            if not data.get("owner"):
                data["owner"] = str(default_owner.pk)
            args = (data,) + args[1:]
        else:
            kwargs.setdefault("data", None)
            if kwargs["data"] is not None:
                data = kwargs["data"].copy()
                if not data.get("owner"):
                    data["owner"] = str(default_owner.pk)
                kwargs["data"] = data
            kwargs.setdefault("initial", {})
            kwargs["initial"].setdefault("owner", default_owner.pk)
        super().__init__(*args, **kwargs)
        self.fields["owner"].initial = default_owner.pk
        self.fields["warehouse"].queryset = Warehouse.objects.filter(
            warehouse_type=Warehouse.DGT
        )
        self.fields["warehouse"].required = True

        owner = self.data.get("owner") or self.initial.get("owner")

        qs = EcxMovement.objects.filter(weighed=True)
        if owner:
            qs = qs.filter(owner_id=owner)
        self.fields["ecx_movement"].queryset = qs
        # Available contract movements (in-transit only)
        self.fields["contract_movement"].queryset = (
            ContractMovement.objects.filter(status=ContractMovement.IN_TRANSIT, consumed_by__isnull=True)
            .order_by("-created_at")
        )
        # Seed selection is only required for LOCAL purchases; keep full list for now
        self.fields["seed_type"].required = False
        # Category/symbol are used for LOCAL; validate in clean()
        self.fields["category"].required = False
        self.fields["symbol"].required = False
        for f in [
            "num_bags",
            "car_plate_number",
            "purity",
            "unloading_rate_etb_per_qtl",
            "weighbridge_certificate",
            "warehouse_document_number",
            "warehouse_document",
            "quality_form",
        ]:
            self.fields[f].required = False
        for f in [
            "r_no",
            "service_rate_etb_per_qtl",
            "storage_rate_etb_per_day",
            "storage_days",
        ]:
            self.fields[f].required = False

    def clean(self):
        cleaned = super().clean()
        owner = cleaned.get("owner")
        if owner and owner.name.lower() == "other":
            if not cleaned.get("new_owner_name"):
                self.add_error("new_owner_name", "Specify company name")
            if not cleaned.get("new_owner_description"):
                self.add_error("new_owner_description", "Provide company description")
        source = cleaned.get("source_type")
        mv = cleaned.get("ecx_movement")
        # Determine if this is a third-party (limited) flow
        owner = cleaned.get("owner")
        is_other = bool(owner and getattr(owner, "name", "").lower() == "other")
        if source == BinCardEntry.ECX and not is_other:
            if not mv:
                self.add_error("ecx_movement", "Select an ECX stock")
            if mv:
                seed_code = mv.item_type.seed_type or ""
                match = re.match(r"([A-Za-z]+?)(UG|[0-9]+)?$", seed_code)
                base_symbol = match.group(1) if match else seed_code
                detail = SeedTypeDetail.objects.filter(symbol=base_symbol).first()
                if detail is None:
                    detail = SeedTypeDetail.objects.filter(category=base_symbol).first()
                if detail is None:
                    symbols = list(
                        SeedTypeDetail.objects.values_list("symbol", flat=True)
                    )
                    close = get_close_matches(base_symbol, symbols, n=1, cutoff=0.8)
                    if close:
                        detail = SeedTypeDetail.objects.filter(symbol=close[0]).first()
                if detail is None:
                    self.add_error(
                        "ecx_movement", f"No seed type found for '{seed_code}'"
                    )
                else:
                    self.seed_detail = detail
        elif source == BinCardEntry.CONTRACT or is_other:
            # Always require a registered Contract Movement; symbol is inferred
            cmv = cleaned.get("contract_movement")
            if not cmv:
                self.add_error("contract_movement", "Select a Contract stock")
            else:
                sym = cmv.symbol
                detail = SeedTypeDetail.objects.filter(symbol=sym).first()
                if not detail:
                    self.add_error("contract_movement", f"Unknown symbol '{sym}'")
                else:
                    self.seed_detail = detail
            if not cleaned.get("weight"):
                self.add_error("weight", "Enter weight (qtls)")
            # Enforce registered quantity match to prevent partial mapping mistakes
            if cmv and cleaned.get("weight") is not None:
                try:
                    w = Decimal(str(cleaned.get("weight")))
                except Exception:
                    w = None
                if w is None or w != cmv.quantity_quintals:
                    self.add_error("weight", f"Weight must equal the registered load: {cmv.quantity_quintals} qtl")
            # Purity not required for 'Other' owners (limited tracking)
            if not is_other and not cleaned.get("purity"):
                self.add_error("purity", "Enter purity (%)")
        elif source == BinCardEntry.LOCAL:
            # Local purchases: prefer category+symbol; fall back to direct seed_type.
            sym = (cleaned.get("symbol") or "").upper().strip()
            st = cleaned.get("seed_type")
            if sym:
                detail = SeedTypeDetail.objects.filter(symbol=sym).first()
                if not detail:
                    self.add_error("symbol", f"Unknown symbol '{sym}'")
                else:
                    self.seed_detail = detail
            else:
                if not st:
                    self.add_error("symbol", "Select a seed type")
                else:
                    self.seed_detail = st
            if not cleaned.get("weight"):
                self.add_error("weight", "Enter weight (qtls)")
            if not cleaned.get("purity"):
                self.add_error("purity", "Enter purity (%)")
        else:
            self.add_error("source_type", "Invalid source type")
        return cleaned

    def save(self, commit=True):
        owner_field = self.cleaned_data["owner"]
        owner_name = owner_field.name.lower()
        is_other = owner_name == "other"
        # Consider any owner other than DGT/BestWay as third-party (limited)
        normalized = owner_name.replace(" ", "")
        is_third_party = is_other or (normalized not in {"dgt", "bestway"})
        owner = owner_field
        if is_other:
            owner = Company.objects.create(
                name=self.cleaned_data["new_owner_name"],
                description=self.cleaned_data["new_owner_description"],
            )
        self.instance.owner = owner
        self.instance.warehouse = self.cleaned_data["warehouse"]
        mv = self.cleaned_data.get("ecx_movement")
        if self.cleaned_data.get("source_type") == BinCardEntry.ECX and mv and not is_other:
            self.instance.ecx_movement = mv
            self.instance.seed_type = getattr(self, "seed_detail", None)
        else:
            # Set seed type from inferred detail
            self.instance.seed_type = getattr(self, "seed_detail", None)
            # Auto description based on source type
            src = self.cleaned_data.get("source_type")
            self.instance.description = (
                "ECX stock in for Export"
                if src == BinCardEntry.ECX
                else ("Local purchase stock in" if src == BinCardEntry.LOCAL else "Contract farming stock in for Export")
            )
        # Third-party limited fields and scope (apply for any non-DGT/BestWay owner)
        if is_third_party:
            self.instance.tracking_scope = BinCardEntry.LIMITED
            self.instance.r_no = self.cleaned_data.get("r_no", "") or ""
            self.instance.service_rate_etb_per_qtl = self.cleaned_data.get("service_rate_etb_per_qtl")
            self.instance.storage_rate_etb_per_day = self.cleaned_data.get("storage_rate_etb_per_day")
            self.instance.storage_days = self.cleaned_data.get("storage_days")
            # Compute storage fee if data present: rate * days * (weight/100)
            rate = self.cleaned_data.get("storage_rate_etb_per_day")
            days = self.cleaned_data.get("storage_days")
            weight = self.cleaned_data.get("weight")
            try:
                if rate is not None and days is not None and weight is not None:
                    self.instance.storage_fee_etb = (rate * days * (weight / 100)).quantize(Decimal("0.01"))
            except Exception:
                pass
        # If description not set for ECX branch, set it now
        if self.cleaned_data.get("source_type") == BinCardEntry.ECX and not getattr(self.instance, "description", None):
            self.instance.description = "ECX stock in for Export"
        if self.cleaned_data.get("source_type") == BinCardEntry.LOCAL and not getattr(self.instance, "description", None):
            self.instance.description = "Local purchase stock in"
        entry = super().save(commit)
        # Optional backdate support
        ed = self.cleaned_data.get("entry_date")
        if ed and getattr(self.instance, "pk", None):
            type(self.instance).objects.filter(pk=self.instance.pk).update(date=ed)
            self.instance.date = ed
        # If a contract movement was selected, mark it consumed and link image
        if (
            self.cleaned_data.get("source_type") == BinCardEntry.CONTRACT
            and not is_other
            and getattr(self.instance, "pk", None)
        ):
            cmv = self.cleaned_data.get("contract_movement")
            if cmv:
                try:
                    cmv.status = ContractMovement.CONSUMED
                    cmv.used_at = timezone.now()
                    cmv.consumed_by = self.instance
                    cmv.save(update_fields=["status", "used_at", "consumed_by"])
                except Exception:
                    pass
                if cmv.dispatch_image:
                    BinCardAttachment.objects.create(
                        entry=self.instance,
                        kind=BinCardAttachment.Kind.WAREHOUSE_DOC,
                        file=cmv.dispatch_image,
                    )
        return entry


class CleanedStockOutForm(forms.ModelForm):
    entry_date = forms.DateField(
        required=False,
        label="Entry Date (optional)",
        input_formats=["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"],
        widget=forms.DateInput(attrs={"type": "date", "placeholder": "YYYY-MM-DD"}),
    )
    owner = forms.ModelChoiceField(queryset=Company.objects.none(), required=True)
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(),
        required=True,
        label="DGT Warehouse",
    )
    loading_rate_etb_per_qtl = forms.DecimalField(
        required=False,
        min_value=0,
        label="Loading labor (ETB per qtl)",
        help_text="Labor cost per quintal for this operation.",
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "e.g. 35.00"}),
    )
    field_order = [
        "owner",
        "seed_type",
        "warehouse",
        "weight",
        "entry_date",
        "loading_rate_etb_per_qtl",
        "num_bags",
        "car_plate_number",
        "weighbridge_certificate",
        "warehouse_document_number",
        "warehouse_document",
    ]

    class Meta:
        model = CleanedStockOut
        fields = [
            "owner",
            "seed_type",
            "warehouse",
            "weight",
            "loading_rate_etb_per_qtl",
            "num_bags",
            "car_plate_number",
            "weighbridge_certificate",
            "warehouse_document_number",
            "warehouse_document",
        ]
        widgets = {
            "weight": forms.NumberInput(attrs={"step": "0.01"}),
            "loading_rate_etb_per_qtl": forms.NumberInput(attrs={"step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["owner"].queryset = Company.objects.order_by("name")
        self.fields["warehouse"].queryset = Warehouse.objects.filter(
            warehouse_type=Warehouse.DGT
        )
        self.fields["warehouse"].required = True

        self.available = None
        available_ids = []
        owner = self.data.get("owner") or self.initial.get("owner")
        warehouse = self.data.get("warehouse") or self.initial.get("warehouse")
        for st in SeedTypeDetail.objects.all():
            avail = self.get_available_weight(st, owner, warehouse)
            if avail > 0:
                available_ids.append(st.id)
            if self.data.get("seed_type") == str(st.id):
                self.available = avail
                self.fields["weight"].help_text = f"Available: {avail} qtl"
        self.fields["seed_type"].queryset = SeedTypeDetail.objects.filter(
            id__in=available_ids
        )
        # Optional UI inputs; weighbridge certificate is optional for stock out registration
        optional_fields = [
            "num_bags",
            "car_plate_number",
            "loading_rate_etb_per_qtl",
            "warehouse_document_number",
            "warehouse_document",
        ]
        for f in optional_fields:
            self.fields[f].required = False
        self.fields["weighbridge_certificate"].required = False

    def clean(self):
        cleaned = super().clean()
        st = cleaned.get("seed_type")
        wt = cleaned.get("weight")
        owner = cleaned.get("owner")
        warehouse = cleaned.get("warehouse")
        if st and wt is not None:
            avail = self.get_available_weight(st, owner, warehouse)
            if wt > avail:
                self.add_error("weight", f"Cannot exceed available {avail} qtl")
        return cleaned

    @staticmethod
    def get_available_weight(seed_type, owner, warehouse=None):
        from django.db.models import Sum
        from .models import StockOut

        filters = {"seed_type": seed_type}
        if owner:
            filters["owner"] = owner
        if warehouse:
            filters["warehouse"] = warehouse

        # Totals on lots are stored as quintals
        cleaned_qtl = (
            BinCardEntry.objects.filter(**filters)
            .aggregate(total=Sum("cleaned_total_kg"))
            .get("total")
            or Decimal("0")
        )

        # Outflows can be recorded via the legacy CleanedStockOut form (qtl)
        # and the newer StockOut API (stored in kg). Subtract both.
        out_qtl_legacy = (
            CleanedStockOut.objects.filter(**filters)
            .aggregate(total=Sum("weight"))
            .get("total")
            or Decimal("0")
        )
        stock_out_filters = {
            "seed_type": seed_type,
            "stock_class": StockOut.CLEANED,
        }
        if owner:
            stock_out_filters["owner"] = owner
        if warehouse:
            stock_out_filters["warehouse"] = warehouse
        out_kg = (
            StockOut.objects.filter(**stock_out_filters)
            .aggregate(total=Sum("quantity_kg"))
            .get("total")
            or Decimal("0")
        )
        out_qtl_api = out_kg / Decimal("100")

        return (Decimal(cleaned_qtl) - Decimal(out_qtl_legacy) - Decimal(out_qtl_api)).quantize(
            Decimal("0.01")
        )

    def save(self, user=None, commit=True):
        """Save the stock-out and record a matching bin card entry."""

        self.instance.owner = self.cleaned_data["owner"]
        self.instance.warehouse = self.cleaned_data["warehouse"]
        st = self.cleaned_data["seed_type"]
        owner = self.cleaned_data["owner"]
        warehouse = self.cleaned_data["warehouse"]
        weight = self.cleaned_data["weight"]

        next_no = next_in_out_no(st, owner=owner, warehouse=warehouse)
        self.instance.in_out_no = next_no
        cleaned_out = super().save(commit)
        # Optional backdate for legacy CleanedStockOut path
        ed = self.cleaned_data.get("entry_date")
        if ed and getattr(cleaned_out, "pk", None):
            type(cleaned_out).objects.filter(pk=cleaned_out.pk).update(date=ed)

        entry = BinCardEntry.objects.create(
            seed_type=st,
            owner=owner,
            grade=getattr(st, "grade", "") or "",
            warehouse=warehouse,
            in_out_no=next_no,
            description="Cleaned product stock out",
            weight=-weight,
            cleaned_total_kg=-weight,
            rejects_total_kg=Decimal("0"),
            loading_rate_etb_per_qtl=self.cleaned_data.get("loading_rate_etb_per_qtl"),
            num_bags=self.cleaned_data.get("num_bags") or 0,
            car_plate_number=self.cleaned_data.get("car_plate_number", ""),
            weighbridge_certificate=self.cleaned_data.get("weighbridge_certificate"),
            warehouse_document_number=self.cleaned_data.get("warehouse_document_number", ""),
            warehouse_document=self.cleaned_data.get("warehouse_document"),
        )
        if ed and getattr(entry, "pk", None):
            type(entry).objects.filter(pk=entry.pk).update(date=ed)
            entry.date = ed

        if user:
            get_or_build_bincard_pdf(entry, user)

        # expose the created bin card entry to callers
        self.bincard_entry = entry

        return cleaned_out


class LocalPurchaseForm(forms.Form):
    """Warehouse Officer form to register a local-market purchase for approval.

    On submit, a BinCardEntryRequest(IN) will be created with source_type=LOCAL
    and sent to the Logistics Manager for approval.
    """

    owner = forms.ModelChoiceField(queryset=Company.objects.all(), required=True, label="Owner")
    warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.filter(warehouse_type=Warehouse.DGT),
        required=True,
        label="DGT Warehouse",
    )
    seed_type = forms.ModelChoiceField(queryset=SeedTypeDetail.objects.all(), required=True, label="Seed Type")
    weight = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01, label="Weight (qtls)")
    purity = forms.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, label="Purity (%)")
    num_bags = forms.IntegerField(required=False, min_value=0)
    car_plate_number = forms.CharField(required=False, max_length=20)
    unloading_rate_etb_per_qtl = forms.DecimalField(required=False, min_value=0, decimal_places=2, max_digits=12, label="Unloading labor (ETB/qtl)")
    weighbridge_certificate = forms.FileField(required=False)
    warehouse_document_number = forms.CharField(required=False, max_length=50)
    warehouse_document = forms.FileField(required=False)
    quality_form = forms.FileField(required=False)
    remark = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    entry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}), label="Entry Date (optional)")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default owner to DGT where present
        try:
            default_owner = get_default_owner()
            self.fields["owner"].initial = default_owner
        except Exception:
            pass


class LaborPaymentForm(forms.ModelForm):
    date = forms.DateField(widget=forms.SelectDateWidget)

    class Meta:
        model = LaborPayment
        fields = [
            "date",
            "seed_type",
            "owner",
            "degami_second_clean",
            "yetemezene_weighting",
            "gravity_cleaning",
            "rebag_quantity",
            "sabiyan_quantity",
            "payment_balance",
            "remark",
        ]
        widgets = {
            "degami_second_clean": forms.NumberInput(attrs={"step": "0.01"}),
            "yetemezene_weighting": forms.NumberInput(attrs={"step": "0.01"}),
            "gravity_cleaning": forms.NumberInput(attrs={"step": "0.01"}),
            "rebag_quantity": forms.NumberInput(attrs={"step": "0.01"}),
            "sabiyan_quantity": forms.NumberInput(attrs={"step": "0.01"}),
            "payment_balance": forms.NumberInput(attrs={"step": "0.01"}),
        }


class UserEditForm(forms.ModelForm):
    """Edit user's basic info and role."""

    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    warehouses = forms.ModelMultipleChoiceField(
        queryset=Warehouse.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        super().__init__(*args, **kwargs)
        profile = getattr(instance, "profile", None) if instance else None
        ecx_qs = Warehouse.objects.filter(warehouse_type=Warehouse.ECX)
        available_ecx = ecx_qs.exclude(
            assigned_users__role=UserProfile.ECX_AGENT,
            assigned_users__user__is_active=True,
        )
        if profile:
            available_ecx = available_ecx.union(profile.warehouses.all())
        self.fields["warehouses"].queryset = available_ecx.distinct()

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        whs = cleaned.get("warehouses")
        profile = getattr(self.instance, "profile", None)

        if role == UserProfile.ECX_AGENT:
            if not whs or whs.count() == 0:
                raise forms.ValidationError(
                    "ECX Agent must be assigned to at least one ECX warehouse."
                )
            busy_qs = whs
            if profile:
                busy_qs = busy_qs.exclude(assigned_users=profile)
            busy = busy_qs.filter(
                assigned_users__role=UserProfile.ECX_AGENT,
                assigned_users__user__is_active=True,
            ).exists()
            if busy:
                raise forms.ValidationError(
                    "One or more selected warehouses are already assigned to an active user."
                )
        else:
            cleaned["warehouses"] = self.fields["warehouses"].queryset.none()

        return cleaned


class UserCreateForm(forms.ModelForm):
    """Create a new user without an initial password."""

    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES)
    warehouses = forms.ModelMultipleChoiceField(
        queryset=Warehouse.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        ecx_qs = Warehouse.objects.filter(warehouse_type=Warehouse.ECX)
        available_ecx = ecx_qs.exclude(
            assigned_users__role=UserProfile.ECX_AGENT,
            assigned_users__user__is_active=True,
        ).distinct()
        self.fields["warehouses"].queryset = available_ecx

    def save(self, commit=True):
        user = super().save(commit=False)
        # Use a random password so the account is disabled but stores a
        # standard hash instead of an unusable value. The user will reset it
        # via email, so the temporary password is never revealed.
        # Generate a random password without relying on any custom
        # ``UserManager`` methods to avoid AttributeError issues on
        # deployments with stripped-down managers.
        from django.utils.crypto import get_random_string

        tmp_password = get_random_string(12)
        user.set_password(tmp_password)
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data["role"]
            profile.save()
            profile.warehouses.set(self.cleaned_data.get("warehouses", []))
        return user

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        whs = cleaned.get("warehouses")

        if role == UserProfile.ECX_AGENT:
            if not whs or whs.count() == 0:
                raise forms.ValidationError(
                    "ECX Agent must be assigned to at least one ECX warehouse."
                )
            busy = whs.filter(
                assigned_users__role=UserProfile.ECX_AGENT,
                assigned_users__user__is_active=True,
            ).exists()
            if busy:
                raise forms.ValidationError(
                    "One or more selected warehouses are already assigned to an active user."
                )
        else:
            cleaned["warehouses"] = self.fields["warehouses"].queryset.none()

        return cleaned
