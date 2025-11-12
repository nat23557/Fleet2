# views.py
import logging
import json
import os
from datetime import timedelta, date, datetime, time
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP
import re
from uuid import UUID
from django.shortcuts import render, get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.core.files.storage import default_storage
from django.utils.crypto import get_random_string
from django.db.models import (
    Sum,
    Avg,
    F,
    ExpressionWrapper,
    DateField,
    BooleanField,
    Case,
    When,
    Value,
    Count,
    Q,
    DecimalField,
    FloatField,
    Q,
)
from django.db.models import Min, Max, Model, QuerySet
from django.db.models.functions import Abs, Cast
from django.db.models import IntegerField
from django.views import View
from django.views.generic import (
    ListView,
    TemplateView,
    CreateView,
    UpdateView,
    FormView,
)
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from functools import wraps
import csv

from rest_framework import viewsets, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import SAFE_METHODS, BasePermission
from django.db.utils import ProgrammingError, OperationalError
from django.db import transaction, IntegrityError
from django.db.models.functions import Coalesce, NullIf, Round
from WareDGT.services.cleaning import post_daily_record, reverse_posted_daily_record
from .utils.ethiopian_dates import to_ethiopian_date_str
from WareDGT.services.shipments import approve_load_request, AlreadyProcessed
from .utils.jsonsafe import json_safe

from .serializers import (
    WarehouseSerializer,
    PurchasedItemTypeSerializer,
    EcxMovementSerializer,
    ContractMovementSerializer,
    SeedTypeSerializer,
    SeedTypeDetailSerializer,
    BinCardSerializer,
    BinCardTransactionSerializer,
    DailyRecordSerializer,
    SeedTypeBalanceSerializer,
    BinCardEntrySerializer,
    StockOutSerializer,
)

from .models import (
    Company,
    SeedType,
    Warehouse,
    PurchaseOrder,
    StockMovement,
    QualityAnalysis,
    DailyRecord,
    BinCardEntry,
    BinCard,
    BinCardTransaction,
    LaborPayment,
    WeighbridgeSlipImage,
    UserProfile,
    Commodity,
    EcxTrade,
    EcxTradeReceiptFile,
    EcxTradeRequest,
    EcxTradeRequestFile,
    PurchasedItemType,
    SeedTypeDetail,
    EcxMovement,
    EcxMovementReceiptFile,
    EcxLoad,
    EcxLoadRequest,
    EcxLoadRequestReceiptFile,
    BinCardEntryRequest,
    SeedTypeBalance,
    StockOut,
    StockOutRequest,
    next_in_out_no,
    QualityCheck,
    PURITY_TOLERANCE,
    ContractMovement,
    ContractMovementRequest,
    EcxShipment,
)
from .forms import (
    PurchaseOrderForm,
    StockMovementForm,
    QualityAnalysisForm,
    DailyRecordForm,
    BinCardEntryForm,
    CleanedStockOutForm,
    LaborPaymentForm,
    SlipImageUploadForm,
    CommodityForm,
    EcxTradeForm,
    EcxTradeReceiptFileForm,
    EcxLoadForm,
    WarehouseForm,
    SeedTypeDetailForm,
    PurchasedItemTypeForm,
    UserEditForm,
    UserCreateForm,
    QualityCheckForm,
    ContractMovementForm,
    EcxMovementWeighForm,
    EcxShipmentWeighForm,
)
from .pdf_utils import (
    get_or_build_bincard_pdf,
    generate_ecxtrade_pdf,
)

logger = logging.getLogger(__name__)


def json_safe(obj):
    """Recursively convert any object to something json-serializable."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (UUID,)):
        return str(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    if isinstance(obj, UploadedFile):
        return getattr(obj, "name", None)
    if isinstance(obj, Model):
        return json_safe(getattr(obj, "pk", None))
    if isinstance(obj, QuerySet):
        return [json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    pk = getattr(obj, "pk", None)
    if pk is not None:
        return json_safe(pk)
    return str(obj)


# ----- Authentication Views -----
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.views import PasswordResetConfirmView

# ----- Simple role helpers (must be defined before use) -----
def _user_role(request):
    return getattr(getattr(request.user, "profile", None), "role", None)


def block_ecx_officer(view_func):
    """Decorator to block ECX officers from non-purchasing views.

    ECX officers should only access purchasing-related views. Apply this
    to any function-based view that is not part of purchasing.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        role = _user_role(request)
        if role == UserProfile.ECX_OFFICER:
            return HttpResponseForbidden(
                "ECX Officer can only access purchasing views."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        uname = request.POST.get("username")
        pwd = request.POST.get("password")
        user = authenticate(request, username=uname, password=pwd)
        if user:
            login(request, user)
            return redirect(request.GET.get("next", "dashboard"))
        messages.error(request, "Invalid credentials")

    return render(request, "WareDGT/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


# Customized password reset confirm view that logs out any active session
# before allowing the password to be set. This prevents a password setup
# link opened in an already authenticated browser session from altering the
# currently logged-in user's credentials or exposing the application's UI.
class PasswordSetupConfirmView(PasswordResetConfirmView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            logout(request)
        return super().dispatch(request, *args, **kwargs)


# ----- Dashboard -----
@login_required
def dashboard(request):
    today = timezone.localdate()
    prof = getattr(request.user, "profile", None)
    role = getattr(prof, "role", None)
    if not role:
        role = UserProfile.ADMIN if (getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)) else UserProfile.WAREHOUSE_OFFICER

    inbound_today = (
        StockMovement.objects.filter(
            movement_type=StockMovement.INBOUND, ticket_date=today
        ).aggregate(total=Sum("net_weight"))["total"]
        or 0
    )

    outbound_today = (
        StockMovement.objects.filter(
            movement_type=StockMovement.OUTBOUND, ticket_date=today
        ).aggregate(total=Sum("net_weight"))["total"]
        or 0
    )

    qc_failed = QualityAnalysis.objects.filter(first_purity_percent__lt=90).count()

    pending_pos = PurchaseOrder.objects.filter(status="PENDING").count()

    pending_qc = StockMovement.objects.filter(
        movement_type=StockMovement.INBOUND, qualityanalysis__isnull=True
    ).count()

    po_deadlines = PurchaseOrder.objects.filter(
        status="PENDING",
        pickup_deadline__lte=today + timedelta(days=3),
        pickup_deadline__gte=today,
    ).count()

    context = {
        "role": role,
        "inbound_today": inbound_today,
        "outbound_today": outbound_today,
        "qc_failed": qc_failed,
        "pending_pos": pending_pos,
        "pending_qc": pending_qc,
        "po_deadlines": po_deadlines,
    }
    return render(request, "WareDGT/dashboard.html", context)


@login_required
@block_ecx_officer
def ecx_console(request):
    """ECX Management Console with key metrics."""
    today = timezone.localdate()
    role = getattr(getattr(request.user, "profile", None), "role", None)

    todays_trades_qs = EcxTrade.objects.select_related("warehouse", "commodity")
    todays_trades_qs = todays_trades_qs.filter(purchase_date=today)
    upcoming_trade_qs = (
        EcxTrade.objects.select_related("warehouse", "commodity")
        .filter(loaded=False)
        .annotate(
            last_pickup=ExpressionWrapper(
                F("purchase_date") + timedelta(days=5), output_field=DateField()
            )
        )
        .filter(last_pickup__gte=today)
        .order_by("last_pickup")
    )
    overdue_trade_qs = (
        EcxTrade.objects.select_related("warehouse", "commodity")
        .filter(loaded=False)
        .annotate(
            last_pickup=ExpressionWrapper(
                F("purchase_date") + timedelta(days=5), output_field=DateField()
            )
        )
        .filter(last_pickup__lt=today)
    )

    if role == UserProfile.ECX_AGENT:
        allowed = request.user.profile.warehouses.all()
        todays_trades_qs = todays_trades_qs.filter(warehouse__in=allowed)
        upcoming_trade_qs = upcoming_trade_qs.filter(warehouse__in=allowed)
        overdue_trade_qs = overdue_trade_qs.filter(warehouse__in=allowed)

    todays_trades = todays_trades_qs.count()

    pending_settlements = PurchaseOrder.objects.filter(
        status="PENDING", purchase_date=today
    ).count()

    upcoming_pickups = upcoming_trade_qs.count()

    overdue_pickups = overdue_trade_qs.count()

    context = {
        "role": role,
        "todays_trades": todays_trades,
        "pending_settlements": pending_settlements,
        "upcoming_pickups": upcoming_pickups,
        "overdue_pickups": overdue_pickups,
        "todays_trade_list": todays_trades_qs,
        "upcoming_trade_list": upcoming_trade_qs,
        "overdue_trade_list": overdue_trade_qs,
    }
    return render(request, "WareDGT/ecx_console.html", context)


from django.http import HttpResponse
from django.contrib.auth.decorators import login_required

# Header stubs (already added earlier)
@login_required
@block_ecx_officer
def notifications(request):
    return HttpResponse("<h1>Notifications</h1><p>Coming soon…</p>")


@login_required
@block_ecx_officer
def borrowed_stocks(request):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
        return HttpResponseForbidden("Only Logistics/System Manager can view borrowed stocks.")
    # Filters
    borrower_q = (request.GET.get("borrower") or "").strip()
    owner_id = request.GET.get("owner") or ""
    warehouse_id = request.GET.get("warehouse") or ""
    seed = (request.GET.get("seed") or "").strip()
    stock_class = (request.GET.get("class") or "").strip()
    state = (request.GET.get("state") or "").strip()  # outstanding|returned|all

    qs = StockOutRequest.objects.filter(is_borrow=True).order_by("-created_at")
    if owner_id:
        qs = qs.filter(owner_id=owner_id)
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if stock_class:
        qs = qs.filter(models.Q(payload__stock_class=stock_class) | models.Q(payload__class=stock_class))
    if borrower_q:
        qs = qs.filter(
            models.Q(borrower__name__icontains=borrower_q)
            | models.Q(borrower_name__icontains=borrower_q)
        )
    outstanding = []
    history = []
    def seed_display(payload_seed):
        from uuid import UUID
        try:
            UUID(str(payload_seed))
            st = SeedTypeDetail.objects.filter(pk=payload_seed).first()
            if st: return f"{st.symbol}"
        except Exception:
            pass
        return str(payload_seed)
    total_outstanding_qtl = Decimal("0")
    borrower_names = set()
    for req in qs:
        qty_qtl = Decimal(str(req.payload.get("quantity") or 0))
        out_kg = req.borrowed_outstanding_kg or Decimal("0")
        out_qtl = (out_kg/Decimal("100")).quantize(Decimal("0.01"))
        if state == "outstanding" and out_qtl <= 0:
            continue
        if state == "returned" and out_qtl > 0:
            continue
        row = {
            "id": req.pk,
            "created_at": req.created_at,
            "owner": req.owner,
            "warehouse": req.warehouse,
            "seed_display": seed_display(req.payload.get("seed_type")),
            "stock_class": req.payload.get("stock_class"),
            "borrower_display": str(req.borrower) if req.borrower else (req.borrower_name or ""),
            "quantity_qtl": qty_qtl,
            "outstanding_qtl": out_qtl,
            "progress_pct": (float(qty_qtl - out_qtl)/float(qty_qtl) * 100) if qty_qtl > 0 else 100.0,
            "approval_token": req.approval_token,
        }
        borrower_names.add(row["borrower_display"]) if row["borrower_display"] else None
        if out_qtl > 0:
            outstanding.append(row)
            total_outstanding_qtl += out_qtl
        elif req.status in [StockOutRequest.APPROVED, StockOutRequest.RETURNED]:
            row["returned_qtl"] = (qty_qtl - out_qtl).quantize(Decimal("0.01"))
            history.append(row)
    # Choices for filters
    owners = Company.objects.order_by("name")
    warehouses = Warehouse.objects.filter(warehouse_type=Warehouse.DGT).order_by("name")
    summary = {
        "outstanding_qtl": total_outstanding_qtl.quantize(Decimal("0.01")),
        "borrowers": sorted([b for b in borrower_names if b])[:10],
        "count": len(outstanding),
    }
    return render(
        request,
        "WareDGT/borrowed_stocks.html",
        {
            "outstanding": outstanding,
            "history": history,
            "owners": owners,
            "warehouses": warehouses,
            "f_borrower": borrower_q,
            "f_owner": owner_id,
            "f_warehouse": warehouse_id,
            "f_seed": seed,
            "f_class": stock_class,
            "f_state": state or "outstanding",
            "summary": summary,
        },
    )


@login_required
@block_ecx_officer
def borrowed_stocks_export(request):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
        return HttpResponseForbidden()
    # Reuse the same filtering logic as borrowed_stocks() in a minimal way
    from io import StringIO
    import csv
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = "attachment; filename=borrowed_stocks.csv"
    # Build dataset
    request.GET = request.GET.copy()
    # Call the function to build rows but without rendering
    borrower_q = (request.GET.get("borrower") or "").strip()
    owner_id = request.GET.get("owner") or ""
    warehouse_id = request.GET.get("warehouse") or ""
    stock_class = (request.GET.get("class") or "").strip()
    state = (request.GET.get("state") or "").strip()
    qs = StockOutRequest.objects.filter(is_borrow=True).order_by("-created_at")
    if owner_id:
        qs = qs.filter(owner_id=owner_id)
    if warehouse_id:
        qs = qs.filter(warehouse_id=warehouse_id)
    if stock_class:
        qs = qs.filter(models.Q(payload__stock_class=stock_class) | models.Q(payload__class=stock_class))
    if borrower_q:
        qs = qs.filter(models.Q(borrower__name__icontains=borrower_q) | models.Q(borrower_name__icontains=borrower_q))
    w = csv.writer(resp)
    w.writerow(["Created", "Owner", "Warehouse", "Seed", "Class", "Borrower", "Requested (qtl)", "Outstanding (qtl)", "Status"]) 
    for req in qs:
        qty_qtl = Decimal(str(req.payload.get("quantity") or 0))
        out_qtl = (Decimal(req.borrowed_outstanding_kg or 0) / Decimal("100")).quantize(Decimal("0.01"))
        if state == "outstanding" and out_qtl <= 0:
            continue
        if state == "returned" and out_qtl > 0:
            continue
        seed_value = req.payload.get("seed_type")
        seed_str = str(seed_value)
        w.writerow([
            request.build_absolute_uri("") and req.created_at.isoformat(),
            str(req.owner),
            str(req.warehouse),
            seed_str,
            req.payload.get("stock_class"),
            str(req.borrower) if req.borrower else (req.borrower_name or ""),
            str(qty_qtl),
            str(out_qtl),
            req.get_status_display(),
        ])
    return resp


@login_required
@block_ecx_officer
def messages_view(request):
    return HttpResponse("<h1>Messages</h1><p>Coming soon…</p>")



# Sidebar stubs (legacy; restrict for ECX)
@login_required
@block_ecx_officer
def stock_movements(request):
    # Aggregate ECX movements by truck/shipment if available
    role = getattr(getattr(request.user, "profile", None), "role", None)
    movements = (
        EcxMovement.objects.all()
        .select_related("warehouse", "item_type", "shipment")
        .order_by("-created_at")
    )
    if role == UserProfile.WEIGHBRIDGE_OPERATOR:
        movements = movements.filter(weighed=False)
    elif role == UserProfile.ECX_AGENT:
        movements = movements.none()
    shipments = (
        EcxShipment.objects.all()
        .select_related("warehouse", "created_by")
        .prefetch_related("movements", "movements__item_type", "movements__receipt_files")
        .order_by("-created_at")
    )
    if role == UserProfile.WEIGHBRIDGE_OPERATOR:
        shipments = shipments.filter(movements__weighed=False).distinct()
    elif role == UserProfile.ECX_AGENT:
        shipments = shipments.none()
    shipments_data = []
    def _is_image(name: str) -> bool:
        n = (name or "").lower()
        return n.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))

    for sh in shipments:
        mvs = list(sh.movements.all())
        if not mvs:
            continue
        # collect distinct item_type codes and grades for display
        codes = []
        for mv in mvs:
            c = str(mv.item_type)
            if c not in codes:
                codes.append(c)
        # collect unique NORs and WRs
        def split_nums(s):
            parts = []
            for p in (s or "").split(","):
                p = p.strip()
                if p and p not in parts:
                    parts.append(p)
            return parts
        nors, wrs = [], []
        for mv in mvs:
            nors.extend(split_nums(mv.net_obligation_receipt_no))
            wrs.extend(split_nums(mv.warehouse_receipt_no))
        # de-dup while preserving order
        seen = set(); nors = [x for x in nors if not (x in seen or seen.add(x))]
        seen = set(); wrs = [x for x in wrs if not (x in seen or seen.add(x))]
        # Collect receipt files attached during loading across all movements
        image_urls = []
        file_urls = []
        for mv in mvs:
            for rf in mv.receipt_files.all():
                try:
                    url = rf.image.url
                except Exception:
                    continue
                if _is_image(getattr(rf.image, "name", url)):
                    image_urls.append(url)
                else:
                    file_urls.append(url)

        # Fallback vehicle details from the originating load request (if any)
        lr = getattr(sh, 'load_requests', None)
        lr_obj = None
        try:
            lr_obj = lr.order_by('-created_at').first() if lr is not None else None
        except Exception:
            lr_obj = None
        truck_plate = sh.truck_plate_no or (getattr(lr_obj, 'truck_plate_no', '') or '')
        trailer_plate = sh.trailer_plate_no or (getattr(lr_obj, 'trailer_plate_no', '') or '')
        try:
            ship_img_url = sh.truck_image.url if sh.truck_image else None
        except Exception:
            ship_img_url = None
        if not ship_img_url and lr_obj and getattr(lr_obj, 'truck_image', None):
            try:
                ship_img_url = lr_obj.truck_image.url
            except Exception:
                ship_img_url = None

        shipments_data.append(
            {
                "id": sh.id,
                "warehouse": sh.warehouse,
                "item_types": ", ".join(codes),
                "net_obligation_receipt_no": ", ".join(nors),
                "warehouse_receipt_no": ", ".join(wrs),
                "quantity_quintals": sum([mv.quantity_quintals for mv in mvs]) if mvs else 0,
                "purchase_date": min([mv.purchase_date for mv in mvs]) if mvs else None,
                "images": image_urls,
                "files": file_urls,
                "truck_image": ship_img_url,
                "truck_plate": truck_plate,
                "trailer_plate": trailer_plate,
            }
        )
    contract_in_transit = (
        ContractMovement.objects.filter(status=ContractMovement.IN_TRANSIT)
        .select_related("owner")
        .order_by("-created_at")
    )
    return render(
        request,
        "WareDGT/ecxmovement_list.html",
        {
            "object_list": movements,
            "contract_list": contract_in_transit,
            "shipments": shipments_data,
            "role": role,
        },
    )


@login_required
def ecx_movement_weigh(request, pk):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.WEIGHBRIDGE_OPERATOR, UserProfile.ADMIN]:
        return HttpResponseForbidden("You do not have permission to access this page.")
    movement = get_object_or_404(EcxMovement, pk=pk, weighed=False)
    if request.method == "POST":
        form = EcxMovementWeighForm(request.POST, request.FILES, instance=movement)
        if form.is_valid():
            form.save()
            messages.success(request, "Weighbridge data recorded.")
            return redirect("stock_movements")
    else:
        form = EcxMovementWeighForm(instance=movement)
    # Safe vehicle context for template (no attribute errors)
    shipment = getattr(movement, 'shipment', None)
    lr_obj = None
    if shipment is not None:
        try:
            lr_obj = shipment.load_requests.order_by('-created_at').first()
        except Exception:
            lr_obj = None
    def _safe_file_url(f):
        try:
            return f.url if f else None
        except Exception:
            return None
    ctx = {
        "form": form,
        "movement": movement,
        "veh_truck_plate": getattr(shipment, 'truck_plate_no', '') or (getattr(lr_obj, 'truck_plate_no', '') or ''),
        "veh_trailer_plate": getattr(shipment, 'trailer_plate_no', '') or (getattr(lr_obj, 'trailer_plate_no', '') or ''),
        "veh_truck_image": _safe_file_url(getattr(shipment, 'truck_image', None)) or _safe_file_url(getattr(lr_obj, 'truck_image', None)),
    }
    return render(request, "WareDGT/ecxmovement_weigh.html", ctx)


@login_required
def ecx_shipment_weigh(request, pk):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.WEIGHBRIDGE_OPERATOR, UserProfile.ADMIN]:
        return HttpResponseForbidden("You do not have permission to access this page.")
    shipment = get_object_or_404(EcxShipment, pk=pk)
    movements = list(shipment.movements.filter(weighed=False))
    if not movements:
        return HttpResponseBadRequest("All movements already weighed.")
    if request.method == "POST":
        form = EcxShipmentWeighForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["weighbridge_certificate"]
            data = file.read()
            for mv in movements:
                mv.weighbridge_certificate.save(file.name, ContentFile(data), save=False)
                if not mv.loaded:
                    mv.loaded = True
                    mv.loaded_at = timezone.now()
                if not mv.weighed:
                    mv.weighed = True
                    mv.weighed_at = timezone.now()
                mv.save()
            messages.success(request, "Weighbridge data recorded.")
            return redirect("stock_movements")
    else:
        form = EcxShipmentWeighForm()
    # Safe vehicle details for template
    lr_obj = None
    try:
        lr_obj = shipment.load_requests.order_by('-created_at').first()
    except Exception:
        lr_obj = None
    def _safe_url(f):
        try:
            return f.url if f else None
        except Exception:
            return None
    ctx = {
        "form": form,
        "shipment": shipment,
        "veh_truck_plate": shipment.truck_plate_no or (getattr(lr_obj, 'truck_plate_no', '') or ''),
        "veh_trailer_plate": shipment.trailer_plate_no or (getattr(lr_obj, 'trailer_plate_no', '') or ''),
        "veh_truck_image": _safe_url(getattr(shipment, 'truck_image', None)) or _safe_url(getattr(lr_obj, 'truck_image', None)),
    }
    return render(request, "WareDGT/ecxshipment_weigh.html", ctx)


@login_required
@block_ecx_officer
def contract_movements(request):
    """Logistics Manager page to register and manage Contract Farming stocks in movement."""
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
        return HttpResponseForbidden("Only Logistics Manager or Admin can access this page.")

    if request.method == "POST":
        form = ContractMovementForm(request.POST, request.FILES)
        if form.is_valid():
            # Directly create the ContractMovement without accountant approval
            mv = form.save(commit=False)
            mv.created_by = request.user
            mv.save()
            messages.success(request, "Contract stock registered.")
            return redirect("contract_movement_list")
        else:
            messages.error(request, "Fix the errors in the form.")
    else:
        form = ContractMovementForm()

    # Only show records that are still in transit; consumed ones should
    # disappear from this page once registered into a bin card.
    qs = (
        ContractMovement.objects.filter(status=ContractMovement.IN_TRANSIT)
        .select_related("owner")
        .order_by("-created_at")
    )
    return render(
        request,
        "WareDGT/contract_movement_list.html",
        {"form": form, "object_list": qs},
    )


def _notify_accountants_contract_request(request, payload):
    cmr = (
        ContractMovementRequest.objects.filter(created_by=request.user)
        .order_by("-created_at")
        .first()
    )
    if not cmr:
        return
    accountants = (
        User.objects.filter(profile__role=UserProfile.ACCOUNTANT, is_active=True)
        .values_list("email", flat=True)
    )
    if not accountants:
        return
    review_url = request.build_absolute_uri(
        reverse("contract_movement_request_review", args=[str(cmr.pk)])
        + f"?t={cmr.approval_token}"
    )
    ctx = {"payload": payload, "review_url": review_url, "cmr": cmr}
    subject = "[Action Required] Contract Stock Approval"
    html = render_to_string("emails/contract_movement_request.html", ctx)
    text = render_to_string("emails/contract_movement_request.txt", ctx)
    mail = EmailMultiAlternatives(
        subject, text, settings.DEFAULT_FROM_EMAIL, list(accountants)
    )
    mail.attach_alternative(html, "text/html")
    mail.send(fail_silently=False)


def _notify_submitter_declined(cmr: ContractMovementRequest):
    if not cmr.created_by.email:
        return
    ctx = {"cmr": cmr}
    subject = "Contract Stock Declined"
    html = render_to_string("emails/contract_movement_declined.html", ctx)
    text = render_to_string("emails/contract_movement_declined.txt", ctx)
    mail = EmailMultiAlternatives(
        subject, text, settings.DEFAULT_FROM_EMAIL, [cmr.created_by.email]
    )
    mail.attach_alternative(html, "text/html")
    mail.send(fail_silently=False)


@login_required
@block_ecx_officer
def daily_records(request):
    """Display form and operation logs with optional date filtering."""

    form = DailyRecordForm()

    # Logistics Manager: view-only; block creates/edits
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role == UserProfile.OPERATIONS_MANAGER and request.method == "POST":
        return HttpResponseForbidden("Logistics Manager has view-only access to Daily Records.")

    if request.method == "POST":
        form = DailyRecordForm(request.POST)
        logger.info("daily_records POST")
        if form.is_valid():
            record = form.save(commit=False)
            if request.user.is_authenticated:
                record.recorded_by = request.user
            record.save()
            record.pieces = record.quality_checks.count()
            record.save(update_fields=['pieces'])
            messages.success(request, "Draft saved")
            return redirect("daily_records")
        else:
            logger.error("DailyRecord invalid: %s", form.errors.as_json())
            messages.error(request, "Fix the errors in Daily Record form.")
    today = timezone.now().date()
    weight_in = F("weight_in")
    weight_out = F("weight_out")
    rejects = F("rejects")
    purity_in = F("purity_before")
    purity_out = F("purity_after")
    den = NullIf(weight_in, Value(0))

    # Default view: current month, anchored to today
    period = request.GET.get("period") or "month"
    ref_str = request.GET.get("start")
    ref_date = today
    if ref_str:
        try:
            ref_date = datetime.strptime(ref_str, "%Y-%m-%d").date()
        except ValueError:
            ref_str = ""

    qs = DailyRecord.objects.all()
    # Helper: apply a date window to either the record's business date or created_at date
    def apply_window(qs_in, start_d, end_d):
        return qs_in.filter(Q(date__range=(start_d, end_d)) | Q(created_at__date__range=(start_d, end_d)))

    # If a start date is supplied but no period chosen, treat it as the selected day
    if period == "all" and ref_str:
        qs = apply_window(qs, ref_date, ref_date)
    elif period != "all":
        end_range = ref_date
        if period == "day":
            start_range = ref_date
        elif period == "week":
            # Interpret provided ref_date as the week's start (e.g., Monday)
            start_range = ref_date
            end_range = ref_date + timedelta(days=6)
        elif period == "month":
            # Full month window for the month containing ref_date
            start_range = ref_date.replace(day=1)
            days_in_month = monthrange(ref_date.year, ref_date.month)[1]
            end_range = ref_date.replace(day=days_in_month)
        elif period == "year":
            # Full calendar year of ref_date
            start_range = ref_date.replace(month=1, day=1)
            end_range = ref_date.replace(month=12, day=31)
        else:
            start_range = ref_date
        qs = apply_window(qs, start_range, end_range)

    # Item filters (owner/seed/status/op) removed for now; focusing on date filters

    records_qs = (
        qs.select_related(
            "owner",
            "recorded_by",
            "lot",
            "lot__owner",
            "lot__seed_type",
        ).order_by("-created_at")
    )

    records = list(records_qs)
    for r in records:
        # Build QC rows with cumulative cleaned-out at each instant
        rows = []
        cumulative_out = Decimal("0.00")
        for qc in r.quality_checks.all():
            piece = Decimal(qc.piece_quintals or 0)
            purity = Decimal(qc.purity_percent or 0)
            # Estimated cleaned for this piece = piece * purity%
            piece_out = (piece * purity / Decimal("100")) if piece and purity else Decimal("0.00")
            piece_out = piece_out.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cumulative_out = (cumulative_out + piece_out).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            rows.append(
                {
                    "amount": qc.piece_quintals,
                    "weight_out": cumulative_out,
                    "purity": qc.purity_percent,
                    "time": qc.timestamp,
                }
            )
        r.qc_rows = rows
        cleaning_cost = (
            (r.labor_rate_per_qtl or Decimal("0")) * (r.weight_in or Decimal("0"))
        )
        r.total_labor_cost = (
            cleaning_cost + (r.labor_cost or Decimal("0"))
        ).quantize(Decimal("0.01"))

    # Owner/Seed/Status/Operation dropdowns removed — no options context needed

    # Choose a friendly default for the visible start field
    if not ref_str and period == "month":
        start_visible = today.replace(day=1)
    else:
        start_visible = ref_date

    context = {
        "form": form,
        "records": records,
        "period": period,
        # Show first of month when period is Month and no explicit start was provided
        "start": start_visible,
    }
    return render(request, "WareDGT/daily_records.html", context)


@login_required
def load_seed_types(request):
    owner_id = request.GET.get("owner")
    # List seed types present in DailyRecord for given owner, then fall back to BinCardEntry,
    # and finally to all SeedTypeDetail if still empty.
    if owner_id:
        seed_ids = list(
            DailyRecord.objects.filter(owner_id=owner_id)
            .values_list("seed_type_id", flat=True)
            .distinct()
        )
        if not seed_ids:
            seed_ids = list(
                BinCardEntry.objects.filter(owner_id=owner_id)
                .values_list("seed_type_id", flat=True)
                .distinct()
            )
    else:
        seed_ids = list(
            DailyRecord.objects.values_list("seed_type_id", flat=True).distinct()
        )
        if not seed_ids:
            seed_ids = list(
                BinCardEntry.objects.values_list("seed_type_id", flat=True).distinct()
            )
    qs = (
        SeedTypeDetail.objects.filter(id__in=seed_ids).order_by("symbol")
        if seed_ids
        else SeedTypeDetail.objects.order_by("symbol")
    )
    types = [{"id": t.id, "name": str(t)} for t in qs]
    return JsonResponse({"seed_types": types})


@login_required
def load_lots(request):
    owner_id = request.GET.get("owner")
    seed_id = request.GET.get("seed_type")
    op_type = request.GET.get("operation_type")
    lots = []
    if owner_id and seed_id:
        qs = BinCardEntry.objects.filter(owner_id=owner_id, seed_type_id=seed_id)
        if op_type == DailyRecord.CLEANING:
            # Allow selecting lots that still have unprocessed raw balance,
            # even if they have been partially cleaned before.
            qs = qs.filter(raw_weight_remaining__gt=0, weight__gt=0)
        elif op_type == DailyRecord.RECLEANING:
            qs = qs.filter(cleaned_weight__gt=0)
        lots = [{"id": l.id, "name": l.in_out_no} for l in qs]
    return JsonResponse({"lots": lots})


@login_required
def lot_details(request):
    lot_id = request.GET.get("lot")
    data = {}
    if lot_id:
        try:
            lot = BinCardEntry.objects.get(pk=lot_id)
            data = {
                "weight_in": float(lot.raw_weight_remaining),
                "purity": float(lot.purity),
            }
        except BinCardEntry.DoesNotExist:
            pass
    return JsonResponse(data)


@login_required
@require_POST
def dailyrecord_reject_weighing(request, pk):
    # Logistics Manager: view-only; block edits
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role == UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden("Logistics Manager cannot modify records.")

    rec = get_object_or_404(DailyRecord, pk=pk)
    if rec.is_posted:
        return HttpResponseBadRequest("Record already posted.")
    if rec.status != DailyRecord.STATUS_DRAFT:
        return HttpResponseBadRequest("Record not in DRAFT.")

    actual = Decimal(request.POST.get("actual_reject_weight", "0"))
    if actual <= 0:
        return HttpResponseBadRequest("Reject weight must be positive.")

    rec.actual_reject_weight = actual
    rec.compute_estimations()
    rec.rejects = actual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rec.weight_out = (
        Decimal(rec.weight_in) - rec.rejects
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rec.weight_out < 0:
        rec.weight_out = Decimal("0.00")

    rate = request.POST.get("labor_rate_per_qtl")
    payment_rate = request.POST.get("reject_labor_payment_per_qtl")
    if rate is not None:
        rec.labor_rate_per_qtl = Decimal(rate)
    if payment_rate is not None:
        rec.reject_labor_payment_per_qtl = Decimal(payment_rate)

    reject_labor_cost = (
        (rec.reject_labor_payment_per_qtl or Decimal("0")) * actual
    ).quantize(Decimal("0.01"))
    rec.labor_cost = (rec.labor_cost or Decimal("0")) + reject_labor_cost

    # Save computed fields and reject weighing metadata first.
    # Do NOT mark as POSTED here; posting service performs validations,
    # updates bin-card balances and sets status/is_posted atomically.
    rec.reject_weighed_by = request.user
    rec.reject_weighed_at = timezone.now()

    rec.save(
        update_fields=[
            "actual_reject_weight",
            "expected_reject_weight",
            "combined_expected_reject_weight",
            "deviation_pct",
            "is_fishy",
            "rejects",
            "weight_out",
            "labor_rate_per_qtl",
            "reject_labor_payment_per_qtl",
            "labor_cost",
            "reject_weighed_by",
            "reject_weighed_at",
        ]
    )

    # Post the record (creates transactions and updates lot balances)
    rec = rec.post(request.user)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        # Return updated totals, including labor cost summary for UI
        cleaning_cost = (
            (rec.labor_rate_per_qtl or Decimal("0")) * (rec.weight_in or Decimal("0"))
        )
        total_labor_cost = (cleaning_cost + (rec.labor_cost or Decimal("0"))).quantize(
            Decimal("0.01")
        )
        return JsonResponse(
            {
                "ok": True,
                "weight_out": float(rec.weight_out or 0),
                "rejects": float(rec.rejects or 0),
                "status": rec.status,
                "total_labor_cost": float(total_labor_cost),
            }
        )
    messages.success(request, "Reject recorded, record posted.")
    return redirect("daily_records")


# Removed daily_record_receipt endpoint per requirement


# Removed start/stop/progress endpoints; hourly purity drives updates


@login_required
@block_ecx_officer
def bincard_pdf_view(request, entry_id):
    entry = get_object_or_404(BinCardEntry, pk=entry_id)
    # Allow forcing a rebuild via query param to refresh cached PDFs after logic changes.
    if request.GET.get("rebuild"):
        entry.pdf_dirty = True
        entry.save(update_fields=["pdf_dirty"])
    filefield = get_or_build_bincard_pdf(entry, request.user)
    return FileResponse(
        filefield.open("rb"),
        filename=f"bincard_{entry.pk}.pdf",
        as_attachment=False,
    )


@login_required
@block_ecx_officer
def add_qc(request, pk):
    # Logistics Manager: view-only; block edits
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role == UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden("Logistics Manager cannot modify records.")

    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    rec = get_object_or_404(DailyRecord, pk=pk)
    if rec.is_posted:
        return HttpResponseForbidden("Record already posted")
    if rec.operation_type not in {DailyRecord.CLEANING, DailyRecord.RECLEANING}:
        return HttpResponseBadRequest("Operation not allowed")

    form = QualityCheckForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    new_piece = form.cleaned_data['piece_quintals']
    consumed = rec.quality_checks.aggregate(s=Sum('piece_quintals'))['s'] or 0
    # Respect partial-cleaning intent: cap QC consumption by the record's weight_in
    lot_total = getattr(rec.lot, 'raw_weight_remaining', None)
    # Prefer explicit record cap when cleaning/recleaning; fall back to lot balance
    lot_balance = rec.weight_in if rec.weight_in else lot_total
    if lot_total is not None and lot_balance is not None:
        # Do not allow consuming more than the physical lot remainder
        lot_balance = min(lot_total, lot_balance)

    if consumed + new_piece > lot_balance:
        remaining = lot_balance - consumed
        return JsonResponse(
            {
                "ok": False,
                "no_more_stock": True,
                "consumed_quintals": float(consumed),
                "remaining_quintals": float(max(remaining, Decimal("0"))),
            },
            status=409,
        )

    qc = form.save(commit=False)
    qc.daily_record = rec
    qc.save()

    qs = list(rec.quality_checks.all())
    total_piece = Decimal('0')
    total_sound = Decimal('0')
    total_reject = Decimal('0')
    wsum = Decimal('0')
    for q in qs:
        total_piece += q.piece_quintals
        total = (q.weight_sound_g or 0) + (q.weight_reject_g or 0)
        if total:
            sound_frac = Decimal(q.weight_sound_g) / Decimal(total)
            reject_frac = Decimal(q.weight_reject_g) / Decimal(total)
            total_sound += q.piece_quintals * sound_frac
            total_reject += q.piece_quintals * reject_frac
            wsum += Decimal(q.purity_percent) * q.piece_quintals
    rec.purity_after = (wsum / total_piece) if total_piece else None
    rec.weight_out = total_sound
    rec.rejects = total_reject
    rec.pieces = len(qs)
    rec.save(update_fields=['purity_after', 'weight_out', 'rejects', 'pieces'])
    remaining = lot_balance - total_piece
    if remaining <= Decimal("0"):
        next_piece = Decimal("0")
    elif remaining < Decimal("50"):
        next_piece = remaining
    else:
        next_piece = Decimal("50")

    return JsonResponse(
        {
            "ok": True,
            "c_number": f"C-{qc.index}",
            "purity_after": float(rec.purity_after or 0),
            "pieces": rec.pieces,
            "weight_out": float(rec.weight_out or 0),
            "rejects": float(rec.rejects or 0),
            "consumed_quintals": float(total_piece),
            "remaining_quintals": float(max(remaining, Decimal('0'))),
            "next_piece": float(next_piece),
            "no_more_stock": False,
        }
    )
  

@login_required
@block_ecx_officer
@require_POST
def add_hourly_purity(request, pk):
    """Add a single hourly QC entry by purity percent only.

    - Defaults to 50.00 qtl piece and 30g sample, 50 kg/h rate.
    - Enforces remaining-cap like add_qc.
    - Updates record's purity_after, weight_out, rejects, and pieces.
    """
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role == UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden("Logistics Manager cannot modify records.")

    rec = get_object_or_404(DailyRecord, pk=pk)
    if rec.is_posted:
        return HttpResponseForbidden("Record already posted")
    if rec.operation_type not in {DailyRecord.CLEANING, DailyRecord.RECLEANING}:
        return HttpResponseBadRequest("Operation not allowed")

    try:
        purity = Decimal(request.POST.get("purity"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid purity"}, status=400)
    if purity < 0 or purity > 100:
        return JsonResponse({"ok": False, "error": "Purity must be 0..100"}, status=400)

    # Optional overrides
    try:
        piece = Decimal(request.POST.get("piece") or "50.00")
        sample = Decimal(request.POST.get("sample") or "30.00")
        rate = Decimal(request.POST.get("rate") or "50.00")
    except Exception:
        return JsonResponse({"ok": False, "error": "Invalid numeric fields"}, status=400)
    if piece <= 0 or sample <= 0:
        return JsonResponse({"ok": False, "error": "Piece and sample must be positive"}, status=400)

    consumed = rec.quality_checks.aggregate(s=Sum('piece_quintals'))['s'] or Decimal('0')
    lot_total = getattr(rec.lot, 'raw_weight_remaining', None)
    lot_balance = rec.weight_in if rec.weight_in else lot_total
    if lot_total is not None and lot_balance is not None:
        lot_balance = min(lot_total, lot_balance)

    if lot_balance is None:
        lot_balance = rec.weight_in or Decimal('0')

    remaining = (lot_balance - consumed)
    if remaining <= Decimal('0'):
        return JsonResponse({"ok": False, "no_more_stock": True, "remaining_quintals": 0.0}, status=409)

    # Cap piece to remaining (so last hour may be <50)
    use_piece = piece if piece <= remaining else remaining

    # Convert purity% into sample sound/reject weights (g)
    weight_sound_g = (sample * purity / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    weight_reject_g = (sample - weight_sound_g).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    qc = QualityCheck.objects.create(
        daily_record=rec,
        sample_weight_g=sample,
        piece_quintals=use_piece,
        machine_rate_kgph=rate,
        weight_sound_g=weight_sound_g,
        weight_reject_g=weight_reject_g,
    )

    # Recompute aggregated purity/weights like add_qc
    qs = list(rec.quality_checks.all())
    total_piece = Decimal('0')
    total_sound = Decimal('0')
    total_reject = Decimal('0')
    wsum = Decimal('0')
    for q in qs:
        total_piece += q.piece_quintals
        total = (q.weight_sound_g or 0) + (q.weight_reject_g or 0)
        if total:
            sound_frac = Decimal(q.weight_sound_g) / Decimal(total)
            reject_frac = Decimal(q.weight_reject_g) / Decimal(total)
            total_sound += q.piece_quintals * sound_frac
            total_reject += q.piece_quintals * reject_frac
            wsum += Decimal(q.purity_percent) * q.piece_quintals
    rec.purity_after = (wsum / total_piece) if total_piece else None
    rec.weight_out = total_sound
    rec.rejects = total_reject
    rec.pieces = len(qs)
    rec.save(update_fields=['purity_after', 'weight_out', 'rejects', 'pieces'])

    remaining = (lot_balance - total_piece)
    if remaining <= Decimal("0"):
        next_piece = Decimal("0")
    elif remaining < Decimal("50"):
        next_piece = remaining
    else:
        next_piece = Decimal("50")

    return JsonResponse(
        {
            "ok": True,
            "c_number": f"C-{qc.index}",
            "purity_after": float(rec.purity_after or 0),
            "pieces": rec.pieces,
            "weight_out": float(rec.weight_out or 0),
            "rejects": float(rec.rejects or 0),
            "consumed_quintals": float(total_piece),
            "remaining_quintals": float(max(remaining, Decimal('0'))),
            "next_piece": float(next_piece),
            "piece_used": float(use_piece),
            "purity": float(purity),
            "timestamp": timezone.now().isoformat(),
            "no_more_stock": False,
        }
    )


@login_required
@block_ecx_officer
def purchase_orders(request):
    return HttpResponse("<h1>Purchase Orders</h1><p>Coming soon…</p>")

@login_required
@block_ecx_officer
def bin_cards(request):
    owners = None
    role = getattr(getattr(request.user, "profile", None), "role", None)
    # Logistics Manager: view-only; block creates/edits
    if role == UserProfile.OPERATIONS_MANAGER and request.method == "POST":
        return HttpResponseForbidden("Logistics Manager has view-only access to Bin Cards.")
    if request.method == "POST":
        if "register_out" in request.GET:
            form = CleanedStockOutForm(request.POST, request.FILES)
            owners = Company.objects.order_by("name")
            if form.is_valid():
                if role == UserProfile.WAREHOUSE_OFFICER:
                    direction = "IN" if request.GET.get("register") else "OUT"
                    cd = form.cleaned_data
                    wh_val = cd.get("warehouse")
                    warehouse_obj = (
                        wh_val
                        if isinstance(wh_val, Warehouse)
                        else Warehouse.objects.get(pk=getattr(wh_val, "pk", wh_val))
                    )
                    payload = json_safe(cd)
                    req = BinCardEntryRequest.objects.create(
                        created_by=request.user,
                        approval_token=get_random_string(48),
                        payload=payload,
                        warehouse=warehouse_obj,
                        direction=direction,
                        warehouse_document=cd.get("warehouse_document"),
                        weighbridge_certificate=cd.get("weighbridge_certificate"),
                    )
                    _notify_bincard_managers(request, req)
                    messages.success(request, f"Draft ({direction}) created and sent to Logistics Manager.")
                    return redirect("bin_cards")
                form.save(user=request.user)
                messages.success(request, "Outbound stock recorded.")
                return redirect("bin_cards")
        else:
            form = BinCardEntryForm(request.POST, request.FILES)
            if form.is_valid():
                if role == UserProfile.WAREHOUSE_OFFICER:
                    direction = "IN" if request.GET.get("register") else "OUT"
                    cd = form.cleaned_data
                    cd["seed_type"] = getattr(form, "seed_detail", None)
                    mv = cd.get("ecx_movement")
                    if mv:
                        cd["grade"] = getattr(getattr(mv, "item_type", None), "grade", "")
                    if not cd.get("description"):
                        src = cd.get("source_type")
                        cd["description"] = (
                            "ECX stock in for Export"
                            if src == BinCardEntry.ECX
                            else ("Local purchase stock in" if src == BinCardEntry.LOCAL else "Contract farming stock in for Export")
                        )
                    # Attach idempotency key to payload to deduplicate rapid re-submits
                    idem_key = request.POST.get("idempotency_key") or get_random_string(24)
                    cd["idempotency_key"] = idem_key
                    payload = json_safe(cd)
                    wh_val = cd.get("warehouse")
                    warehouse_obj = (
                        wh_val
                        if isinstance(wh_val, Warehouse)
                        else Warehouse.objects.get(pk=getattr(wh_val, "pk", wh_val))
                    )
                    # If same idempotency_key pending from this user, do not duplicate
                    existing = BinCardEntryRequest.objects.filter(
                        created_by=request.user,
                        status=BinCardEntryRequest.PENDING,
                        direction=direction,
                        payload__idempotency_key=idem_key,
                    ).first()
                    if existing:
                        messages.success(request, "Draft already submitted and pending approval.")
                        return redirect("bin_cards")
                    req = BinCardEntryRequest.objects.create(
                        created_by=request.user,
                        approval_token=get_random_string(48),
                        payload=payload,
                        warehouse=warehouse_obj,
                        direction=direction,
                        weighbridge_certificate=cd.get("weighbridge_certificate"),
                        warehouse_document=cd.get("warehouse_document"),
                        quality_form=cd.get("quality_form"),
                    )
                    _notify_bincard_managers(request, req)
                    messages.success(
                        request,
                        f"Draft ({direction}) created and sent to Logistics Manager.",
                    )
                    return redirect("bin_cards")
                entry = form.save()
                get_or_build_bincard_pdf(entry, request.user)
                messages.success(request, "Bin card entry recorded.")
                return redirect("bin_cards")
    else:
        if "register_out" in request.GET and role != UserProfile.OPERATIONS_MANAGER:
            form = CleanedStockOutForm()
            owners = Company.objects.order_by("name")
        elif "register" in request.GET and role != UserProfile.OPERATIONS_MANAGER:
            form = BinCardEntryForm()
            # Provide idempotency key to prevent double-submit duplicates
            request._bincard_idem = get_random_string(24)
        else:
            form = None

    # ---- Filters (server-side) ----
    from django.core.paginator import Paginator
    from django.utils.dateparse import parse_date
    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    owner_id = request.GET.get("owner")
    warehouse_id = request.GET.get("warehouse")
    owner_name = request.GET.get("owner_name")
    warehouse_name = request.GET.get("warehouse_name")
    seed_symbol = request.GET.get("seed")
    grade = request.GET.get("grade")
    inout_no = request.GET.get("io")
    # Default to last 10 entries on a fresh page load with no filters
    is_default_view = not any([
        start_str,
        end_str,
        request.GET.get("owner"),
        request.GET.get("warehouse"),
        request.GET.get("owner_name"),
        request.GET.get("warehouse_name"),
        request.GET.get("seed"),
        request.GET.get("grade"),
        request.GET.get("io"),
    ]) and ("register" not in request.GET and "register_out" not in request.GET)

    per_default = 10 if is_default_view else 100
    per = max(1, int(request.GET.get("per", str(per_default)) or per_default))
    page_no = max(1, int(request.GET.get("p", "1") or 1))
    go_last_page = is_default_view and ("p" not in request.GET)

    entries_qs = (
        BinCardEntry.objects.select_related(
            "owner",
            "seed_type",
            "ecx_movement__item_type",
            "ecx_movement__warehouse",
        )
        .prefetch_related("ecx_movement__receipt_files")
        .order_by("date", "id")
    )

    # Date filter is fully optional: if no dates are provided, do not limit.
    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None
    if start_date:
        entries_qs = entries_qs.filter(date__gte=start_date)
    if end_date:
        entries_qs = entries_qs.filter(date__lte=end_date)
    # Owner/Warehouse can arrive as UUID or as human name. Resolve gracefully.
    from uuid import UUID
    def _resolve_owner(val, by_name=None):
        if not val and not by_name:
            return None, None
        # Prefer explicit name param
        if by_name:
            oid = (
                Company.objects.filter(name__iexact=by_name)
                .values_list("id", flat=True)
                .first()
            )
            return (str(oid) if oid else None, by_name)
        # Try UUID, else treat as name
        try:
            UUID(str(val))
            return str(val), Company.objects.filter(id=val).values_list("name", flat=True).first() or None
        except Exception:
            oid = (
                Company.objects.filter(name__iexact=val)
                .values_list("id", flat=True)
                .first()
            )
            return (str(oid) if oid else None, val)

    def _resolve_warehouse(val, by_name=None):
        if not val and not by_name:
            return None, None
        if by_name:
            wid = (
                Warehouse.objects.filter(name__iexact=by_name, warehouse_type=Warehouse.DGT)
                .values_list("id", flat=True)
                .first()
            )
            return (str(wid) if wid else None, by_name)
        from uuid import UUID as _UUID
        try:
            _UUID(str(val))
            nm = (
                Warehouse.objects.filter(id=val)
                .values_list("name", flat=True)
                .first()
            )
            return str(val), nm
        except Exception:
            wid = (
                Warehouse.objects.filter(name__iexact=val, warehouse_type=Warehouse.DGT)
                .values_list("id", flat=True)
                .first()
            )
            return (str(wid) if wid else None, val)

    owner_id, owner_name_resolved = _resolve_owner(owner_id, by_name=owner_name)
    warehouse_id, warehouse_name_resolved = _resolve_warehouse(warehouse_id, by_name=warehouse_name)
    # Keep selected names for sticky filter UI
    if not owner_name:
        owner_name = owner_name_resolved
    if not warehouse_name:
        warehouse_name = warehouse_name_resolved

    if owner_id:
        entries_qs = entries_qs.filter(owner_id=owner_id)
    if warehouse_id:
        entries_qs = entries_qs.filter(warehouse_id=warehouse_id)
    if seed_symbol:
        entries_qs = entries_qs.filter(seed_type__symbol=seed_symbol)
    if grade:
        entries_qs = entries_qs.filter(grade=grade)
    if inout_no:
        entries_qs = entries_qs.filter(in_out_no=inout_no)

    # Compute running balances and totals.
    from collections import defaultdict

    balances = defaultdict(Decimal)
    cleaned_totals = defaultdict(Decimal)
    reject_totals = defaultdict(Decimal)

    entries = []
    two_places = Decimal("0.01")
    for entry in entries_qs:
        # Group by seed symbol so multiple SeedTypeDetail rows with the same
        # symbol participate in one continuous sequence per owner+warehouse.
        seed_key = getattr(entry.seed_type, "symbol", None) or entry.seed_type_id
        key = (seed_key, entry.owner_id, entry.warehouse_id)

        # Running balance before applying current entry
        prev_balance = balances[key]
        # Track the actual row weight separately from any later adjustments so
        # we can compute a display balance from the previous in/out number
        # regardless of mismatches in stored running balances.
        try:
            weight_dec = Decimal(entry.weight)
        except Exception:
            weight_dec = Decimal("0")
        raw_weight_dec = weight_dec

        computed_balance = prev_balance + weight_dec
        # Compute the running balance purely from prior computed value and this
        # row's signed weight. Do not trust the DB-stored balance field because
        # historical rows may have been written using different grouping rules
        # (e.g., per SeedTypeDetail id instead of symbol). Using a single
        # consistent in-memory sequence eliminates aggregation anomalies.
        computed_balance = computed_balance.quantize(two_places)
        balances[key] = computed_balance
        # Persist computed balance for use in templates
        entry.balance = computed_balance
        # Also expose a display-specific balance to make stock-out rows clearer.
        # For stock-out rows, display the simple subtraction from the prior
        # running balance in this symbol-wide sequence, regardless of how the
        # DB stored per-row balance was computed for mixed SeedTypeDetail ids.
        entry.display_balance_qtl = (
            (prev_balance + raw_weight_dec).quantize(two_places)
            if raw_weight_dec < 0
            else computed_balance
        )

        prev_cleaned = cleaned_totals[key]
        prev_reject = reject_totals[key]

        # Only the entry's own totals contribute to the running totals here.
        # Including BinCardTransaction rows would double count or time-shift
        # deductions across the sequence.
        cleaned_delta = Decimal(entry.cleaned_total_kg or 0)
        reject_delta = Decimal(entry.rejects_total_kg or 0)

        # Compute the updated running totals (with floor at 0)
        updated_cleaned_total = (
            prev_cleaned + cleaned_delta if cleaned_delta >= 0 else max(prev_cleaned + cleaned_delta, Decimal("0"))
        )
        updated_reject_total = (
            prev_reject + reject_delta if reject_delta >= 0 else max(prev_reject + reject_delta, Decimal("0"))
        )

        # Advance the tracked totals
        cleaned_totals[key] = updated_cleaned_total
        reject_totals[key] = updated_reject_total

        # Expose both the actual running totals and a display variant that keeps
        # the non-affected class unchanged for stock-out rows. This mirrors the
        # requirement that a stock-out only deducts from the chosen class.
        entry.cleaned_seed_total = cleaned_totals[key]
        entry.reject_seed_total = reject_totals[key]

        cleaned_is_negative = cleaned_delta < 0
        reject_is_negative = reject_delta < 0

        if cleaned_is_negative and not reject_is_negative:
            display_cleaned_total = updated_cleaned_total
            display_reject_total = prev_reject  # unchanged for cleaned stock-out
        elif reject_is_negative and not cleaned_is_negative:
            display_cleaned_total = prev_cleaned  # unchanged for reject stock-out
            display_reject_total = updated_reject_total
        else:
            # Regular in/out that affects both or neither
            display_cleaned_total = updated_cleaned_total
            display_reject_total = updated_reject_total
        entry.cleaned_total_qtl = Decimal(entry.cleaned_total_kg).quantize(two_places)
        entry.rejects_total_qtl = Decimal(entry.rejects_total_kg).quantize(two_places)
        entry.cleaned_seed_total_qtl = cleaned_totals[key].quantize(two_places)
        entry.reject_seed_total_qtl = reject_totals[key].quantize(two_places)
        entry.display_cleaned_seed_total_qtl = display_cleaned_total.quantize(two_places)
        entry.display_reject_seed_total_qtl = display_reject_total.quantize(two_places)

        entries.append(entry)

    # Display oldest entries first (chronological)
    entries.sort(key=lambda e: (e.date, e.id))

    # Quick summary across current filtered set (before pagination)
    total_in_qtl = Decimal("0")
    total_out_qtl = Decimal("0")
    for e in entries:
        try:
            w = Decimal(e.weight)
        except Exception:
            w = Decimal("0")
        if w >= 0:
            total_in_qtl += w
        else:
            total_out_qtl += abs(w)

    # Pagination (slice the already-computed list to keep running balances correct)
    paginator = Paginator(entries, per)
    if go_last_page:
        page_no = paginator.num_pages or 1
    page = paginator.get_page(page_no)
    net_total_qtl = (total_in_qtl - total_out_qtl)

    # Build choice lists strictly from current stock balances so suggestions
    # reflect what is actually available in stock.
    stock_qs = (
        SeedTypeBalance.objects.select_related("warehouse", "owner", "seed_type")
        .filter(warehouse__warehouse_type=Warehouse.DGT)
        .filter(Q(cleaned_kg__gt=0) | Q(rejects_kg__gt=0))
    )
    if owner_id:
        stock_qs = stock_qs.filter(owner_id=owner_id)
    if warehouse_id:
        stock_qs = stock_qs.filter(warehouse_id=warehouse_id)
    if seed_symbol:
        stock_qs = stock_qs.filter(seed_type__symbol=seed_symbol)

    owner_name_choices = sorted(
        set(
            stock_qs.exclude(owner__isnull=True).values_list("owner__name", flat=True)
        )
    )
    warehouse_name_choices = sorted(
        set(stock_qs.values_list("warehouse__name", flat=True))
    )
    seed_symbol_choices = sorted(
        set(stock_qs.values_list("seed_type__symbol", flat=True))
    )
    grade_choices = sorted(
        set(filter(None, stock_qs.values_list("seed_type__grade", flat=True)))
    )

    # Resolve selected names for template selection state
    selected_owner_name = owner_name
    selected_warehouse_name = warehouse_name
    if not selected_owner_name and owner_id:
        selected_owner_name = Company.objects.filter(id=owner_id).values_list("name", flat=True).first() or ""
    if not selected_warehouse_name and warehouse_id:
        selected_warehouse_name = (
            Warehouse.objects.filter(id=warehouse_id).values_list("name", flat=True).first() or ""
        )

    # Inject idempotency key into context if present
    idem = getattr(request, "_bincard_idem", None)
    return TemplateResponse(
            request,
            "WareDGT/bincard_list.html",
            {
                "form": form,
                "idempotency_key": idem,
                "entries": list(page.object_list),
                # Hide registration modes from Logistics Manager
                "register_out": ("register_out" in request.GET) and (role != UserProfile.OPERATIONS_MANAGER),
                "owners": owners,
                # Filters and pagination state for the template
                "f_start": start_date,
                "f_end": end_date,
                "f_owner": owner_name or owner_id or "",
                "f_owner_name": owner_name or "",
                "f_warehouse": warehouse_name or warehouse_id or "",
                "f_warehouse_name": warehouse_name or "",
                "selected_owner_name": selected_owner_name or "",
                "selected_warehouse_name": selected_warehouse_name or "",
                "f_seed": seed_symbol or "",
                "f_grade": grade or "",
                "f_io": inout_no or "",
                "per": per,
                "page": page,
                "paginator": paginator,
                "total_in_qtl": total_in_qtl,
                "total_out_qtl": total_out_qtl,
                "net_total_qtl": net_total_qtl,
                # Choice lists limited to what currently exists in stock
                "filter_owner_choices": owner_name_choices,
                "filter_warehouse_choices": warehouse_name_choices,
                "filter_seed_choices": seed_symbol_choices,
                "filter_grade_choices": grade_choices,
            },
        )


@login_required
@block_ecx_officer
def bincards_export(request):
    """Export filtered bin card entries as CSV using the same filters as the list view."""
    # Reuse bin_cards filter logic by calling the view's internals in a minimal way
    # Build the same filtered queryset
    from django.http import StreamingHttpResponse
    from django.utils.dateparse import parse_date
    from datetime import timedelta
    from django.utils import timezone

    start_str = request.GET.get("start")
    end_str = request.GET.get("end")
    owner_id = request.GET.get("owner")
    warehouse_id = request.GET.get("warehouse")
    owner_name = request.GET.get("owner_name")
    warehouse_name = request.GET.get("warehouse_name")
    seed_symbol = request.GET.get("seed")
    grade = request.GET.get("grade")
    inout_no = request.GET.get("io")

    entries_qs = (
        BinCardEntry.objects.select_related("owner", "seed_type")
        .order_by("date", "id")
    )
    # Dates are optional; when absent, don't constrain export by date.
    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None
    if start_date:
        entries_qs = entries_qs.filter(date__gte=start_date)
    if end_date:
        entries_qs = entries_qs.filter(date__lte=end_date)
    # Resolve owner/warehouse whether provided as UUID or name for robust export links
    from uuid import UUID
    def _try_uuid(v):
        try:
            UUID(str(v))
            return True
        except Exception:
            return False
    if owner_name and not owner_id:
        owner_id = (
            Company.objects.filter(name__iexact=owner_name).values_list("id", flat=True).first()
        )
    elif owner_id and not _try_uuid(owner_id):
        owner_id = (
            Company.objects.filter(name__iexact=owner_id).values_list("id", flat=True).first()
        )
    if warehouse_name and not warehouse_id:
        warehouse_id = (
            Warehouse.objects.filter(name__iexact=warehouse_name, warehouse_type=Warehouse.DGT)
            .values_list("id", flat=True)
            .first()
        )
    elif warehouse_id and not _try_uuid(warehouse_id):
        warehouse_id = (
            Warehouse.objects.filter(name__iexact=warehouse_id, warehouse_type=Warehouse.DGT)
            .values_list("id", flat=True)
            .first()
        )
    if owner_id:
        entries_qs = entries_qs.filter(owner_id=owner_id)
    if warehouse_id:
        entries_qs = entries_qs.filter(warehouse_id=warehouse_id)
    if seed_symbol:
        entries_qs = entries_qs.filter(seed_type__symbol=seed_symbol)
    if grade:
        entries_qs = entries_qs.filter(grade=grade)
    if inout_no:
        entries_qs = entries_qs.filter(in_out_no=inout_no)

    # Compute running balances as in list view
    from collections import defaultdict
    balances = defaultdict(Decimal)
    cleaned_totals = defaultdict(Decimal)
    reject_totals = defaultdict(Decimal)
    two_places = Decimal("0.01")
    rows = []
    for entry in entries_qs:
        seed_key = getattr(entry.seed_type, "symbol", None) or entry.seed_type_id
        key = (seed_key, entry.owner_id, entry.warehouse_id)
        prev_balance = balances[key]
        try:
            weight_dec = Decimal(entry.weight)
        except Exception:
            weight_dec = Decimal("0")
        computed_balance = (prev_balance + weight_dec).quantize(two_places)
        balances[key] = computed_balance
        cleaned_delta = Decimal(entry.cleaned_total_kg or 0)
        reject_delta = Decimal(entry.rejects_total_kg or 0)
        cleaned_totals[key] = max(cleaned_totals[key] + cleaned_delta, Decimal("0")) if cleaned_delta < 0 else cleaned_totals[key] + cleaned_delta
        reject_totals[key] = max(reject_totals[key] + reject_delta, Decimal("0")) if reject_delta < 0 else reject_totals[key] + reject_delta
        rows.append([
            str(entry.date),
            getattr(entry.seed_type, "symbol", ""),
            entry.grade,
            str(entry.purity or ""),
            str(entry.owner),
            str(entry.warehouse),
            entry.in_out_no,
            entry.description,
            str(entry.weight),
            str(computed_balance),
            str(entry.cleaned_total_kg or 0),
            str(entry.rejects_total_kg or 0),
            str(cleaned_totals[key]),
            str(reject_totals[key]),
        ])

    def iterator():
        import csv
        yield (
            "Date,Seed,Grade,Purity (%),Owner,Warehouse,In/Out No,Description,Weight (qtls),Balance (qtls),Cleaned (qtls),Rejects (qtls),Total Cleaned (qtls),Total Rejects (qtls)\n"
        )
        for r in rows:
            # Escape commas by CSV writer formatting
            from io import StringIO
            sio = StringIO()
            csv.writer(sio).writerow(r)
            yield sio.getvalue()

    resp = StreamingHttpResponse(iterator(), content_type="text/csv")
    resp["Content-Disposition"] = "attachment; filename=bincards.csv"
    return resp

@login_required
@block_ecx_officer
def bincard_detail(request, lot_id):
    """Display a single lot with running cleaning balances."""
    lot = get_object_or_404(
        BinCardEntry.objects.select_related("seed_type", "warehouse"), pk=lot_id
    )
    total = lot.cleaned_total_kg + lot.rejects_total_kg
    yield_pct = (lot.cleaned_total_kg / total * 100) if total else None
    context = {"lot": lot, "yield_pct": yield_pct}
    return render(request, "WareDGT/bincard_detail.html", context)


@login_required
@block_ecx_officer
def stock_levels(request):
    """Display current stock levels.

    Placeholder view that will later be expanded with real stock
    visualizations. For now it simply renders a stub template so the
    sidebar link resolves correctly instead of returning a 404.
    """

    return render(request, "WareDGT/stock_levels.html")


@login_required
@block_ecx_officer
def reports(request):
    """Reporting page for Logistics Manager/Admin including stock overviews.

    Mirrors the Accountant Overview (totals by seed, grade, owner, and date)
    and is accessible via the Reporting section for Logistics Manager and Admin.
    """
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
        return HttpResponseForbidden("Only Logistics/System Manager can access reports.")

    owner_id = request.GET.get("owner")
    symbol = request.GET.get("symbol")
    grade = request.GET.get("grade")
    purchase_date = request.GET.get("purchase_date")

    # ECX trades summary (optionally filtered)
    ecx_qs = EcxTrade.objects.all()
    if owner_id:
        ecx_qs = ecx_qs.filter(owner_id=owner_id)
    if symbol:
        ecx_qs = ecx_qs.filter(commodity__seed_type__code=symbol)
    if grade:
        ecx_qs = ecx_qs.filter(commodity__grade__icontains=grade)
    if purchase_date:
        ecx_qs = ecx_qs.filter(purchase_date=purchase_date)

    from django.db.models import Sum
    ecx_total = ecx_qs.aggregate(s=Sum("quantity_quintals")).get("s") or 0
    ecx_rows = (
        ecx_qs.values(
            "commodity__seed_type__code",
            "commodity__grade",
            "owner__name",
            "purchase_date",
        )
        .annotate(total=Sum("quantity_quintals"))
        .order_by("-purchase_date", "commodity__seed_type__code", "commodity__grade", "owner__name")
    )

    # Contract movements summary (no purchase_date dimension)
    cm_qs = ContractMovement.objects.all()
    if owner_id:
        cm_qs = cm_qs.filter(owner_id=owner_id)
    if symbol:
        cm_qs = cm_qs.filter(symbol=symbol)
    cm_total = cm_qs.aggregate(s=Sum("quantity_quintals")).get("s") or 0
    cm_rows = (
        cm_qs.values("symbol", "owner__name")
        .annotate(total=Sum("quantity_quintals"))
        .order_by("symbol", "owner__name")
    )

    ctx = {
        "ecx_total": ecx_total,
        "ecx_rows": ecx_rows,
        "cm_total": cm_total,
        "cm_rows": cm_rows,
        "filters": {
            "owner": owner_id,
            "symbol": symbol,
            "grade": grade,
            "purchase_date": purchase_date,
        },
    }
    return render(request, "WareDGT/reports.html", ctx)


@login_required
@block_ecx_officer
def sesame_contract(request):
    """Display ECX sesame contract details."""
    return render(request, "WareDGT/sesame_contract.html")


@login_required
@block_ecx_officer
def coffee_details(request):
    """Reference page for ECX coffee grading and trading terms."""
    return render(request, "WareDGT/coffee_details.html")


@login_required
@block_ecx_officer
def bean_contract(request):
    """Display ECX white pea beans contract details."""
    return render(request, "WareDGT/bean_contract.html")


@login_required
@block_ecx_officer
def master_data(request):
    return HttpResponse("<h1>Master Data</h1><p>Coming soon…</p>")


@login_required
@block_ecx_officer
def system_config(request):
    return HttpResponse("<h1>Configuration</h1><p>Coming soon…</p>")


# ----- Permissions & Roles -----
class RoleRequiredMixin(UserPassesTestMixin):
    allowed_roles = []

    def test_func(self):
        profile = getattr(self.request.user, "profile", None)
        return profile and profile.role in self.allowed_roles

    def handle_no_permission(self):
        messages.error(self.request, "You do not have permission to access this page.")
        return redirect("login")


class IsEcxOfficer(permissions.BasePermission):
    """DRF permission enforcing ECX_OFFICER role.

    Note: Per requirements, Logistics Manager (OPERATIONS_MANAGER)
    should have all ECX Officer capabilities, so they are included here.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return profile and profile.role in [
            UserProfile.ECX_OFFICER,
            UserProfile.OPERATIONS_MANAGER,
        ]


class IsAdmin(permissions.BasePermission):
    """DRF permission enforcing ADMIN role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return profile and profile.role == UserProfile.ADMIN


class IsAdminOrEcxOfficer(permissions.BasePermission):
    """DRF permission for ADMIN, ECX_OFFICER, or OPERATIONS_MANAGER roles."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        profile = getattr(request.user, "profile", None)
        return profile and profile.role in [
            UserProfile.ADMIN,
            UserProfile.ECX_OFFICER,
            UserProfile.OPERATIONS_MANAGER,
        ]


class AgentReadOnly(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        prof = getattr(request.user, "profile", None)
        if not prof:
            return False
        if prof.role == UserProfile.ECX_AGENT:
            if request.method in SAFE_METHODS:
                return True
            if (
                request.method == "POST"
                and getattr(view, "action", "") in ["load", "load_stock"]
            ):
                return True
            return False
        return True


# Decorator to enforce login on function views
@login_required
@block_ecx_officer
def serve_weighbridge_slip_image(request, image_id):
    slip = get_object_or_404(WeighbridgeSlipImage, id=image_id)
    try:
        return FileResponse(open(slip.image.path, "rb"), content_type="image/jpeg")
    except IOError:
        raise Http404("Image not found")


# ----- CRUD Views -----
@method_decorator(login_required, name="dispatch")
class PurchaseOrderListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = PurchaseOrder
    template_name = "WareDGT/purchaseorder_list.html"
    allowed_roles = ["OPERATIONS_MANAGER", "ADMIN"]


@method_decorator(login_required, name="dispatch")
class PurchaseOrderCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = PurchaseOrder
    form_class = PurchaseOrderForm
    template_name = "WareDGT/purchaseorder_form.html"
    success_url = reverse_lazy("purchaseorder_list")
    allowed_roles = ["OPERATIONS_MANAGER", "ADMIN"]


@method_decorator(login_required, name="dispatch")
class StockMovementCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = StockMovement
    form_class = StockMovementForm
    template_name = "WareDGT/stockmovement_form.html"
    success_url = reverse_lazy("stockmovement_list")
    allowed_roles = ["WAREHOUSE_OFFICER", "ADMIN"]

    def form_valid(self, form):
        messages.success(self.request, "Stock movement recorded successfully.")
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
class StockMovementListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = StockMovement
    template_name = "WareDGT/stockmovement_list.html"
    allowed_roles = ["WAREHOUSE_OFFICER", "ADMIN"]
    ordering = ["-ticket_date"]


@method_decorator(login_required, name="dispatch")
class WeighbridgeSlipImageUploadView(LoginRequiredMixin, RoleRequiredMixin, View):
    allowed_roles = ["WAREHOUSE_OFFICER", "ADMIN", UserProfile.WEIGHBRIDGE_OPERATOR]

    def post(self, request, *args, **kwargs):
        form = SlipImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            movement = form.cleaned_data["movement"]
            desc = form.cleaned_data.get("description", "")
            for img in request.FILES.getlist("images"):
                WeighbridgeSlipImage.objects.create(
                    movement=movement, image=img, description=desc
                )
            messages.success(request, "Slip images uploaded.")
        else:
            messages.error(request, "Upload failed: %s" % form.errors)
        return redirect(request.META.get("HTTP_REFERER", "/"))


@method_decorator(login_required, name="dispatch")
class EcxTradeListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = EcxTrade
    template_name = "WareDGT/ecxtrade_list.html"
    allowed_roles = ["ECX_OFFICER", "OPERATIONS_MANAGER", "ADMIN", UserProfile.ECX_AGENT]
    ordering = ["warehouse__name", "-purchase_date"]

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("warehouse", "commodity", "owner")
            .prefetch_related("receipt_files")
        )
        role = getattr(getattr(self.request.user, "profile", None), "role", None)
        if role == UserProfile.ECX_AGENT:
            qs = qs.filter(warehouse__in=self.request.user.profile.warehouses.all())
        return qs

    def get_context_data(self, **kwargs):
        """Provide warehouse and owner options for client-side filtering."""
        context = super().get_context_data(**kwargs)
        context["warehouses"] = Warehouse.objects.filter(
            warehouse_type=Warehouse.ECX
        ).order_by("name")
        context["owners"] = Company.objects.all().order_by("name")
        context["role"] = getattr(getattr(self.request.user, "profile", None), "role", None)
        # Build per-trade receipt image and file lists for stylish display
        def _is_image(name: str) -> bool:
            n = (name or "").lower()
            return n.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
        trade_rows = []
        for t in context.get("object_list", []):
            images, files = [], []
            for rf in getattr(t, "receipt_files", []).all():
                try:
                    url = rf.file.url
                except Exception:
                    continue
                name = getattr(rf.file, "name", url)
                if _is_image(name):
                    images.append(url)
                else:
                    files.append(url)
            trade_rows.append({"trade": t, "images": images, "files": files})
        context["trade_rows"] = trade_rows
        return context


@login_required
def ecx_trade_pdf(request, pk):
    trade = get_object_or_404(EcxTrade.objects.select_related("warehouse", "commodity", "owner"), pk=pk)
    pdf_file = generate_ecxtrade_pdf(trade)
    response = HttpResponse(pdf_file.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{pdf_file.name}"'
    return response


@method_decorator(login_required, name="dispatch")
class EcxTradeCreateView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    form_class = EcxTradeForm
    template_name = "WareDGT/ecxtrade_form.html"
    success_url = reverse_lazy("ecxtrade_list")
    allowed_roles = ["ECX_OFFICER", "OPERATIONS_MANAGER", "ADMIN"]

    def form_valid(self, form):
        """Directly record ECX trades without accountant approval.

        Previously this created an EcxTradeRequest for ACCOUNTANT review. Per
        updated requirements, Logistics Manager submissions are saved
        immediately to reduce bureaucracy.
        """

        owner = form.cleaned_data.get("owner")
        category = form.cleaned_data.get("category")
        symbol = form.cleaned_data.get("symbol")
        grade = form.cleaned_data.get("grade")
        warehouse_val = form.cleaned_data.get("warehouse")
        # Second set
        category2 = form.cleaned_data.get("category2")
        symbol2 = form.cleaned_data.get("symbol2")
        grade2 = form.cleaned_data.get("grade2")
        warehouse2_val = form.cleaned_data.get("warehouse2")
        receipt_lines_raw = form.cleaned_data.get("receipt_entries")
        receipt_lines_raw2 = form.cleaned_data.get("receipt_entries2")
        nor = form.cleaned_data.get("net_obligation_receipt_no")
        purchase_date = form.cleaned_data.get("purchase_date")

        # Prefer dynamic multi-group payload if provided
        groups_payload = form.cleaned_data.get("groups_json") or self.request.POST.get("groups_json")
        parsed_groups = []
        if groups_payload:
            try:
                parsed = json.loads(groups_payload)
                if isinstance(parsed, dict) and "groups" in parsed:
                    parsed_groups = parsed.get("groups") or []
                elif isinstance(parsed, list):
                    parsed_groups = parsed
            except Exception:
                parsed_groups = []

        use_groups = isinstance(parsed_groups, list) and len(parsed_groups) > 0

        lines = []
        chosen_warehouse = None
        chosen_symbol = None
        chosen_grade = None
        chosen_category = None

        if use_groups:
            for idx, g in enumerate(parsed_groups):
                gcat = (g.get("category") or "").strip() or None
                gsym = (g.get("symbol") or "").strip()
                ggrade = (g.get("grade") or "").strip()
                gwh = (g.get("warehouse") or "").strip()
                gentries = g.get("receipt_entries") or g.get("entries") or ""
                if not gsym or not ggrade or not gwh:
                    messages.error(self.request, f"Group {idx+1}: Missing seed or warehouse.")
                    return self.form_invalid(form)
                wh_obj = Warehouse.objects.filter(pk=gwh).first()
                if not wh_obj:
                    messages.error(self.request, f"Group {idx+1}: Invalid warehouse.")
                    return self.form_invalid(form)
                dqs = SeedTypeDetail.objects.filter(
                    symbol=gsym,
                    delivery_location=wh_obj,
                    grade__icontains=ggrade,
                )
                if gcat and gcat != "OTHER":
                    dqs = dqs.filter(category=gcat)
                if not dqs.exists():
                    messages.error(self.request, f"Group {idx+1}: Invalid seed/grade for warehouse.")
                    return self.form_invalid(form)
                # Parse entries
                any_line = False
                for line in re.split(r"[\n,]+", gentries or ""):
                    line = line.strip()
                    if not line:
                        continue
                    if ":" not in line:
                        messages.error(self.request, f"Group {idx+1}: Use 'receipt:qty' format per line")
                        return self.form_invalid(form)
                    wrn, qty = line.split(":", 1)
                    wrn = wrn.strip()
                    try:
                        qty_val = Decimal(qty.strip())
                    except Exception:
                        messages.error(self.request, f"Group {idx+1}: Invalid quantity for {wrn}")
                        return self.form_invalid(form)
                    lines.append({
                        "warehouse_receipt_no": wrn,
                        "quantity": str(qty_val),
                        "warehouse": str(wh_obj.pk),
                        "symbol": gsym,
                        "grade": ggrade,
                    })
                    any_line = True
                if not any_line:
                    messages.error(self.request, f"Group {idx+1}: Provide at least one receipt:qty line")
                    return self.form_invalid(form)
                if chosen_warehouse is None:
                    chosen_warehouse = wh_obj
                    chosen_symbol = gsym
                    chosen_grade = ggrade
                    chosen_category = gcat
        else:
            # Legacy single/two groups path
            # Validate seed/warehouse combination early
            detail_qs = SeedTypeDetail.objects.filter(
                symbol=symbol,
                delivery_location_id=warehouse_val,
                grade__icontains=grade,
            )
            if category and category != "OTHER":
                detail_qs = detail_qs.filter(category=category)
            detail = detail_qs.first()
            if not detail:
                messages.error(self.request, "Invalid seed type selection.")
                return self.form_invalid(form)

            warehouse = Warehouse.objects.filter(pk=warehouse_val).first()
            if not warehouse:
                messages.error(self.request, "Invalid warehouse selection.")
                return self.form_invalid(form)

            # Optional: second warehouse validation when provided
            warehouse2 = None
            if warehouse2_val:
                # Require symbol2/grade2 if using a second warehouse
                if not symbol2 or not grade2:
                    messages.error(self.request, "Please select seed type and grade for the second warehouse.")
                    return self.form_invalid(form)
                detail2_qs = SeedTypeDetail.objects.filter(
                    symbol=symbol2,
                    delivery_location_id=warehouse2_val,
                    grade__icontains=grade2,
                )
                if category2 and category2 != "OTHER":
                    detail2_qs = detail2_qs.filter(category=category2)
                detail2 = detail2_qs.first()
                if not detail2:
                    messages.error(self.request, "Invalid second warehouse for selected seed/grade.")
                    return self.form_invalid(form)
                warehouse2 = Warehouse.objects.filter(pk=warehouse2_val).first()
                if not warehouse2:
                    messages.error(self.request, "Invalid second warehouse selection.")
                    return self.form_invalid(form)

            # Parse receipt lines to normalized JSON
            for line in re.split(r"[\n,]+", receipt_lines_raw or ""):
                line = line.strip()
                if not line:
                    continue
                if ":" not in line:
                    form.add_error("receipt_entries", "Use 'receipt:qty' format per line")
                    return self.form_invalid(form)
                wrn, qty = line.split(":", 1)
                wrn = wrn.strip()
                try:
                    qty_val = Decimal(qty.strip())
                except Exception:
                    form.add_error("receipt_entries", f"Invalid quantity for {wrn}")
                    return self.form_invalid(form)
                lines.append({
                    "warehouse_receipt_no": wrn,
                    "quantity": str(qty_val),
                    "warehouse": str(warehouse.pk),
                    "symbol": symbol,
                    "grade": grade,
                })
            if not lines:
                form.add_error("receipt_entries", "Provide at least one receipt:qty line")
                return self.form_invalid(form)

            # Optionally parse second set of receipt lines for the second warehouse
            if warehouse2 and receipt_lines_raw2:
                for line in re.split(r"[\n,]+", receipt_lines_raw2 or ""):
                    line = line.strip()
                    if not line:
                        continue
                    if ":" not in line:
                        form.add_error("receipt_entries2", "Use 'receipt:qty' format per line")
                        return self.form_invalid(form)
                    wrn, qty = line.split(":", 1)
                    wrn = wrn.strip()
                    try:
                        qty_val = Decimal(qty.strip())
                    except Exception:
                        form.add_error("receipt_entries2", f"Invalid quantity for {wrn}")
                        return self.form_invalid(form)
                    lines.append({
                        "warehouse_receipt_no": wrn,
                        "quantity": str(qty_val),
                        "warehouse": str(warehouse2.pk),
                        "symbol": symbol2,
                        "grade": grade2,
                    })
            chosen_warehouse = warehouse
            chosen_symbol = symbol
            chosen_grade = grade
            chosen_category = category

        # Create EcxTrade rows immediately, mirroring approval logic
        files = list(self.request.FILES.getlist("receipt_file"))
        created = 0
        with transaction.atomic():
            for line in lines:
                wrn = (line.get("warehouse_receipt_no") or "").strip()
                qty_str = line.get("quantity")
                if not wrn or not qty_str:
                    continue
                qty_val = Decimal(str(qty_str))

                # Determine warehouse for this line
                line_wh_id = line.get("warehouse") or (chosen_warehouse.pk if chosen_warehouse else None)
                try:
                    line_wh = Warehouse.objects.get(pk=line_wh_id)
                except Warehouse.DoesNotExist:
                    messages.error(self.request, "Invalid warehouse on a receipt line.")
                    return self.form_invalid(form)

                # Resolve seed detail and commodity per warehouse (origin can differ)
                line_symbol = line.get("symbol") or chosen_symbol or ""
                line_grade = line.get("grade") or chosen_grade or ""
                detail = (
                    SeedTypeDetail.objects.filter(
                        symbol=line_symbol,
                        delivery_location=line_wh,
                        grade__icontains=line_grade,
                    ).first()
                )
                if not detail:
                    messages.error(self.request, "Seed type detail not found for a receipt line.")
                    return self.form_invalid(form)

                seed_type, _ = SeedType.objects.get_or_create(
                    code=line_symbol, defaults={"name": detail.name}
                )
                commodity, _ = Commodity.objects.get_or_create(
                    seed_type=seed_type, origin=detail.origin, grade=line_grade
                )

                # Next available version for WRN
                max_ver = (
                    EcxTrade.objects.filter(warehouse_receipt_no=wrn)
                    .aggregate(m=Max("warehouse_receipt_version"))
                    .get("m")
                )
                next_ver = (max_ver or 0) + 1

                trade = EcxTrade.objects.create(
                    warehouse=line_wh,
                    commodity=commodity,
                    net_obligation_receipt_no=nor,
                    warehouse_receipt_no=wrn,
                    warehouse_receipt_version=next_ver,
                    quantity_quintals=qty_val,
                    purchase_date=purchase_date,
                    recorded_by=self.request.user,
                    owner=owner,
                )
                for f in files:
                    EcxTradeReceiptFile.objects.create(trade=trade, file=f)
                created += 1

        messages.success(self.request, f"Recorded {created} trade(s).")
        return super().form_valid(form)

    def _email_accountants(self, req):
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string
        from django.urls import reverse

        accountants = (
            User.objects.filter(is_active=True, profile__role=UserProfile.ACCOUNTANT)
            .distinct()
        )
        if not accountants.exists():
            accountants = User.objects.filter(is_active=True, profile__role=UserProfile.ADMIN)
        if not accountants.exists():
            return

        review_url = self.request.build_absolute_uri(
            reverse("ecxtrade_request_review", args=[str(req.id)]) + f"?t={req.approval_token}"
        )
        file_urls = [
            self.request.build_absolute_uri(f.file.url) for f in req.files.all()
        ]
        # Map warehouse IDs to names for display
        wh_ids = set()
        for l in req.receipt_lines:
            wid = l.get("warehouse")
            if wid:
                wh_ids.add(str(wid))
        wh_names = {}
        if wh_ids:
            for w in Warehouse.objects.filter(id__in=list(wh_ids)):
                wh_names[str(w.id)] = w.name
        lines = []
        total_quantity = Decimal("0")
        for idx, line in enumerate(req.receipt_lines):
            file_url = file_urls[idx] if idx < len(file_urls) else ""
            try:
                total_quantity += Decimal(str(line.get("quantity") or 0))
            except Exception:
                pass
            wid = str(line.get("warehouse") or "")
            lines.append(
                {
                    "warehouse_receipt_no": line.get("warehouse_receipt_no"),
                    "quantity": line.get("quantity"),
                    "file_url": file_url,
                    "warehouse_name": wh_names.get(wid) or (req.warehouse.name if req.warehouse else ""),
                    "symbol": line.get("symbol") or req.symbol,
                    "grade": line.get("grade") or req.grade,
                }
            )
        unique_wh = sorted({l.get("warehouse_name") for l in lines if l.get("warehouse_name")})
        ctx = {
            "request_obj": req,
            "review_url": review_url,
            "site_name": "DGT Warehouse",
            "submitter": self.request.user,
            "lines": lines,
            "total_quantity": total_quantity,
            "warehouses": ", ".join(unique_wh) if unique_wh else (req.warehouse.name if req.warehouse else ""),
        }
        subject = f"Approval Required: ECX Trade {req.net_obligation_receipt_no}"
        html = render_to_string("WareDGT/emails/ecx_trade_request.html", ctx)
        text = render_to_string("WareDGT/emails/ecx_trade_request.txt", ctx)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text,
            to=[u.email for u in accountants if u.email],
        )
        msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=True)


def _notify_ecx_load_managers(django_request, req):
    managers = User.objects.filter(
        profile__role=UserProfile.OPERATIONS_MANAGER, is_active=True
    )
    if not managers:
        return
    ctx = {
        "req": req,
        "approve_url": django_request.build_absolute_uri(
            reverse("ecxload_request_review", args=[str(req.id)])
        )
        + f"?t={req.approval_token}",
    }
    subject = "ECX Load Request – Approval Needed"
    text = render_to_string("emails/ecx_load_request.txt", ctx)
    html = render_to_string("emails/ecx_load_request.html", ctx)
    msg = EmailMultiAlternatives(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [m.email for m in managers if m.email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)


def _create_ecx_load_request(
    django_request,
    user,
    warehouse,
    trades,
    plombs_count,
    has_trailer,
    trailer_count,
    truck_image=None,
    payload=None,
):
    req = EcxLoadRequest.objects.create(
        created_by=user,
        warehouse=warehouse,
        plombs_count=plombs_count,
        has_trailer=has_trailer,
        trailer_count=trailer_count if has_trailer else 0,
        truck_image=truck_image,
        approval_token=get_random_string(48),
        payload=payload or {},
    )
    req.trades.set(trades)
    _notify_ecx_load_managers(django_request, req)
    return req


@login_required
@require_POST
def ecx_load_request_from_map(request):
    prof = getattr(request.user, "profile", None)
    if not prof or prof.role != UserProfile.ECX_AGENT:
        return JsonResponse({"error": "Forbidden"}, status=403)

    wh_id = request.POST.get("warehouse_id")
    symbol = request.POST.get("symbol")
    grade = request.POST.get("grade")
    trade_ids = request.POST.getlist("trade_ids") or request.POST.getlist("trade_ids[]")
    plombs = request.POST.get("plombs_count")
    has_trailer = request.POST.get("has_trailer") in ["1", "true", "on", "True"]
    trailer_count = request.POST.get("trailer_count") or 0
    truck_image = request.FILES.get("truck_image")
    truck_plate_no = request.POST.get("truck_plate_no", "").strip()
    trailer_plate_no = request.POST.get("trailer_plate_no", "").strip()
    loading_date_str = request.POST.get("loading_date")
    requested_qty = request.POST.get("quantity")

    if not wh_id or not trade_ids or not symbol:
        return JsonResponse({"error": "Missing fields"}, status=400)

    try:
        warehouse = Warehouse.objects.get(pk=wh_id)
    except Warehouse.DoesNotExist:
        return JsonResponse({"error": "Invalid warehouse"}, status=400)

    if not prof.warehouses.filter(id=warehouse.id).exists():
        return JsonResponse({"error": "Warehouse not assigned"}, status=400)

    try:
        plombs_val = int(plombs or 0)
        trailer_count_val = int(trailer_count or 0)
    except ValueError:
        return JsonResponse({"error": "Invalid counts"}, status=400)

    try:
        trade_ids_int = [int(t) for t in trade_ids]
    except ValueError:
        return JsonResponse({"error": "Invalid trade IDs"}, status=400)

    trades = list(
        EcxTrade.objects.filter(
            id__in=trade_ids_int, loaded=False, warehouse=warehouse
        )
    )
    if len(trades) != len(trade_ids_int):
        return JsonResponse({"error": "Invalid trade selection"}, status=400)

    for t in trades:
        if t.commodity.seed_type.code != symbol:
            return JsonResponse({"error": "Symbol/grade mismatch"}, status=400)
        if grade and grade.lower() not in t.commodity.grade.lower():
            return JsonResponse({"error": "Symbol/grade mismatch"}, status=400)

    if EcxLoadRequest.objects.filter(
        status=EcxLoadRequest.STATUS_PENDING, trades__in=trades
    ).exists():
        return JsonResponse({"error": "Trade already requested"}, status=400)

    # Optional per-trade allocations: fields like alloc_<trade_id>=<qty>
    allocations = {}
    for k in request.POST.keys():
        ks = str(k)
        if ks.startswith("alloc_"):
            try:
                tid = int(ks.split("_", 1)[1])
                val = request.POST.get(k)
                if val is not None:
                    allocations[tid] = str(val)
            except Exception:
                pass

    payload = {
        "symbol": symbol,
        "grade": grade,
        "trade_ids": trade_ids_int,
        "quantity": requested_qty,
        "loading_date": loading_date_str,
    }
    if allocations:
        payload["allocations"] = allocations

    req = _create_ecx_load_request(
        request,
        request.user,
        warehouse,
        trades,
        plombs_val,
        has_trailer,
        trailer_count_val,
        truck_image,
        payload=payload,
    )
    # Persist plate numbers on the request so weighbridge operator sees them later
    changed = False
    if truck_plate_no:
        req.truck_plate_no = truck_plate_no
        changed = True
    if trailer_plate_no:
        req.trailer_plate_no = trailer_plate_no
        changed = True
    if changed:
        req.save(update_fields=["truck_plate_no", "trailer_plate_no"]) 

    # Save optional per-grade receipt files
    groups = {}
    for t in trades:
        key = (t.commodity.origin, t.commodity.grade)
        if key not in groups:
            groups[key] = {"origin": t.commodity.origin, "grade": t.commodity.grade}
    group_list = sorted(groups.values(), key=lambda g: (g["origin"], g["grade"]))
    for idx, g in enumerate(group_list):
        file_obj = request.FILES.get(f"file_{idx}")
        if file_obj:
            EcxLoadRequestReceiptFile.objects.create(
                request=req, origin=g["origin"], grade=g["grade"], file=file_obj
            )

    return JsonResponse({"ok": True})

@method_decorator(login_required, name="dispatch")
class EcxLoadCreateView(LoginRequiredMixin, RoleRequiredMixin, FormView):
    """Mark ECX trades as loaded for a selected warehouse."""

    form_class = EcxLoadForm
    template_name = "WareDGT/ecxload_form.html"
    success_url = reverse_lazy("ecxtrade_list")
    allowed_roles = ["OPERATIONS_MANAGER", "ADMIN"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        trades = form.cleaned_data.get("trades", [])
        EcxTrade.objects.filter(pk__in=[t.pk for t in trades]).update(
            loaded=True,
            loaded_at=timezone.now(),
        )
        messages.success(self.request, "Load recorded successfully.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "Record ECX Load"
        ctx["submit_label"] = "Save"
        return ctx



@method_decorator(login_required, name="dispatch")
class EcxTradeRequestListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = EcxTradeRequest
    template_name = "WareDGT/ecxtrade_request_list.html"
    allowed_roles = [UserProfile.ACCOUNTANT, UserProfile.ADMIN]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = super().get_queryset().filter(status=EcxTradeRequest.STATUS_PENDING)
        owner = self.request.GET.get("owner")
        nor_q = self.request.GET.get("q")
        start = self.request.GET.get("start")
        end = self.request.GET.get("end")
        if owner:
            qs = qs.filter(owner_id=owner)
        if nor_q:
            qs = qs.filter(net_obligation_receipt_no__icontains=nor_q)
        # Optional date range filters on purchase_date
        try:
            if start:
                from datetime import datetime
                qs = qs.filter(purchase_date__gte=datetime.strptime(start, "%Y-%m-%d").date())
            if end:
                from datetime import datetime
                qs = qs.filter(purchase_date__lte=datetime.strptime(end, "%Y-%m-%d").date())
        except Exception:
            pass
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .models import Company
        ctx["owners"] = Company.objects.all().order_by("name")
        ctx["selected_owner"] = self.request.GET.get("owner") or ""
        ctx["query"] = self.request.GET.get("q") or ""
        ctx["start"] = self.request.GET.get("start") or ""
        ctx["end"] = self.request.GET.get("end") or ""
        return ctx


@login_required
def ecxtrade_request_export(request):
    """Export pending ECX trade requests as CSV for accountants.

    Accepts the same filters as the list view: owner, q (NOR contains), start, end.
    """
    prof = getattr(request.user, "profile", None)
    if not prof or prof.role not in [UserProfile.ACCOUNTANT, UserProfile.ADMIN]:
        return HttpResponseForbidden("Forbidden")
    qs = EcxTradeRequest.objects.filter(status=EcxTradeRequest.STATUS_PENDING)
    owner = request.GET.get("owner")
    nor_q = request.GET.get("q")
    start = request.GET.get("start")
    end = request.GET.get("end")
    if owner:
        qs = qs.filter(owner_id=owner)
    if nor_q:
        qs = qs.filter(net_obligation_receipt_no__icontains=nor_q)
    try:
        from datetime import datetime
        if start:
            qs = qs.filter(purchase_date__gte=datetime.strptime(start, "%Y-%m-%d").date())
        if end:
            qs = qs.filter(purchase_date__lte=datetime.strptime(end, "%Y-%m-%d").date())
    except Exception:
        pass

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="ecx_trade_requests.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Submitted', 'Submitter', 'Owner', 'Warehouses', 'Seed', 'Grade', 'NOR', 'Purchase Date', 'Total Qtls', 'Lines'
    ])
    for r in qs.select_related('created_by', 'owner', 'warehouse'):
        lines_str = "; ".join(
            [f"{l.get('warehouse_receipt_no')}:{l.get('quantity')}" for l in (r.receipt_lines or [])]
        )
        writer.writerow([
            r.created_at.isoformat(),
            r.created_by.get_username(),
            str(r.owner) if r.owner else '',
            r.warehouses_display,
            r.symbol,
            r.grade,
            r.net_obligation_receipt_no,
            r.purchase_date.isoformat() if r.purchase_date else '',
            r.total_quantity,
            lines_str,
        ])
    return response


@method_decorator(login_required, name="dispatch")
class EcxTradeRequestReviewView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "WareDGT/ecxtrade_request_detail.html"
    allowed_roles = [UserProfile.ACCOUNTANT, UserProfile.ADMIN]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = get_object_or_404(EcxTradeRequest, pk=kwargs.get("pk"))
        files = list(req.files.all())
        ctx["request_obj"] = req
        # Token is no longer required for in-app accountant review
        ctx["token_ok"] = True
        # Build map of per-line warehouses for display
        wh_ids = set()
        for l in req.receipt_lines:
            wid = l.get("warehouse")
            if wid:
                wh_ids.add(str(wid))
        wh_names = {}
        if wh_ids:
            for w in Warehouse.objects.filter(id__in=list(wh_ids)):
                wh_names[str(w.id)] = w.name
        lines_display = []
        for idx, line in enumerate(req.receipt_lines):
            wid = str(line.get("warehouse") or "")
            lines_display.append(
                {
                    "warehouse_receipt_no": line.get("warehouse_receipt_no"),
                    "quantity": line.get("quantity"),
                    "symbol": line.get("symbol") or req.symbol,
                    "grade": line.get("grade") or req.grade,
                    "warehouse_name": wh_names.get(wid) or (req.warehouse.name if req.warehouse else ""),
                    "file": files[idx] if idx < len(files) else None,
                }
            )
        ctx["lines_display"] = lines_display
        # Compute total quantity across receipt lines for quick review
        try:
            from decimal import Decimal
            total = sum(Decimal(str(l.get("quantity", 0))) for l in req.receipt_lines)
            ctx["total_quantity"] = total
        except Exception:
            ctx["total_quantity"] = None
        return ctx

    def post(self, request, *args, **kwargs):
        req = get_object_or_404(EcxTradeRequest, pk=kwargs.get("pk"))
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        if req.status != EcxTradeRequest.STATUS_PENDING:
            messages.info(request, "Request already decided.")
            return redirect("ecxtrade_request_review", pk=req.pk)
        if req.created_by_id == request.user.id:
            messages.error(request, "Submitter cannot self-approve or decline.")
            return redirect("ecxtrade_request_review", pk=req.pk)

        if action == "decline":
            if not note.strip():
                messages.error(request, "Reason is required to decline.")
                return redirect("ecxtrade_request_review", pk=req.pk)
            req.status = EcxTradeRequest.STATUS_DECLINED
            req.decision_by = request.user
            req.decided_at = timezone.now()
            req.decision_note = note
            req.save(update_fields=["status", "decision_by", "decided_at", "decision_note"])

            files = list(req.files.all())
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string
            import mimetypes
            import os
            from email.mime.image import MIMEImage

            lines = []
            for idx, line in enumerate(req.receipt_lines):
                file_obj = files[idx] if idx < len(files) else None
                line_entry = {
                    "warehouse_receipt_no": line.get("warehouse_receipt_no"),
                    "quantity": line.get("quantity"),
                    "cid": f"img{idx}" if file_obj else "",
                }
                lines.append(line_entry)

            ctx = {
                "request_obj": req,
                "note": note,
                "accountant": request.user,
                "lines": lines,
                "site_name": "DGT Warehouse",
            }
            subject = (
                f"ECX Trade Request Declined: {req.net_obligation_receipt_no}"
            )
            html = render_to_string(
                "WareDGT/emails/ecx_trade_declined.html", ctx
            )
            text = render_to_string(
                "WareDGT/emails/ecx_trade_declined.txt", ctx
            )
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text,
                to=[req.created_by.email] if req.created_by.email else [],
            )
            msg.attach_alternative(html, "text/html")
            for idx, f in enumerate(files):
                f.file.open("rb")
                data = f.file.read()
                f.file.close()
                mime_type, _ = mimetypes.guess_type(f.file.name)
                image = MIMEImage(
                    data,
                    _subtype=(mime_type.split("/")[1] if mime_type else None),
                )
                image.add_header("Content-ID", f"<img{idx}>")
                image.add_header(
                    "Content-Disposition",
                    "inline",
                    filename=os.path.basename(f.file.name),
                )
                msg.attach(image)
            msg.send(fail_silently=True)

            # Remove from the system on decline
            req.delete()
            messages.success(request, "Request declined and removed.")
            return redirect("ecxtrade_request_list")

        if action == "approve":
            # Create EcxTrade rows (supporting per-line warehouse overrides)
            files = list(req.files.all())
            created = 0
            with transaction.atomic():
                for line in req.receipt_lines:
                    wrn = (line.get("warehouse_receipt_no") or "").strip()
                    qty_str = line.get("quantity")
                    if not wrn or not qty_str:
                        continue
                    qty_val = Decimal(str(qty_str))

                    # Determine warehouse for this line (fallback to request's warehouse)
                    line_wh_id = line.get("warehouse") or req.warehouse_id
                    try:
                        line_wh = Warehouse.objects.get(pk=line_wh_id)
                    except Warehouse.DoesNotExist:
                        messages.error(request, "Invalid warehouse on a receipt line.")
                        return redirect("ecxtrade_request_review", pk=req.pk)

                    # Use per-line symbol/grade if supplied; otherwise fall back to request-level
                    line_symbol = (line.get("symbol") or req.symbol)
                    line_grade = (line.get("grade") or req.grade)

                    # Resolve seed detail and commodity per warehouse (origin can differ)
                    detail = (
                        SeedTypeDetail.objects.filter(
                            symbol=line_symbol,
                            delivery_location=line_wh,
                            grade__icontains=line_grade,
                        ).first()
                    )
                    if not detail:
                        messages.error(request, "Seed type detail not found for a receipt line.")
                        return redirect("ecxtrade_request_review", pk=req.pk)

                    seed_type, _ = SeedType.objects.get_or_create(
                        code=line_symbol, defaults={"name": detail.name}
                    )
                    commodity, _ = Commodity.objects.get_or_create(
                        seed_type=seed_type, origin=detail.origin, grade=line_grade
                    )

                    # Ensure we do not collide with an existing WR number by using
                    # the next available version when needed (v1 for new WRs).
                    max_ver = (
                        EcxTrade.objects.filter(
                            warehouse_receipt_no=wrn
                        ).aggregate(m=Max("warehouse_receipt_version")).get("m")
                    )
                    next_ver = (max_ver or 0) + 1

                    trade = EcxTrade.objects.create(
                        warehouse=line_wh,
                        commodity=commodity,
                        net_obligation_receipt_no=req.net_obligation_receipt_no,
                        warehouse_receipt_no=wrn,
                        warehouse_receipt_version=next_ver,
                        quantity_quintals=qty_val,
                        purchase_date=req.purchase_date,
                        recorded_by=req.created_by,
                        owner=req.owner,
                    )
                    for rf in files:
                        EcxTradeReceiptFile.objects.create(trade=trade, file=rf.file)
                    created += 1
                req.status = EcxTradeRequest.STATUS_APPROVED
                req.decision_by = request.user
                req.decided_at = timezone.now()
                req.decision_note = note
                req.save(update_fields=["status", "decision_by", "decided_at", "decision_note"])

            messages.success(request, f"Approved and registered {created} trade(s).")
            # Redirect accountant to an overview that totals ECX and Contract stocks
            return redirect(
                reverse(
                    "accountant_overview"
                )
                + f"?owner={req.owner_id}&symbol={req.symbol}&grade={req.grade}&purchase_date={req.purchase_date}"
            )

        messages.error(request, "Invalid action.")
        return redirect("ecxtrade_request_review", pk=req.pk)


@method_decorator(login_required, name="dispatch")
class RequestListView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "WareDGT/request_list.html"
    allowed_roles = [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["ecx_requests"] = (
            EcxLoadRequest.objects.filter(
                status=EcxLoadRequest.STATUS_PENDING,
                created_by__profile__role=UserProfile.ECX_AGENT,
            ).order_by("-created_at")
        )
        ctx["bincard_requests"] = (
            BinCardEntryRequest.objects.filter(
                status=BinCardEntryRequest.PENDING,
                created_by__profile__role=UserProfile.WAREHOUSE_OFFICER,
            ).order_by("-created_at")
        )
        # Stock-out requests visibility by role: OM sees PENDING; Admin sees PENDING_SM only.
        prof = getattr(getattr(self.request, "user", None), "profile", None)
        if prof and prof.role == UserProfile.ADMIN:
            ctx["stockout_requests"] = StockOutRequest.objects.none()
            ctx["stockout_requests_sm"] = (
                StockOutRequest.objects.filter(status=StockOutRequest.PENDING_SM).order_by("-created_at")
            )
        else:
            ctx["stockout_requests"] = (
                StockOutRequest.objects.filter(status=StockOutRequest.PENDING).order_by("-created_at")
            )
        return ctx


@method_decorator(login_required, name="dispatch")
class EcxLoadRequestReviewView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    template_name = "WareDGT/ecxload_request_detail.html"
    allowed_roles = [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = get_object_or_404(EcxLoadRequest, pk=kwargs.get("pk"))
        ctx["request_obj"] = req
        ctx["token_ok"] = self.request.GET.get("t") == req.approval_token
        return ctx

    def post(self, request, *args, **kwargs):
        req = get_object_or_404(EcxLoadRequest, pk=kwargs.get("pk"))
        if request.POST.get("t") != req.approval_token:
            messages.error(request, "Invalid or missing approval token.")
            return redirect("ecxload_request_review", pk=req.pk)
        if req.status != EcxLoadRequest.STATUS_PENDING:
            messages.info(request, "Request already decided.")
            return redirect("ecxload_request_review", pk=req.pk)
        if req.created_by_id == request.user.id:
            messages.error(request, "Submitter cannot self-approve or decline.")
            return redirect("ecxload_request_review", pk=req.pk)
        action = request.POST.get("action")
        note = request.POST.get("note", "")
        if action == "approve":
            try:
                approve_load_request(req, request.user)
            except AlreadyProcessed:
                messages.info(request, "Request already decided.")
                return redirect("ecxload_request_review", pk=req.pk)
            req.decision_note = note
            req.save(update_fields=["decision_note"])
            messages.success(request, "Load request approved.")
            self._notify_agent(req, approved=True)
        else:
            req.status = EcxLoadRequest.STATUS_DECLINED
            req.approved_by = request.user
            req.approved_at = timezone.now()
            req.decision_note = note
            req.save(update_fields=["status", "approved_by", "approved_at", "decision_note"])
            messages.info(request, "Load request declined.")
            self._notify_agent(req, approved=False)
        return redirect("request_list")

    def _notify_agent(self, req, approved):
        if not req.created_by.email:
            return
        ctx = {"req": req, "approved": approved}
        subject = ("Approved" if approved else "Declined") + " – ECX Load Request"
        text = render_to_string("emails/ecx_load_result.txt", ctx)
        html = render_to_string("emails/ecx_load_result.html", ctx)
        msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [req.created_by.email])
        msg.attach_alternative(html, "text/html")
        # Attach load request assets first: truck image and any receipt images
        if req.truck_image:
            f = req.truck_image
            try:
                msg.attach_file(f.path)
            except Exception:
                f.open("rb")
                msg.attach(f.name, f.read())
                f.close()
        for rfile in req.receipt_files.all():
            f = rfile.file
            try:
                msg.attach_file(f.path)
            except Exception:
                f.open("rb")
                msg.attach(f.name, f.read())
                f.close()

        # Also include any receipt files already stored on the trades

        for trade in req.trades.all():
            for receipt in trade.receipt_files.all():
                f = receipt.file
                try:
                    msg.attach_file(f.path)
                except Exception:
                    f.open("rb")
                    msg.attach(f.name, f.read())
                    f.close()

        msg.send(fail_silently=True)


@method_decorator(login_required, name="dispatch")
class EcxMovementListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """Display recorded movements of ECX stock."""

    model = EcxMovement
    template_name = "WareDGT/ecxmovement_list.html"
    allowed_roles = ["OPERATIONS_MANAGER", "ADMIN", UserProfile.WEIGHBRIDGE_OPERATOR]
    ordering = ["-purchase_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        role = getattr(getattr(self.request.user, "profile", None), "role", None)
        if role == UserProfile.WEIGHBRIDGE_OPERATOR:
            qs = qs.filter(weighed=False)
        elif role == UserProfile.ECX_AGENT:
            qs = qs.none()
        else:
            qs = qs.filter(weighed=True)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        role = getattr(getattr(self.request.user, "profile", None), "role", None)
        ctx["role"] = role
        return ctx


# Additional CRUD views for QualityAnalysis, DailyRecord, etc.
# can follow the same pattern with LoginRequiredMixin and RoleRequiredMixin


@method_decorator(login_required, name="dispatch")
class WarehouseListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = Warehouse
    template_name = "WareDGT/warehouse_list.html"
    allowed_roles = ["ADMIN"]


@method_decorator(login_required, name="dispatch")
class WarehouseCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = Warehouse
    form_class = WarehouseForm
    template_name = "WareDGT/warehouse_form.html"
    success_url = reverse_lazy("warehouse_list")
    allowed_roles = ["ADMIN"]


@method_decorator(login_required, name="dispatch")
class PurchasedItemTypeListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = PurchasedItemType
    template_name = "WareDGT/itemtype_list.html"
    allowed_roles = ["ADMIN"]


@method_decorator(login_required, name="dispatch")
class PurchasedItemTypeCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = PurchasedItemType
    form_class = PurchasedItemTypeForm
    template_name = "WareDGT/itemtype_form.html"
    success_url = reverse_lazy("itemtype_list")
    allowed_roles = ["ADMIN"]


@method_decorator(login_required, name="dispatch")
class SeedTypeDetailListView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """Display seed types grouped by category and coffee type."""

    template_name = "WareDGT/seedtypedetail_list.html"
    allowed_roles = ["ADMIN"]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["sesame_seed_types"] = SeedTypeDetail.objects.filter(
            category=SeedTypeDetail.SESAME
        )
        ctx["bean_seed_types"] = SeedTypeDetail.objects.filter(
            category=SeedTypeDetail.BEANS
        )
        coffee_groups = {}
        for key, label in SeedTypeDetail.COFFEE_TYPE_CHOICES:
            coffee_groups[label] = SeedTypeDetail.objects.filter(
                category=SeedTypeDetail.COFFEE,
                coffee_type=key,
            )
        ctx["coffee_groups"] = coffee_groups
        ctx["other_seed_types"] = SeedTypeDetail.objects.filter(category=getattr(SeedTypeDetail, 'OTHER', 'OTHER'))
        return ctx


@method_decorator(login_required, name="dispatch")
class SeedTypeDetailCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = SeedTypeDetail
    form_class = SeedTypeDetailForm
    template_name = "WareDGT/seedtypedetail_form.html"
    success_url = reverse_lazy("seedtypedetail_list")
    allowed_roles = ["ADMIN"]


@method_decorator(login_required, name="dispatch")
class UserListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    """Display system users with optional filters."""

    model = User
    template_name = "WareDGT/user_list.html"
    allowed_roles = ["ADMIN"]
    paginate_by = 20

    def get_queryset(self):
        # Exclude superuser from the listing per requirement
        qs = User.objects.select_related("profile").filter(is_superuser=False)
        role = self.request.GET.get("role")
        active = self.request.GET.get("active")
        if role:
            qs = qs.filter(profile__role=role)
        if active in ["true", "false"]:
            qs = qs.filter(is_active=(active == "true"))
        return qs.order_by("username")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["userprofile_role_choices"] = UserProfile.ROLE_CHOICES
        return ctx


@method_decorator(login_required, name="dispatch")
class AccountantOverviewView(LoginRequiredMixin, RoleRequiredMixin, TemplateView):
    """Accountant summary: totals by seed type, owner, and purchase date.

    Warehouse dimension is intentionally ignored per requirement.
    """
    template_name = "WareDGT/accountant_overview.html"
    allowed_roles = [UserProfile.ACCOUNTANT, UserProfile.ADMIN]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        owner_id = self.request.GET.get("owner")
        symbol = self.request.GET.get("symbol")
        grade = self.request.GET.get("grade")
        purchase_date = self.request.GET.get("purchase_date")

        # ECX: group and optionally filter
        ecx_qs = EcxTrade.objects.all()
        if owner_id:
            ecx_qs = ecx_qs.filter(owner_id=owner_id)
        if symbol:
            ecx_qs = ecx_qs.filter(commodity__seed_type__code=symbol)
        if grade:
            ecx_qs = ecx_qs.filter(commodity__grade__icontains=grade)
        if purchase_date:
            ecx_qs = ecx_qs.filter(purchase_date=purchase_date)

        from django.db.models import Sum
        ecx_total = ecx_qs.aggregate(s=Sum("quantity_quintals")).get("s") or 0
        ecx_rows = (
            ecx_qs.values(
                "commodity__seed_type__code",
                "commodity__grade",
                "owner__name",
                "purchase_date",
            )
            .annotate(total=Sum("quantity_quintals"))
            .order_by("-purchase_date", "commodity__seed_type__code", "commodity__grade", "owner__name")
        )

        # Contract movements: total per owner+symbol (no purchase_date dimension available)
        cm_qs = ContractMovement.objects.all()
        if owner_id:
            cm_qs = cm_qs.filter(owner_id=owner_id)
        if symbol:
            cm_qs = cm_qs.filter(symbol=symbol)
        cm_total = cm_qs.aggregate(s=Sum("quantity_quintals")).get("s") or 0
        cm_rows = (
            cm_qs.values("symbol", "owner__name")
            .annotate(total=Sum("quantity_quintals"))
            .order_by("symbol", "owner__name")
        )

        ctx.update(
            {
                "ecx_total": ecx_total,
                "ecx_rows": ecx_rows,
                "cm_total": cm_total,
                "cm_rows": cm_rows,
                "filters": {
                    "owner": owner_id,
                    "symbol": symbol,
                    "grade": grade,
                    "purchase_date": purchase_date,
                },
            }
        )
        return ctx


@method_decorator(login_required, name="dispatch")
class UserCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    """Create a new user and send password setup email."""

    model = User
    form_class = UserCreateForm
    template_name = "WareDGT/user_form.html"
    success_url = reverse_lazy("user_list")
    allowed_roles = ["ADMIN"]

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.object
        email_sent = False
        if user.email:
            uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            set_url = self.request.build_absolute_uri(
                reverse('account_set_password', kwargs={'uidb64': uidb64, 'token': token})
            )
            context = {
                'user': user,
                'set_url': set_url,
            }
            subject = f"Set your password for {getattr(settings, 'PRODUCT_NAME', 'DGT WMS')}"
            text_body = render_to_string('emails/set_password.txt', context)
            html_body = render_to_string('emails/set_password.html', context)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@example.com'),
                to=[user.email],
            )
            msg.attach_alternative(html_body, "text/html")
            try:
                msg.send(fail_silently=False)
                email_sent = True
            except Exception:
                # Log the exception and inform the user without failing the request
                logger.exception("Failed to send set-password email to %s", user.email)
                email_sent = False
        if email_sent:
            messages.success(
                self.request,
                "User created successfully. Password setup email sent.",
            )
        else:
            messages.warning(
                self.request,
                "User created successfully, but sending the password setup email failed. "
                "Please verify email settings/connectivity and resend.",
            )
        return response


@method_decorator(login_required, name="dispatch")
class UserUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    """Edit existing user accounts."""

    model = User
    form_class = UserEditForm
    template_name = "WareDGT/user_form.html"
    success_url = reverse_lazy("user_list")
    allowed_roles = ["ADMIN"]

    def get_initial(self):
        initial = super().get_initial()
        # If the user lacks a profile (e.g. created via admin), provide a default
        profile = getattr(self.object, "profile", None)
        if not profile:
            profile = UserProfile.objects.create(
                user=self.object,
                role=(
                    UserProfile.ADMIN
                    if self.object.is_superuser
                    else UserProfile.WAREHOUSE_OFFICER
                ),
            )
        initial["role"] = profile.role
        initial["warehouses"] = profile.warehouses.all()
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        profile, _ = UserProfile.objects.get_or_create(user=self.object)
        profile.role = form.cleaned_data["role"]
        profile.save()
        profile.warehouses.set(form.cleaned_data.get("warehouses"))
        messages.success(self.request, "User updated successfully.")
        return response


@login_required
def user_toggle_active(request, user_id):
    if not request.user.profile.role == UserProfile.ADMIN:
        messages.error(request, "You do not have permission to do that.")
        return redirect("user_list")

    user = get_object_or_404(User, pk=user_id)
    user.is_active = not user.is_active
    user.save()
    status = "activated" if user.is_active else "deactivated"
    messages.success(request, f"User {status}.")
    return redirect("user_list")


# ----- DRF ViewSets -----

class SeedTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SeedType.objects.all().order_by("name")
    serializer_class = SeedTypeSerializer
    permission_classes = [permissions.IsAuthenticated, AgentReadOnly]


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [permissions.IsAuthenticated, AgentReadOnly]

    def get_queryset(self):
        qs = Warehouse.objects.all()
        category = self.request.query_params.get("category")
        symbol = self.request.query_params.get("symbol")
        grade = self.request.query_params.get("grade")
        owner = self.request.query_params.get("owner")
        if category or symbol or grade:
            filters = {}
            if category:
                filters["seed_type_details__category"] = category
            if symbol:
                filters["seed_type_details__symbol"] = symbol
            if grade:
                filters["seed_type_details__grade__icontains"] = grade
            qs = qs.filter(**filters).distinct()
        # When an owner is selected, limit to warehouses that have
        # unloaded ECX trades for that owner so the map only shows
        # warehouses with stock for the chosen owner.
        if owner:
            qs = qs.filter(ecx_trades__loaded=False, ecx_trades__owner_id=owner).distinct()
        prof = getattr(getattr(self.request, "user", None), "profile", None)
        if prof and prof.role == UserProfile.ECX_AGENT:
            qs = qs.filter(id__in=prof.warehouses.values("id"))
        return qs

    @action(detail=True, methods=["post"], url_path="load")
    def load_stock(self, request, pk=None):
        """Record a load for the selected warehouse and seed type."""
        symbol = request.data.get("symbol")
        # Grade is optional to support multi-grade loads. Treat empty string as
        # no grade filter so different grades of the same seed type can be
        # loaded together.
        grade = request.data.get("grade") or None
        stockline_id = request.data.get("stockline_id")
        qty = request.data.get("quantity")
        loading_date_str = request.data.get("loading_date") or request.query_params.get("loading_date")
        loading_dt = None
        if loading_date_str:
            try:
                ld = datetime.strptime(loading_date_str, "%Y-%m-%d").date()
                loading_dt = timezone.make_aware(datetime.combine(ld, time(12, 0)))
            except Exception:
                loading_dt = None
        # Treat preview a little more forgivingly: allow no quantity and
        # cap over-requests to the available amount so users can still
        # see/select trades even if they typed a larger number.
        preview_only = request.query_params.get("preview") or request.data.get(
            "preview"
        )

        trade_ids = []
        if hasattr(request.data, "getlist"):
            trade_ids = request.data.getlist("trade_ids")
        elif request.data.get("trade_ids"):
            trade_ids = request.data.get("trade_ids")
            if not isinstance(trade_ids, list):
                trade_ids = [trade_ids]
        if stockline_id:
            if not trade_ids:
                trade_ids = [stockline_id]
            elif stockline_id not in trade_ids:
                trade_ids.append(stockline_id)
        file = request.FILES.get("file")
        truck_image = request.FILES.get("truck_image")
        truck_plate_no = str(request.data.get("truck_plate_no") or "").strip()
        trailer_plate_no = str(request.data.get("trailer_plate_no") or "").strip()

        warehouse = self.get_object()
        available_qs = warehouse.ecx_trades.filter(loaded=False)
        # Optional owner scope: when provided, restrict selection/preview
        # to trades owned by the specified company.
        owner_param = request.data.get("owner") or request.query_params.get("owner")
        if owner_param:
            available_qs = available_qs.filter(owner_id=owner_param)

        # Parse optional per-trade allocations sent as fields like alloc_<id>=<qty>
        allocations = {}
        try:
            for k in request.data.keys():
                ks = str(k)
                if ks.startswith("alloc_"):
                    tid = int(ks.split("_", 1)[1])
                    raw = request.data.get(k)
                    if isinstance(raw, list):
                        raw = raw[0]
                    qty_d = Decimal(str(raw))
                    if qty_d > 0:
                        allocations[tid] = qty_d
        except Exception:
            return Response({"error": "Invalid allocations"}, status=400)

        trade_ids_int = []
        if trade_ids:
            try:
                trade_ids_int = [int(t) for t in trade_ids]
            except (TypeError, ValueError):
                return Response({"error": "Invalid trade IDs"}, status=400)
        # If allocations provided without explicit trade_ids, infer them
        if not trade_ids_int and allocations:
            trade_ids_int = list(allocations.keys())

        if trade_ids_int:
            available_qs = available_qs.filter(id__in=trade_ids_int)

        prof = getattr(getattr(request, "user", None), "profile", None)
        if prof and prof.role == UserProfile.ECX_AGENT and not preview_only:
            if not trade_ids_int:
                return Response({"error": "Invalid trade selection"}, status=400)
            trades = list(available_qs)
            if len(trades) != len(trade_ids_int):
                return Response({"error": "Invalid trade selection"}, status=400)
            if EcxLoadRequest.objects.filter(
                status=EcxLoadRequest.STATUS_PENDING, trades__in=trades
            ).exists():
                return Response({"error": "Trade already requested"}, status=400)
            try:
                plombs_val = int(request.data.get("plombs_count", 0))
                trailer_count_val = int(request.data.get("trailer_count", 0))
            except ValueError:
                return Response({"error": "Invalid counts"}, status=400)
            has_trailer = request.data.get("has_trailer") in ["1", "true", "on", "True"]
            payload = {
                "symbol": symbol,
                "grade": grade,
                "trade_ids": trade_ids_int,
                "quantity": str(sum(t.quantity_quintals for t in trades)),
                "loading_date": loading_date_str,
            }
            _create_ecx_load_request(
                request._request,
                request.user,
                warehouse,
                trades,
                plombs_val,
                has_trailer,
                trailer_count_val,
                request.FILES.get("truck_image"),
                payload=payload,
            )
            return Response({"ok": True})

        if trade_ids_int:
            trades = list(available_qs)
            if len(trades) != len(trade_ids_int):
                return Response({"error": "Invalid trade selection"}, status=400)

            # If explicit allocations are provided, use them; otherwise, greedily fill
            if allocations:
                loaded_trades = []
                total_requested = Decimal("0")
                for t in trades:
                    req = allocations.get(t.id, Decimal("0"))
                    if req < 0 or req > t.quantity_quintals:
                        return Response({"error": "Allocation exceeds available for a trade"}, status=400)
                    if req > 0:
                        loaded_trades.append((t, req))
                        total_requested += req
                if qty:
                    try:
                        qty_val = Decimal(qty)
                    except Exception:
                        return Response({"error": "Invalid quantity"}, status=400)
                else:
                    qty_val = total_requested
                # For preview, allow slight mismatch; for final, require match
                if not preview_only and total_requested != qty_val:
                    return Response({"error": "Allocation total does not match requested quantity"}, status=400)
            else:
                total_selected = sum(t.quantity_quintals for t in trades)
                if qty:
                    try:
                        qty_val = Decimal(qty)
                    except Exception:
                        msg = "Invalid quantity"
                        logger.warning(
                            "Load stock failed: %s (symbol=%s grade=%s qty=%s)",
                            msg,
                            symbol,
                            grade,
                            qty,
                        )
                        return Response({"error": msg}, status=400)
                    if qty_val > total_selected:
                        msg = "Quantity exceeds selected stock"
                        logger.warning(
                            "Load stock failed: %s (symbol=%s grade=%s qty=%s selected=%s)",
                            msg,
                            symbol,
                            grade,
                            qty,
                            total_selected,
                        )
                        return Response({"error": msg}, status=400)
                else:
                    qty_val = total_selected

                remaining = qty_val
                loaded_trades = []
                for t in trades:
                    if remaining <= 0:
                        break
                    loaded_qty = min(t.quantity_quintals, remaining)
                    loaded_trades.append((t, loaded_qty))
                    remaining -= loaded_qty
        else:
            if not symbol:
                msg = "Missing fields"
                logger.warning(
                    "Load stock failed: %s (symbol=%s)",
                    msg,
                    symbol,
                )
                return Response({"error": msg}, status=400)
            available_qs = available_qs.filter(
                commodity__seed_type__code=symbol,
            )
            if grade:
                available_qs = available_qs.filter(commodity__grade__icontains=grade)

            # Total available for this warehouse/symbol/grade (unloaded only)
            available = (
                available_qs.aggregate(total=Sum("quantity_quintals"))["total"] or Decimal("0")
            )

            if not qty:
                if preview_only:
                    qty_val = available  # show all available in preview
                else:
                    msg = "Missing fields"
                    logger.warning(
                        "Load stock failed: %s (symbol=%s grade=%s qty=%s)",
                        msg,
                        symbol,
                        grade,
                        qty,
                    )
                    return Response({"error": msg}, status=400)
            else:
                try:
                    qty_val = Decimal(qty)
                except Exception:
                    msg = "Invalid quantity"
                    logger.warning(
                        "Load stock failed: %s (symbol=%s grade=%s qty=%s)",
                        msg,
                        symbol,
                        grade,
                        qty,
                    )
                    return Response({"error": msg}, status=400)

            if qty_val > available:
                msg = "Quantity exceeds available stock"
                logger.warning(
                    "Load stock failed: %s (symbol=%s grade=%s qty=%s available=%s)",
                    msg,
                    symbol,
                    grade,
                    qty,
                    available,
                )
                if not preview_only:
                    return Response({"error": msg}, status=400)
                # For preview, cap to available so user can proceed.
                qty_val = available

            today = timezone.localdate()
            trades = (
                available_qs.annotate(
                    last_pickup=ExpressionWrapper(
                        F("purchase_date") + timedelta(days=5),
                        output_field=DateField(),
                    )
                )
                .annotate(
                    overdue=Case(
                        When(last_pickup__lt=today, then=Value(True)),
                        default=Value(False),
                        output_field=BooleanField(),
                    )
                )
                .order_by("-overdue", "last_pickup")
            )

            remaining = qty_val
            loaded_trades = []
            for t in trades:
                if remaining <= 0:
                    break
                if t.quantity_quintals <= remaining:
                    loaded_qty = t.quantity_quintals
                    remaining -= loaded_qty
                else:
                    loaded_qty = remaining
                    remaining = 0

                loaded_trades.append((t, loaded_qty))

        if not preview_only:
            # Apply DB changes atomically and handle unexpected errors gracefully
            try:
                with transaction.atomic():
                    for t, loaded_qty in loaded_trades:
                        if loaded_qty == t.quantity_quintals:
                            t.loaded = True
                            t.loaded_at = loading_dt or timezone.now()
                            t.save()
                        else:
                            leftover = t.quantity_quintals - loaded_qty
                            t.quantity_quintals = loaded_qty
                            t.loaded = True
                            t.loaded_at = loading_dt or timezone.now()
                            t.save()

                            # Ensure we always create the next available WR version
                            max_ver = (
                                EcxTrade.objects.filter(
                                    warehouse=t.warehouse,
                                    warehouse_receipt_no=t.warehouse_receipt_no,
                                )
                                .aggregate(m=Max("warehouse_receipt_version"))
                                .get("m")
                            )
                            next_ver = (max_ver or t.warehouse_receipt_version) + 1

                            EcxTrade.objects.create(
                                warehouse=t.warehouse,
                                commodity=t.commodity,
                                net_obligation_receipt_no=t.net_obligation_receipt_no,
                                warehouse_receipt_no=t.warehouse_receipt_no,
                                warehouse_receipt_version=next_ver,
                                quantity_quintals=leftover,
                                purchase_date=t.purchase_date,
                                recorded_by=t.recorded_by,
                                owner=t.owner,
                            )
            except Exception as e:
                logger.exception("Error while recording ECX load")
                return Response({"error": f"Server error while saving load: {e}"}, status=500)

        if loaded_trades:
            # Ensure item types exist for all (seed, origin, grade) combos
            for t, _ in loaded_trades:
                PurchasedItemType.objects.get_or_create(
                    seed_type=t.commodity.seed_type.code,
                    origin=t.commodity.origin,
                    grade=t.commodity.grade,
                )
            total_qty = sum(q for _, q in loaded_trades)
            net_receipts = ", ".join(
                t.net_obligation_receipt_no for t, _ in loaded_trades
            )
            wr_receipts = ", ".join(
                f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}"
                for t, _ in loaded_trades
            )
            purchase_date = min(t.purchase_date for t, _ in loaded_trades)
            available_trades = [
                {
                    "id": t.id,
                    "net_obligation_receipt_no": t.net_obligation_receipt_no,
                    "warehouse_receipt_no": f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}",
                    "warehouse_receipt_version": t.warehouse_receipt_version,
                    "purchase_date": t.purchase_date.isoformat(),
                    "purchase_date_ethiopian": to_ethiopian_date_str(t.purchase_date),
                    "grade": t.commodity.grade,
                    "quantity": str(t.quantity_quintals),
                }
                for t in available_qs.order_by("purchase_date")
            ]

            if preview_only:
                load_map = {t.id: q for t, q in loaded_trades}
                if trade_ids_int:
                    available_trades = []
                    for t in available_qs.order_by("purchase_date"):
                        loaded_qty = load_map.get(t.id, 0)
                        if loaded_qty == 0:
                            available_trades.append(
                                {
                                    "id": t.id,
                                    "net_obligation_receipt_no": t.net_obligation_receipt_no,
                                    "warehouse_receipt_no": f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}",
                                    "warehouse_receipt_version": t.warehouse_receipt_version,
                                    "purchase_date": t.purchase_date.isoformat(),
                                    "purchase_date_ethiopian": to_ethiopian_date_str(t.purchase_date),
                                    "grade": t.commodity.grade,
                                    "quantity": str(t.quantity_quintals),
                                }
                            )
                        elif loaded_qty < t.quantity_quintals:
                            available_trades.append(
                                {
                                    "id": None,
                                    "net_obligation_receipt_no": t.net_obligation_receipt_no,
                                    "warehouse_receipt_no": f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version + 1}",
                                    "warehouse_receipt_version": t.warehouse_receipt_version
                                    + 1,
                                    "purchase_date": t.purchase_date.isoformat(),
                                    "purchase_date_ethiopian": to_ethiopian_date_str(t.purchase_date),
                                    "grade": t.commodity.grade,
                                    "quantity": str(t.quantity_quintals - loaded_qty),
                                }
                            )
                else:
                    available_trades = [
                        {
                            "id": t.id,
                            "net_obligation_receipt_no": t.net_obligation_receipt_no,
                            "warehouse_receipt_no": f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}",
                            "warehouse_receipt_version": t.warehouse_receipt_version,
                            "purchase_date": t.purchase_date.isoformat(),
                            "purchase_date_ethiopian": to_ethiopian_date_str(t.purchase_date),
                            "grade": t.commodity.grade,
                            "quantity": str(t.quantity_quintals),
                        }
                        for t in available_qs.order_by("purchase_date")
                    ]

                # Compute per-grade groups for per-group receipt uploads
                group_map = {}
                for t, q in loaded_trades:
                    key = (
                        t.commodity.seed_type.code,
                        t.commodity.origin,
                        t.commodity.grade,
                    )
                    if key not in group_map:
                        group_map[key] = {"qty": Decimal("0"), "trade_ids": []}
                    group_map[key]["qty"] += q
                    group_map[key]["trade_ids"].append(t.id)
                group_items = sorted(
                    [
                        {
                            "symbol": str(k[0]),
                            "origin": str(k[1]),
                            "grade": str(k[2]),
                            "quantity": str(v["qty"]),
                            "trade_ids": v["trade_ids"],
                        }
                        for k, v in group_map.items()
                    ],
                    key=lambda d: (d["symbol"], d["origin"], d["grade"]),
                )
                for idx, g in enumerate(group_items):
                    g["index"] = idx

                return Response(
                    {
                        "net_receipts": net_receipts,
                        "warehouse_receipts": wr_receipts,
                        "trades": [
                            {
                                "id": t.id,
                                "net_obligation_receipt_no": t.net_obligation_receipt_no,
                                "warehouse_receipt_no": f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}",
                                "warehouse_receipt_version": t.warehouse_receipt_version,
                                "purchase_date": t.purchase_date.isoformat(),
                                "purchase_date_ethiopian": to_ethiopian_date_str(t.purchase_date),
                                "grade": t.commodity.grade,
                                "quantity": str(q),
                            }
                            for t, q in loaded_trades
                        ],
                        "total_quantity": str(total_qty),
                        "available_trades": available_trades,
                        "grade_groups": group_items,
                    }
                )

            try:
                with transaction.atomic():
                    # Group trades by (seed, origin, grade) and create one movement per group
                    groups = {}
                    for t, q in loaded_trades:
                        key = (
                            t.commodity.seed_type.code,
                            t.commodity.origin,
                            t.commodity.grade,
                        )
                        if key not in groups:
                            groups[key] = {
                                "trades": [],
                                "qty": Decimal("0"),
                                "purchase_date": t.purchase_date,
                                "owner": t.owner,
                            }
                        g = groups[key]
                        g["trades"].append((t, q))
                        g["qty"] += q
                        if t.purchase_date < g["purchase_date"]:
                            g["purchase_date"] = t.purchase_date

                    # Create parent shipment (truck) to group movements
                    from .models import EcxShipment
                    symbols = sorted({t.commodity.seed_type.code for t, _ in loaded_trades})
                    shipment_symbol = symbols[0] if len(symbols) == 1 else ""
                    shipment = EcxShipment.objects.create(
                        warehouse=warehouse,
                        symbol=shipment_symbol or None,
                        total_quantity=sum(q for _, q in loaded_trades),
                        created_by=request.user,
                        loading_date=loading_dt,
                        truck_plate_no=truck_plate_no,
                        trailer_plate_no=trailer_plate_no,
                        truck_image=truck_image if truck_image else None,
                    )

                    group_items = sorted(
                        groups.items(),
                        key=lambda kv: (str(kv[0][0]), str(kv[0][1]), str(kv[0][2])),
                    )
                    # Collect per-group files named file_0, file_1, ...
                    files_by_index = {}
                    for k in request.FILES.keys():
                        key = str(k)
                        if key.startswith("file_"):
                            try:
                                idx = int(key.split("_")[1])
                                files_by_index[idx] = request.FILES[k]
                            except Exception:
                                pass

                    for idx, ((seed_code, origin, grade_val), g) in enumerate(group_items):
                        itype, _ = PurchasedItemType.objects.get_or_create(
                            seed_type=seed_code,
                            origin=origin,
                            grade=grade_val,
                        )
                        net_receipts_g = ", ".join(t.net_obligation_receipt_no for t, _ in g["trades"])
                        wr_receipts_g = ", ".join(
                            f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}" for t, _ in g["trades"]
                        )
                        mv = EcxMovement.objects.create(
                            warehouse=warehouse,
                            item_type=itype,
                            net_obligation_receipt_no=net_receipts_g,
                            warehouse_receipt_no=wr_receipts_g,
                            quantity_quintals=g["qty"],
                            purchase_date=g["purchase_date"],
                            created_by=request.user,
                            owner=g["owner"],
                            shipment=shipment,
                        )
                        if loading_dt is not None:
                            mv.created_at = loading_dt
                            mv.save(update_fields=["created_at"]) 

                        # Attach per-group file if provided, else fallback to common 'file'
                        file_for_group = files_by_index.get(idx, None) or file
                        if file_for_group:
                            EcxMovementReceiptFile.objects.create(movement=mv, image=file_for_group)
            except Exception as e:
                logger.exception("Error while creating ECX movement")
                return Response({"error": f"Server error while creating movement: {e}"}, status=500)

        logger.info(
            "Recorded ECX load: warehouse=%s symbol=%s grade=%s qty=%s",
            warehouse.id,
            symbol,
            grade,
            qty_val,
        )

        return Response({"success": True})


class LoadRequestViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request):
        prof = getattr(getattr(request, "user", None), "profile", None)
        if not prof or prof.role != UserProfile.ECX_AGENT:
            return Response({"error": "Forbidden"}, status=403)
        warehouse_id = request.data.get("warehouse")
        symbol = request.data.get("symbol")
        grade = request.data.get("grade")
        trade_ids = request.data.get("trade_ids") or []
        loading_date = request.data.get("loading_date")
        if not isinstance(trade_ids, list):
            trade_ids = [trade_ids]
        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id)
        except Warehouse.DoesNotExist:
            return Response({"error": "Invalid warehouse"}, status=400)
        trades = list(
            EcxTrade.objects.filter(id__in=trade_ids, warehouse=warehouse, loaded=False)
        )
        if len(trades) != len(trade_ids):
            return Response({"error": "Invalid trade selection"}, status=400)
        if EcxLoadRequest.objects.filter(
            status=EcxLoadRequest.STATUS_PENDING, trades__in=trades
        ).exists():
            return Response({"error": "Trade already requested"}, status=400)
        payload = {
            "symbol": symbol,
            "grade": grade,
            "trade_ids": [int(t) for t in trade_ids],
            "quantity": str(sum(t.quantity_quintals for t in trades)),
            "loading_date": loading_date,
        }
        req = EcxLoadRequest.objects.create(
            created_by=request.user,
            warehouse=warehouse,
            payload=payload,
            approval_token=get_random_string(48),
        )
        req.trades.set(trades)
        return Response({"id": str(req.id), "status": req.status}, status=201)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        prof = getattr(getattr(request, "user", None), "profile", None)
        if not prof or prof.role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
            return Response({"error": "Forbidden"}, status=403)
        lr = get_object_or_404(EcxLoadRequest, pk=pk)
        try:
            shipment = approve_load_request(lr, request.user)
        except AlreadyProcessed:
            return Response({"error": "already processed"}, status=409)
        data = {
            "id": shipment.id,
            "total_quantity": str(shipment.total_quantity),
            "movements": [
                {
                    "id": mv.id,
                    "item_type": str(mv.item_type),
                    "quantity": str(mv.quantity_quintals),
                }
                for mv in shipment.movements.all().select_related("item_type")
            ],
        }
        return Response(data, status=201)

    @action(detail=True, methods=["post"], url_path="decline")
    def decline(self, request, pk=None):
        prof = getattr(getattr(request, "user", None), "profile", None)
        if not prof or prof.role not in [UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
            return Response({"error": "Forbidden"}, status=403)
        lr = get_object_or_404(EcxLoadRequest, pk=pk)
        if lr.status != EcxLoadRequest.STATUS_PENDING:
            return Response({"error": "already processed"}, status=409)
        lr.status = EcxLoadRequest.STATUS_DECLINED
        lr.approved_by = request.user
        lr.approved_at = timezone.now()
        lr.save(update_fields=["status", "approved_by", "approved_at"])
        return Response({"status": lr.status})


class PurchasedItemTypeViewSet(viewsets.ModelViewSet):
    queryset = PurchasedItemType.objects.all()
    serializer_class = PurchasedItemTypeSerializer
    permission_classes = [permissions.IsAuthenticated, IsEcxOfficer]


class EcxMovementViewSet(viewsets.ModelViewSet):
    queryset = EcxMovement.objects.all().select_related("warehouse", "item_type")
    serializer_class = EcxMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        owner_id = self.request.query_params.get("owner")
        if owner_id:
            qs = qs.filter(owner_id=owner_id)
        weighed_param = self.request.query_params.get("weighed")
        role = getattr(getattr(self.request.user, "profile", None), "role", None)
        if role == UserProfile.WEIGHBRIDGE_OPERATOR:
            if weighed_param is not None:
                val = weighed_param.lower() in ["1", "true", "yes"]
                qs = qs.filter(weighed=val)
            else:
                qs = qs.filter(weighed=False)
        elif role == UserProfile.ECX_AGENT:
            qs = qs.none()
        else:
            if weighed_param is not None:
                val = weighed_param.lower() in ["1", "true", "yes"]
                qs = qs.filter(weighed=val)
            else:
                qs = qs.filter(weighed=True)
        return qs


class ContractMovementViewSet(viewsets.ModelViewSet):
    queryset = ContractMovement.objects.all().select_related("owner")
    serializer_class = ContractMovementSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        status = self.request.query_params.get("status", ContractMovement.IN_TRANSIT)
        owner_id = self.request.query_params.get("owner")
        if status:
            qs = qs.filter(status=status)
        # Safety: avoid returning items already consumed by a bin card
        # (status should already be CONSUMED, but this guards against drift)
        if status == ContractMovement.IN_TRANSIT:
            qs = qs.filter(consumed_by__isnull=True)
        if owner_id:
            qs = qs.filter(owner_id=owner_id)
        return qs


class SeedTypeDetailViewSet(viewsets.ModelViewSet):
    queryset = SeedTypeDetail.objects.all()
    serializer_class = SeedTypeDetailSerializer
    permission_classes = [permissions.IsAuthenticated, AgentReadOnly]

    def get_queryset(self):
        qs = super().get_queryset()
        prof = getattr(self.request.user, "profile", None)
        if prof and prof.role == UserProfile.ECX_AGENT:
            qs = qs.filter(delivery_location__in=prof.warehouses.all())
        return qs


class BinCardViewSet(viewsets.ModelViewSet):
    queryset = BinCard.objects.select_related("owner", "commodity", "warehouse")
    serializer_class = BinCardSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        owner = self.request.query_params.get("owner")
        commodity = self.request.query_params.get("commodity")
        if owner:
            qs = qs.filter(owner_id=owner)
        if commodity:
            qs = qs.filter(commodity_id=commodity)
        return qs

    @action(detail=True, methods=["get"], url_path="series")
    def series(self, request, pk=None):
        """Return time series data for a bin card."""
        bin_card = self.get_object()
        qs = bin_card.transactions.all()
        start = request.query_params.get("from")
        end = request.query_params.get("to")
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        data = []
        for tx in qs.order_by("date", "id"):
            data.append(
                {
                    "ts": tx.date.isoformat(),
                    "balance_kg": float(tx.balance),
                    "inflow_kg": float(tx.qty_in),
                    "outflow_kg": float(tx.qty_out),
                    "capacity_pct": 0.0,
                    "purity_wavg": 0.0,
                    "fifo_age_days": 0.0,
                    "doc_integrity": 100.0,
                    "discrepancy_kg": 0.0,
                    "source_ecx_pct": 100.0,
                    "risk_sar_kg": 0.0,
                }
            )
        return Response(data)

    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, pk=None):
        """Return notable events for a bin card. Placeholder implementation."""
        return Response([])

    @action(detail=True, methods=["get"], url_path="forecast")
    def forecast(self, request, pk=None):
        """Return a naive forecast for a bin card balance."""
        bin_card = self.get_object()
        horizon = request.query_params.get("horizon", "90d")
        try:
            days = int(horizon.rstrip("d"))
        except ValueError:
            days = 90
        last = bin_card.transactions.order_by("-date", "-id").first()
        last_balance = float(last.balance) if last else 0.0
        today = date.today()
        data = []
        for i in range(1, days + 1):
            ts = today + timedelta(days=i)
            data.append(
                {
                    "ts": ts.isoformat(),
                    "p10": last_balance,
                    "p50": last_balance,
                    "p90": last_balance,
                }
            )
        return Response(data)


class DailyRecordViewSet(viewsets.ModelViewSet):
    queryset = DailyRecord.objects.select_related(
        "lot", "warehouse", "owner", "seed_type", "recorded_by"
    )
    serializer_class = DailyRecordSerializer
    permission_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["post"], url_path="post_record")
    def post_record(self, request, pk=None):
        if not request.user.has_perm("WareDGT.can_post_daily_record"):
            return Response(status=403)
        post_daily_record(pk, request.user)
        record = self.get_object()
        serializer = self.get_serializer(record)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="reverse_record")
    def reverse_record(self, request, pk=None):
        if not request.user.has_perm("WareDGT.can_reverse_daily_record"):
            return Response(status=403)
        reverse_posted_daily_record(pk, request.user)
        record = self.get_object()
        serializer = self.get_serializer(record)
        return Response(serializer.data)


class BinCardEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = BinCardEntry.objects.select_related("seed_type", "warehouse")
    serializer_class = BinCardEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        warehouse = self.request.query_params.get("warehouse")
        owner = self.request.query_params.get("owner")
        seed_type = self.request.query_params.get("seed_type")
        grade = self.request.query_params.get("grade")
        purity = self.request.query_params.get("purity")

        if warehouse:
            qs = qs.filter(warehouse_id=warehouse)
        if owner:
            qs = qs.filter(owner_id=owner)
        if seed_type:
            # Accept either SeedTypeDetail id or symbol; match by symbol
            sym = None
            try:
                int(seed_type)
                sym = (
                    SeedTypeDetail.objects.filter(id=seed_type)
                    .values_list("symbol", flat=True)
                    .first()
                )
            except (TypeError, ValueError):
                sym = seed_type
            if sym:
                qs = qs.filter(seed_type__symbol=sym)
            else:
                qs = qs.filter(seed_type_id=seed_type)
        if grade:
            qs = qs.filter(grade=grade)
        if purity:
            try:
                p = Decimal(purity)
                qs = qs.filter(purity__gte=p - PURITY_TOLERANCE, purity__lte=p + PURITY_TOLERANCE)
            except Exception:
                pass
        return qs


class BinCardTransactionViewSet(viewsets.ModelViewSet):
    queryset = BinCardTransaction.objects.select_related("bin_card")
    serializer_class = BinCardTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        bin_card = self.request.query_params.get("bin_card")
        if bin_card:
            qs = qs.filter(bin_card_id=bin_card)
        return qs


class SeedTypeBalanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = SeedTypeBalance.objects.select_related("warehouse", "seed_type")
    serializer_class = SeedTypeBalanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        wh = self.request.query_params.get("warehouse")
        st = self.request.query_params.get("seed_type")
        grade = self.request.query_params.get("grade")
        purity = self.request.query_params.get("purity")
        if wh:
            qs = qs.filter(warehouse_id=wh)
        if st:
            qs = qs.filter(seed_type_id=st)
        if grade:
            qs = qs.filter(grade=grade)
        if purity:
            try:
                p = Decimal(purity)
                qs = qs.filter(
                    purity__gte=p - PURITY_TOLERANCE,
                    purity__lte=p + PURITY_TOLERANCE,
                )
            except Exception:
                pass
        return qs


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_filters(request):
    """Return available filter options derived from BinCardEntry."""
    qs = BinCardEntry.objects.all()
    owners = request.query_params.getlist("owner")
    seed_types = request.query_params.getlist("seed_type")
    grades = request.query_params.getlist("grade")
    purities = request.query_params.getlist("purity")
    warehouses = request.query_params.getlist("warehouse")
    as_of = request.query_params.get("as_of")
    status = request.query_params.get("status")

    if owners:
        qs = qs.filter(owner__name__in=owners)
    if seed_types:
        qs = qs.filter(seed_type__id__in=seed_types)
    if grades:
        qs = qs.filter(grade__in=grades)
    if purities:
        qs = qs.filter(purity__in=purities)
    if warehouses:
        qs = qs.filter(warehouse__id__in=warehouses)
    if as_of:
        qs = qs.filter(date__lte=as_of)
    if status == "cleaned":
        qs = qs.filter(cleaned_weight__gt=0)
    elif status == "uncleaned":
        qs = qs.filter(cleaned_weight=0)

    owner_opts = [
        {"id": str(o["owner__id"]), "name": o["owner__name"], "count": o["n"]}
        for o in qs.values("owner__id", "owner__name").annotate(n=Count("id")).order_by("owner__name")
    ]
    # Aggregate seed types by symbol to avoid duplicates across delivery locations
    seed_opts = [
        {
            "id": str(o["min_id"]),  # canonical id for this symbol
            "symbol": o["seed_type__symbol"],
            "name": o["seed_type__name"],
            "count": o["n"],
        }
        for o in (
            qs.values("seed_type__symbol", "seed_type__name")
            .annotate(n=Count("id"), min_id=Min("seed_type_id"))
            .order_by("seed_type__name")
        )
    ]
    grade_opts = [
        {"value": o["grade"], "count": o["n"]}
        for o in qs.values("grade").annotate(n=Count("id")).order_by("grade")
        if o["grade"]
    ]
    purity_opts = [
        {"value": str(o["purity"]), "count": o["n"]}
        for o in qs.values("purity").annotate(n=Count("id")).order_by("purity")
        if o["purity"] is not None
    ]
    warehouse_opts = [
        {"id": str(o["warehouse__id"]), "code": o["warehouse__code"], "count": o["n"]}
        for o in qs.values("warehouse__id", "warehouse__code")
        .annotate(n=Count("id"))
        .order_by("warehouse__code")
        if o["warehouse__id"]
    ]

    return Response(
        {
            "owners": owner_opts,
            "seed_types": seed_opts,
            "grades": grade_opts,
            "purities": purity_opts,
            "warehouses": warehouse_opts,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def ecx_owners(request):
    """Return owners that currently have unloaded ECX trades.

    Accepts optional category/symbol/grade params to mirror the map filters
    and restrict the owner list contextually.
    """
    from .models import EcxTrade, SeedTypeDetail
    qs = EcxTrade.objects.filter(loaded=False)

    # Restrict to agent's allowed warehouses
    prof = getattr(getattr(request.user, "profile", None), "role", None)
    if prof == UserProfile.ECX_AGENT:
        allowed = request.user.profile.warehouses.all()
        qs = qs.filter(warehouse__in=allowed)

    category = request.query_params.get("category")
    symbol = request.query_params.get("symbol")
    grade = request.query_params.get("grade")

    if category:
        symbols = list(
            SeedTypeDetail.objects.filter(category=category).values_list("symbol", flat=True)
        )
        qs = qs.filter(commodity__seed_type__code__in=symbols)
    if symbol:
        qs = qs.filter(commodity__seed_type__code=symbol)
    if grade:
        qs = qs.filter(commodity__grade__icontains=grade)

    owners = (
        qs.values("owner__id", "owner__name")
        .annotate(n=Count("id"))
        .order_by("owner__name")
    )
    data = [
        {"id": str(o["owner__id"]), "name": o["owner__name"], "count": o["n"]}
        for o in owners
        if o["owner__id"]
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_series(request):
    """Return stock series aggregated from BinCardEntry."""
    from .models import SeedTypeDetail, StockSeries

    qs = StockSeries.objects.all()

    owner = request.query_params.get("owner_id")
    warehouse = request.query_params.get("warehouse_id")
    seed_type = request.query_params.get("seed_type")
    grade = request.query_params.get("grade")
    purity = request.query_params.get("purity")
    start = request.query_params.get("from")
    end = request.query_params.get("to")
    status = request.query_params.get("status")

    if owner:
        qs = qs.filter(owner_id=owner)
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    if seed_type:
        # StockSeries view stores the seed type category, so map the
        # provided SeedTypeDetail ID to its category before filtering.
        seed_cat = (
            SeedTypeDetail.objects.filter(id=seed_type)
            .values_list("category", flat=True)
            .first()
        )
        if seed_cat:
            qs = qs.filter(seed_type=seed_cat)
        else:
            qs = qs.none()
    if grade:
        qs = qs.filter(grade=grade)
    if purity:
        try:
            p = Decimal(purity)
            qs = qs.filter(
                purity_wavg__gte=p - PURITY_TOLERANCE,
                purity_wavg__lte=p + PURITY_TOLERANCE,
            )
        except Exception:
            pass
    if start:
        qs = qs.filter(ts__gte=start)
    if end:
        qs = qs.filter(ts__lte=end)

    data = []
    if status not in ("cleaned", "uncleaned"):
        try:
            for row in qs.order_by("ts").values(
                "ts",
                "balance_kg",
                "inflow_kg",
                "outflow_kg",
                "purity_wavg",
                "doc_integrity",
            ):
                data.append(
                    {
                        "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else row["ts"],
                        "balance_kg": float(row["balance_kg"]),
                        "inflow_kg": float(row["inflow_kg"]),
                        "outflow_kg": float(row["outflow_kg"]),
                        "purity_wavg": float(row["purity_wavg"]) if row["purity_wavg"] is not None else None,
                        "doc_integrity": float(row["doc_integrity"]) if row["doc_integrity"] is not None else None,
                    }
                )
            return Response(data)
        except (ProgrammingError, OperationalError):
            pass

    from collections import defaultdict
    from decimal import Decimal
    from .models import BinCardEntry

    entries = BinCardEntry.objects.all()
    if owner:
        entries = entries.filter(owner_id=owner)
    if warehouse:
        entries = entries.filter(warehouse_id=warehouse)
    if seed_type:
        # Accept either SeedTypeDetail id or symbol; match by symbol to avoid
        # duplicate SeedTypeDetail rows (different delivery locations)
        sym = None
        try:
            # Numeric id path
            int(seed_type)
            sym = (
                SeedTypeDetail.objects.filter(id=seed_type)
                .values_list("symbol", flat=True)
                .first()
            )
        except (TypeError, ValueError):
            sym = seed_type
        if sym:
            entries = entries.filter(seed_type__symbol=sym)
        else:
            entries = entries.filter(seed_type_id=seed_type)
    if grade:
        entries = entries.filter(grade=grade)
    if purity:
        try:
            p = Decimal(purity)
            entries = entries.filter(
                purity__gte=p - PURITY_TOLERANCE,
                purity__lte=p + PURITY_TOLERANCE,
            )
        except Exception:
            pass
    if start:
        entries = entries.filter(date__gte=start)
    if end:
        entries = entries.filter(date__lte=end)
    if status == "cleaned":
        entries = entries.filter(cleaned_weight__gt=0)
    elif status == "uncleaned":
        entries = entries.filter(cleaned_weight=0)
    daily = defaultdict(
        lambda: {
            "inflow": Decimal("0"),
            "outflow": Decimal("0"),
            "purity_sum": Decimal("0"),
            "purity_count": 0,
            "doc_sum": Decimal("0"),
            "doc_count": 0,
        }
    )

    for e in entries.order_by("date"):
        ts = e.date
        desc = (e.description or "").lower()
        if e.weight > 0 and "out" not in desc:
            daily[ts]["inflow"] += e.weight
        if e.weight < 0 or "out" in desc:
            daily[ts]["outflow"] += abs(e.weight)
        if e.purity and e.purity != 0:
            daily[ts]["purity_sum"] += e.purity
            daily[ts]["purity_count"] += 1
        doc_score = 0
        if e.weighbridge_certificate:
            doc_score += 1
        if e.warehouse_document:
            doc_score += 1
        if e.quality_form:
            doc_score += 1
        daily[ts]["doc_sum"] += Decimal(doc_score) / Decimal(3)
        daily[ts]["doc_count"] += 1

    balance = Decimal("0")
    for ts in sorted(daily.keys()):
        inflow = daily[ts]["inflow"]
        outflow = daily[ts]["outflow"]
        purity_wavg = (
            daily[ts]["purity_sum"] / daily[ts]["purity_count"]
            if daily[ts]["purity_count"]
            else None
        )
        doc_integrity = (
            daily[ts]["doc_sum"] / daily[ts]["doc_count"]
            if daily[ts]["doc_count"]
            else None
        )
        balance += inflow - outflow
        data.append(
            {
                "ts": ts.isoformat() if hasattr(ts, "isoformat") else ts,
                "balance_kg": float(balance),
                "inflow_kg": float(inflow),
                "outflow_kg": float(outflow),
                "purity_wavg": float(purity_wavg) if purity_wavg is not None else None,
                "doc_integrity": float(doc_integrity) if doc_integrity is not None else None,
            }
        )

    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_events(request):
    """Return raw BinCardEntry events for plotting."""
    qs = BinCardEntry.objects.all()

    owner = request.query_params.get("owner_id")
    warehouse = request.query_params.get("warehouse_id")
    seed_type = request.query_params.get("seed_type")
    grade = request.query_params.get("grade")
    purity = request.query_params.get("purity")
    start = request.query_params.get("from")
    end = request.query_params.get("to")
    status = request.query_params.get("status")

    if owner:
        qs = qs.filter(owner_id=owner)
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    if seed_type:
        # Accept SeedTypeDetail id or symbol here as well
        sym = None
        try:
            int(seed_type)
            sym = (
                SeedTypeDetail.objects.filter(id=seed_type)
                .values_list("symbol", flat=True)
                .first()
            )
        except (TypeError, ValueError):
            sym = seed_type
        if sym:
            qs = qs.filter(seed_type__symbol=sym)
        else:
            qs = qs.filter(seed_type_id=seed_type)
    if grade:
        qs = qs.filter(grade=grade)
    if purity:
        try:
            p = Decimal(purity)
            qs = qs.filter(purity__gte=p - PURITY_TOLERANCE, purity__lte=p + PURITY_TOLERANCE)
        except Exception:
            pass
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if status == "cleaned":
        qs = qs.filter(cleaned_weight__gt=0)
    elif status == "uncleaned":
        qs = qs.filter(cleaned_weight=0)

    events = []
    for e in qs.order_by("date", "id"):
        # Hide explicit stock-out registration events from the UI feed.
        desc_l = (e.description or "").lower()
        if "stock out" in desc_l or "stock-out" in desc_l:
            continue
        events.append(
            {
                "ts": e.date.isoformat(),
                "type": (e.source_type or "").lower(),
                "message": e.description,
                # Include weight to support client-side fallbacks when the
                # pre-aggregated series view lacks outflow detail. Quintals.
                "weight": float(e.weight) if e.weight is not None else None,
                "num_bags": e.num_bags,
                "car_plate_number": e.car_plate_number,
                "pdf_file": reverse("bincard-pdf", args=[e.pk]),
                "weighbridge_certificate": e.weighbridge_certificate.url if e.weighbridge_certificate else None,
                "warehouse_document": e.warehouse_document.url if e.warehouse_document else None,
                "quality_form": e.quality_form.url if e.quality_form else None,
            }
        )

    return Response(events)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_seed_types_available(request):
    """Return seed types with any available cleaned, reject, or raw stock."""
    owner = request.query_params.get("owner")
    warehouse = request.query_params.get("warehouse")
    data = []
    if owner:
        qs = BinCardEntry.objects.filter(owner_id=owner)
        if warehouse:
            qs = qs.filter(warehouse_id=warehouse)
        grouped = (
            qs.values("seed_type__symbol", "seed_type__name")
            .annotate(
                cleaned=Sum("cleaned_total_kg"),
                reject=Sum("rejects_total_kg"),
                raw=Sum("raw_balance_kg"),
            )
            .filter(Q(cleaned__gt=0) | Q(reject__gt=0) | Q(raw__gt=0))
            .annotate(
                cleaned=Sum("cleaned_total_kg"),
                reject=Sum("rejects_total_kg"),
                raw=Sum("raw_balance_kg"),
            )
            .order_by("seed_type__symbol")
        )
        for g in grouped:
            cleaned_qtl = g.get("cleaned") or Decimal("0")
            reject_qtl = g.get("reject") or Decimal("0")
            raw_qtl = g.get("raw") or Decimal("0")
            if cleaned_qtl > 0 or reject_qtl > 0 or raw_qtl > 0:
                data.append(
                    {
                        "seed_type": g["seed_type__symbol"],
                        "label": g["seed_type__name"],
                        "available_cleaned": str(cleaned_qtl.quantize(Decimal("0.01"))),
                        "available_reject": str(reject_qtl.quantize(Decimal("0.01"))),
                        "available_raw": str(raw_qtl.quantize(Decimal("0.01"))),
                    }
                )
    else:
        qs = SeedTypeBalance.objects.all()
        if warehouse:
            qs = qs.filter(warehouse_id=warehouse)
        grouped = (
            qs.values("seed_type__symbol", "seed_type__name")
            .annotate(cleaned=Sum("cleaned_kg"), reject=Sum("rejects_kg"))
            .order_by("seed_type__symbol")
        )
        for g in grouped:
            cleaned_qtl = g["cleaned"] or Decimal("0")
            reject_qtl = g["reject"] or Decimal("0")
            if cleaned_qtl > 0 or reject_qtl > 0:
                data.append(
                    {
                        "seed_type": g["seed_type__symbol"],
                        "label": g["seed_type__name"],
                        "available_cleaned": str(cleaned_qtl.quantize(Decimal("0.01"))),
                        "available_reject": str(reject_qtl.quantize(Decimal("0.01"))),
                    }
                )
    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_owners_available(request):
    """Return owners that currently have stock on any bin card (cleaned/reject/raw)."""
    grouped = (
        BinCardEntry.objects.values("owner_id", "owner__name")
        .annotate(
            cleaned=Sum("cleaned_total_kg"),
            reject=Sum("rejects_total_kg"),
            raw=Sum("raw_balance_kg"),
        )
        .annotate(
            cleaned=Sum("cleaned_total_kg"),
            reject=Sum("rejects_total_kg"),
            raw=Sum("raw_balance_kg"),
        )
        .filter(Q(cleaned__gt=0) | Q(reject__gt=0) | Q(raw__gt=0))
        .order_by("owner__name")
    )
    data = [
        {"id": g["owner_id"], "name": g["owner__name"]}
        for g in grouped
        if g["owner_id"]
    ]
    return Response(data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_classes_available(request):
    """Return availability by class for a given seed type."""
    seed = request.query_params.get("seed_type")
    owner = request.query_params.get("owner")
    warehouse = request.query_params.get("warehouse")
    if not seed:
        return Response({"error": "seed_type required"}, status=400)
    cleaned = _available_qty_qtl(seed, "cleaned", owner=owner, warehouse=warehouse)
    reject = _available_qty_qtl(seed, "reject", owner=owner, warehouse=warehouse)
    raw = _available_qty_qtl(seed, "raw", owner=owner, warehouse=warehouse)
    return Response({"cleaned": str(cleaned), "reject": str(reject), "raw": str(raw)})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def stock_specs_available(request):
    """Return grade list (if any) and total availability for seed/class."""
    seed = request.query_params.get("seed_type")
    stock_class = request.query_params.get("class")
    owner = request.query_params.get("owner")
    warehouse = request.query_params.get("warehouse")
    if not (seed and stock_class and warehouse):
        return Response({"error": "Missing fields"}, status=400)
    if not Warehouse.objects.filter(id=warehouse, warehouse_type=Warehouse.DGT).exists():
        return Response({"error": "Invalid warehouse"}, status=400)
    total = _available_qty_qtl(seed, stock_class, owner=owner, warehouse=warehouse)
    return Response({"available_total": str(total)})


def _pending_stockout_hold(seed, stock_class, owner=None, warehouse=None, exclude=None):
    """Return the quantity currently reserved by pending stock-out requests."""

    seed_value = getattr(seed, "symbol", seed)
    owner_value = getattr(owner, "pk", owner)
    warehouse_value = getattr(warehouse, "pk", warehouse)

    if not seed_value:
        return Decimal("0")

    pending_qs = StockOutRequest.objects.filter(
        status__in=[StockOutRequest.PENDING, StockOutRequest.PENDING_SM]
    )

    seed_filters = Q(payload__seed_type=str(seed_value))
    seed_pk_value = getattr(seed, "pk", None)
    if not seed_pk_value:
        try:
            possible_uuid = UUID(str(seed_value))
        except (TypeError, ValueError):
            possible_uuid = None
        if possible_uuid:
            seed_pk_value = possible_uuid
        else:
            seed_pk_value = (
                SeedTypeDetail.objects.filter(symbol=str(seed_value))
                .values_list("pk", flat=True)
                .first()
            )
    if seed_pk_value:
        seed_filters |= Q(payload__seed_type=str(seed_pk_value))

    pending_qs = pending_qs.filter(seed_filters)

    class_filters = Q(payload__stock_class=stock_class)
    # Backwards compatibility for legacy payloads that used the ``class`` key.
    class_filters |= Q(payload__class=stock_class)
    pending_qs = pending_qs.filter(class_filters)

    if owner_value:
        pending_qs = pending_qs.filter(payload__owner=str(owner_value))
    if warehouse_value:
        pending_qs = pending_qs.filter(payload__warehouse=str(warehouse_value))

    if exclude:
        try:
            pending_qs = pending_qs.exclude(pk=exclude)
        except Exception:
            pass

    hold_total = Decimal("0")
    for req in pending_qs.only("payload"):
        qty = req.payload.get("quantity")
        if qty in (None, "", False):
            continue
        hold_total += Decimal(str(qty))

    if hold_total <= 0:
        return Decimal("0")

    return hold_total.quantize(Decimal("0.01"))


def _apply_pending_stockout_hold(total, seed, stock_class, owner=None, warehouse=None, exclude=None):
    base_total = Decimal(total or 0)
    hold = _pending_stockout_hold(seed, stock_class, owner, warehouse, exclude=exclude)
    available = base_total - hold
    if available < 0:
        available = Decimal("0")
    return available.quantize(Decimal("0.01"))


def _available_qty_qtl(seed, stock_class, owner=None, warehouse=None, *, exclude_request=None):
    if owner:
        lot_qs = BinCardEntry.objects.filter(seed_type__symbol=seed, owner_id=owner)
        if warehouse:
            lot_qs = lot_qs.filter(warehouse_id=warehouse)
        if stock_class == "cleaned":
            total = lot_qs.aggregate(total=Sum("cleaned_total_kg"))["total"] or Decimal("0")
        elif stock_class == "reject":
            total = lot_qs.aggregate(total=Sum("rejects_total_kg"))["total"] or Decimal("0")
        else:
            total = lot_qs.aggregate(total=Sum("raw_balance_kg"))["total"] or Decimal("0")
        if total:
            return _apply_pending_stockout_hold(total, seed, stock_class, owner, warehouse, exclude=exclude_request)
        qs = SeedTypeBalance.objects.filter(seed_type__symbol=seed, owner_id=owner)
        if warehouse:
            qs = qs.filter(warehouse_id=warehouse)
        if stock_class == "cleaned":
            total = qs.aggregate(total=Sum("cleaned_kg"))["total"]
        elif stock_class == "reject":
            total = qs.aggregate(total=Sum("rejects_kg"))["total"]
        else:
            # No raw in SeedTypeBalance; fall back to lot sums only.
            return _apply_pending_stockout_hold(total or 0, seed, stock_class, owner, warehouse, exclude=exclude_request)

    qs = SeedTypeBalance.objects.filter(seed_type__symbol=seed)
    if warehouse:
        qs = qs.filter(warehouse_id=warehouse)
    if stock_class == "cleaned":
        total = qs.aggregate(total=Sum("cleaned_kg"))["total"]
        if not total:
            lot_qs = BinCardEntry.objects.filter(seed_type__symbol=seed)
            if warehouse:
                lot_qs = lot_qs.filter(warehouse_id=warehouse)
            total = (
                lot_qs.aggregate(total=Sum("cleaned_total_kg"))["total"]
                or Decimal("0")
            )
    elif stock_class == "reject":
        total = qs.aggregate(total=Sum("rejects_kg"))["total"]
        if not total:
            lot_qs = BinCardEntry.objects.filter(seed_type__symbol=seed)
            if warehouse:
                lot_qs = lot_qs.filter(warehouse_id=warehouse)
            total = (
                lot_qs.aggregate(total=Sum("rejects_total_kg"))["total"]
                or Decimal("0")
            )
    else:
        lot_qs = BinCardEntry.objects.filter(seed_type__symbol=seed)
        if warehouse:
            lot_qs = lot_qs.filter(warehouse_id=warehouse)
        total = lot_qs.aggregate(total=Sum("raw_balance_kg"))["total"] or Decimal("0")
    return _apply_pending_stockout_hold(total or 0, seed, stock_class, owner, warehouse, exclude=exclude_request)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def validate_stock_out(request):
    """Server-side validation for stock out quantity."""
    data = request.data.copy()
    ser = StockOutSerializer(data=data)
    if not ser.is_valid():
        return Response(
            {"error": "Missing/invalid fields", "details": ser.errors},
            status=400,
        )
    seed = ser.validated_data["seed_type"]
    stock_class = ser.validated_data["stock_class"]
    qty_val = ser.validated_data["quantity"]
    owner = ser.validated_data["owner"]
    warehouse_id = ser.validated_data["warehouse"]
    if not Warehouse.objects.filter(id=warehouse_id, warehouse_type=Warehouse.DGT).exists():
        return Response({"error": "Invalid warehouse"}, status=400)
    available = _available_qty_qtl(seed, stock_class, owner, warehouse_id)
    if qty_val > available:
        return Response(
            {"error": f"Requested {qty_val} qtl exceeds available {available} qtl."},
            status=409,
        )
    return Response({"ok": True})


def _process_stock_out(data, warehouse, owner, user, entry_date=None, wh_doc=None, wb_cert=None):
    seed = data.get("seed_type")
    stock_class = data.get("stock_class") or data.get("class") or "cleaned"
    qty_val = Decimal(str(data["quantity"]))
    loading_rate = data.get("loading_rate_etb_per_qtl")
    if loading_rate is not None:
        loading_rate = Decimal(str(loading_rate))
    num_bags = data.get("num_bags") or 0
    car_plate = data.get("car_plate_number", "")
    wh_doc_no = data.get("warehouse_document_number", "")
    desc = data.get("description") or (
        "Cleaned product stock out" if stock_class == "cleaned" else "Reject product stock out"
    )

    stb_qs = SeedTypeBalance.objects.select_for_update().filter(
        seed_type__symbol=seed, warehouse=warehouse, owner=owner
    )
    qty_kg = qty_val * Decimal("100")
    remaining = qty_val
    if stock_class == "cleaned":
        rows = list(stb_qs.filter(cleaned_kg__gt=0).order_by("id"))
        for row in rows:
            take = min(row.cleaned_kg, remaining)
            row.cleaned_kg = row.cleaned_kg - take
            row.save(update_fields=["cleaned_kg", "updated_at"])
            remaining -= take
            if remaining <= 0:
                break
    else:
        rows = list(stb_qs.filter(rejects_kg__gt=0).order_by("id"))
        for row in rows:
            take = min(row.rejects_kg, remaining)
            row.rejects_kg = row.rejects_kg - take
            row.save(update_fields=["rejects_kg", "updated_at"])
            remaining -= take
            if remaining <= 0:
                break
    st = SeedTypeDetail.objects.filter(symbol=seed).order_by("id").first()
    if not st:
        raise ValueError(f"Seed type {seed} not found.")

    # Record lot-level transactions without mutating historical BinCardEntry rows.
    # Business rule: Do NOT touch previous bin card entries during stock-out.
    # Only the newly created stock-out entry should carry the negative delta.
    remaining = qty_val
    if stock_class == "cleaned":
        lot_qs = (
            BinCardEntry.objects.select_for_update()
            .filter(
                seed_type=st,
                owner=owner,
                warehouse=warehouse,
                cleaned_total_kg__gt=0,
            )
            .order_by("id")
        )
        movement = BinCardTransaction.CLEANED_OUT
        field = "cleaned_total_kg"
    elif stock_class == "reject":
        lot_qs = (
            BinCardEntry.objects.select_for_update()
            .filter(
                seed_type=st,
                owner=owner,
                warehouse=warehouse,
                rejects_total_kg__gt=0,
            )
            .order_by("id")
        )
        movement = BinCardTransaction.REJECT_OUT
        field = "rejects_total_kg"
    else:
        lot_qs = (
            BinCardEntry.objects.select_for_update()
            .filter(
                seed_type=st,
                owner=owner,
                warehouse=warehouse,
                raw_balance_kg__gt=0,
            )
            .order_by("id")
        )
        movement = BinCardTransaction.RAW_OUT
        field = "raw_balance_kg"

    created_txs = []
    for lot in lot_qs:
        if remaining <= 0:
            break
        avail = getattr(lot, field)
        take = min(avail, remaining)
        # Do not modify 'lot' totals; only record a transaction for traceability.
        tx = BinCardTransaction.objects.create(
            commodity=st,
            lot=lot,
            movement=movement,
            qty_kg=take,
            grade_before=lot.grade,
            grade_after=lot.grade,
        )
        created_txs.append(tx)
        remaining -= take

    StockOut.objects.create(
        seed_type=st,
        stock_class=stock_class,
        quantity_kg=qty_kg,
        created_by=user,
        owner=owner,
        warehouse=warehouse,
    )

    raw_delta = Decimal("0")
    if stock_class == "raw":
        raw_delta = qty_val
    entry = BinCardEntry.objects.create(
        seed_type=st,
        owner=owner,
        grade="",
        warehouse=warehouse,
        in_out_no=next_in_out_no(st, owner=owner, warehouse=warehouse),
        description=desc,
        weight=-qty_val,
        cleaned_total_kg=-qty_val if stock_class == "cleaned" else Decimal("0"),
        rejects_total_kg=-qty_val if stock_class == "reject" else Decimal("0"),
        raw_balance_kg=-raw_delta,
        loading_rate_etb_per_qtl=loading_rate,
        num_bags=num_bags,
        car_plate_number=car_plate,
        weighbridge_certificate=wb_cert,
        warehouse_document_number=wh_doc_no,
        warehouse_document=wh_doc,
    )
    if entry_date is not None:
        type(entry).objects.filter(pk=entry.pk).update(date=entry_date)
        entry.date = entry_date
        try:
            ts = timezone.make_aware(datetime.combine(entry_date, time(12, 0)))
            for tx in created_txs:
                type(tx).objects.filter(pk=tx.pk).update(ts=ts)
        except Exception:
            pass
    get_or_build_bincard_pdf(entry, user)
    return entry


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def register_stock_out(request):
    """Record stock out via API, optionally requiring manager approval."""
    ser = StockOutSerializer(data=request.data)
    if not ser.is_valid():
        return Response(
            {"error": "Missing/invalid fields", "details": ser.errors},
            status=400,
        )
    data = ser.validated_data
    seed = data["seed_type"]
    stock_class = data["stock_class"]
    qty_val = data["quantity"]
    owner_id = data["owner"]
    warehouse_id = data["warehouse"]
    warehouse = Warehouse.objects.filter(id=warehouse_id, warehouse_type=Warehouse.DGT).first()
    if not warehouse:
        return Response({"error": "Invalid warehouse"}, status=400)
    available = _available_qty_qtl(seed, stock_class, owner_id, warehouse_id)
    if qty_val > available:
        return Response(
            {"error": f"Requested {qty_val} qtl exceeds available {available} qtl."},
            status=409,
        )
    owner = Company.objects.filter(pk=owner_id).first()
    if not owner:
        return Response({"error": "Owner not found."}, status=404)

    weighbridge_file = request.FILES.get("weighbridge_certificate") or data.get(
        "weighbridge_certificate"
    )

    payload = json_safe(data)
    payload.pop("warehouse_document", None)
    payload.pop("weighbridge_certificate", None)
    # Support client-supplied idempotency key via header or payload
    idem_key = (
        request.META.get("HTTP_IDEMPOTENCY_KEY")
        or request.data.get("idempotency_key")
        or None
    )
    if idem_key:
        # If we already have a request with this key, return it
        existing = StockOutRequest.objects.filter(idempotency_key=idem_key).first()
        if existing:
            message = (
                "Draft (OUT) created and sent to Logistics Manager for approval."
                if existing.status == StockOutRequest.PENDING
                else f"Request already {existing.status.lower()}."
            )
            return Response(
                {
                    "ok": True,
                    "pending": existing.status == StockOutRequest.PENDING,
                    "notified": existing.status == StockOutRequest.PENDING,
                    "request_id": str(existing.pk),
                    "message": message,
                }
            )
    try:
        req = StockOutRequest.objects.create(
            created_by=request.user,
            approval_token=get_random_string(48),
            payload=payload,
            warehouse=warehouse,
            owner=owner,
            warehouse_document=data.get("warehouse_document"),
            weighbridge_certificate=weighbridge_file or None,
            idempotency_key=idem_key,
            is_borrow=(str(request.data.get("is_borrow", "")).lower() in ["1", "true", "yes"]),
            borrower=(Company.objects.filter(pk=request.data.get("borrower")).first() if request.data.get("borrower") else None),
            borrower_name=(request.data.get("borrower_name") or "").strip() or None,
        )
    except IntegrityError:
        # Handle race where the same idempotency key was inserted concurrently
        if idem_key:
            existing = StockOutRequest.objects.filter(idempotency_key=idem_key).first()
            if existing:
                return Response(
                    {
                        "ok": True,
                        "pending": existing.status == StockOutRequest.PENDING,
                        "notified": existing.status == StockOutRequest.PENDING,
                        "request_id": str(existing.pk),
                        "message": "Duplicate submission ignored.",
                    }
                )
        raise
    _notify_stockout_managers(request, req)
    message = "Draft (OUT) created and sent to Logistics Manager for approval."
    return Response(
        {
            "ok": True,
            "pending": True,
            "notified": True,
            "request_id": str(req.pk),
            "message": message,
        }
    )




@login_required
def bincard_request_review(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    req = get_object_or_404(BinCardEntryRequest, pk=pk)
    token_ok = request.GET.get("t") == req.approval_token
    form_cls = BinCardEntryForm if req.direction == "IN" else CleanedStockOutForm
    form = form_cls(req.payload)
    rows = []
    fk_map = {
        "warehouse": Warehouse,
        "owner": Company,
        "seed_type": SeedTypeDetail,
        "ecx_movement": EcxMovement,
        "contract_movement": ContractMovement,
    }
    skip = {"warehouse_document", "quality_form", "weighbridge_certificate"}
    for name, field in form.fields.items():
        if name in skip:
            continue
        label = field.label or name
        value = req.payload.get(name)
        model = fk_map.get(name)
        if model and value:
            try:
                value = str(model.objects.get(pk=value))
            except Exception:
                pass
        rows.append((label, value))
    ctx = {"req": req, "rows": rows, "token_ok": token_ok}
    return render(request, "WareDGT/bincard/request_review.html", ctx)


@login_required
def approve_bincard_request(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            BinCardEntryRequest.objects.select_for_update(), pk=pk, status=BinCardEntryRequest.PENDING
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        data = req.payload.copy()
        file_fields = ["warehouse_document", "quality_form", "weighbridge_certificate"]
        for f in file_fields:
            data.pop(f, None)
        fk_map = {
            "warehouse": Warehouse,
            "owner": Company,
            "seed_type": SeedTypeDetail,
            "ecx_movement": EcxMovement,
            "contract_movement": ContractMovement,
        }
        for field, model in fk_map.items():
            if data.get(field):
                try:
                    data[field] = model.objects.get(pk=data[field])
                except model.DoesNotExist:
                    data[field] = None
        if req.direction == "IN":
            form = BinCardEntryForm(data)
        else:
            form = CleanedStockOutForm(data)
        if not form.is_valid():
            return JsonResponse({"error": "Payload invalid"}, status=400)
        old_pdf = getattr(req.pdf_file, "name", None)
        if req.direction == "IN":
            entry = form.save(commit=False)
            if req.warehouse_document:
                entry.warehouse_document = req.warehouse_document
            if req.quality_form:
                entry.quality_form = req.quality_form
            if req.weighbridge_certificate:
                entry.weighbridge_certificate = req.weighbridge_certificate
            entry.save()
            get_or_build_bincard_pdf(entry, request.user)
        else:
            if req.warehouse_document:
                form.cleaned_data["warehouse_document"] = req.warehouse_document
            if req.weighbridge_certificate:
                form.cleaned_data["weighbridge_certificate"] = req.weighbridge_certificate
            form.save(user=request.user)
            entry = getattr(form, "bincard_entry", None)
        if entry and entry.pdf_file:
            req.pdf_file.name = entry.pdf_file.name
        req.status = BinCardEntryRequest.APPROVED
        req.save(update_fields=["status", "pdf_file"])
        if old_pdf:
            try:
                default_storage.delete(old_pdf)
            except Exception:
                pass
        _notify_bincard_officer(req, approved=True)
        messages.success(request, "Bin card entry approved.")
    return redirect("request_list")


@login_required
def decline_bincard_request(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            BinCardEntryRequest.objects.select_for_update(), pk=pk, status=BinCardEntryRequest.PENDING
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        if request.method == "POST":
            reason = request.POST.get("reason", "")
            req.reason = reason
            req.status = BinCardEntryRequest.DECLINED
            req.save(update_fields=["status", "reason"])
            _notify_bincard_officer(req, approved=False)
            messages.success(request, "Bin card entry declined.")
            return redirect("request_list")
    return render(request, "WareDGT/bincard/decline_form.html", {"req": req})


@login_required
def stockout_request_review(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    req = get_object_or_404(StockOutRequest, pk=pk)
    token_ok = request.GET.get("t") == req.approval_token
    fk_map = {"warehouse": Warehouse, "owner": Company}
    rows = []
    for name, value in req.payload.items():
        label = name.replace("_", " ").title()
        model = fk_map.get(name)
        if model and value:
            try:
                value = str(model.objects.get(pk=value))
            except Exception:
                pass
        rows.append((label, value))
    # Surface borrow context if present
    if req.is_borrow:
        rows.append(("Borrow", "Yes"))
        rows.append(("Borrower", str(req.borrower) if req.borrower else (req.borrower_name or "")))
    ctx = {"req": req, "rows": rows, "token_ok": token_ok}
    return render(request, "WareDGT/stockout/request_review.html", ctx)


@login_required
def approve_stockout_request(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            StockOutRequest.objects.select_for_update(), pk=pk, status=StockOutRequest.PENDING
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        # Weighbridge slip is optional; proceed if missing
        data = req.payload.copy()
        seed = data["seed_type"]
        stock_class = data["stock_class"]
        qty_val = Decimal(str(data["quantity"]))
        owner_id = data["owner"]
        warehouse_id = data["warehouse"]
        # Exclude this pending request from the available calculation to
        # avoid double-reserving its own quantity.
        available = _available_qty_qtl(
            seed, stock_class, owner_id, warehouse_id, exclude_request=req.pk
        )
        if qty_val > available:
            req.reason = "Insufficient stock"
            req.status = StockOutRequest.DECLINED
            req.save(update_fields=["status", "reason"])
            _notify_stockout_officer(req, approved=False)
            messages.error(request, "Requested quantity exceeds available stock.")
            return redirect("request_list")
        # Borrow flow requires System Manager final approval.
        if req.is_borrow:
            req.status = StockOutRequest.PENDING_SM
            req.lm_approved_by = request.user
            req.lm_approved_at = timezone.now()
            req.save(update_fields=["status", "lm_approved_by", "lm_approved_at"])
            try:
                _notify_stockout_sysmanagers(request, req)
            except Exception:
                pass
            messages.success(request, "Approved by Logistics Manager. Sent to System Manager.")
        else:
            owner = req.owner
            entry = _process_stock_out(
                data,
                req.warehouse,
                owner,
                request.user,
                None,
                req.warehouse_document,
                req.weighbridge_certificate,
            )
            if entry and entry.pdf_file:
                req.pdf_file.name = entry.pdf_file.name
            req.status = StockOutRequest.APPROVED
            req.save(update_fields=["status", "pdf_file"])
            _notify_stockout_officer(req, approved=True)
            messages.success(request, "Stock out approved.")
    return redirect("request_list")


@login_required
def decline_stockout_request(request, pk):
    if getattr(getattr(request.user, "profile", None), "role", None) != UserProfile.OPERATIONS_MANAGER:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            StockOutRequest.objects.select_for_update(), pk=pk, status=StockOutRequest.PENDING
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        if request.method == "POST":
            raw_reason = request.POST.get("reason", "")
            reason = (raw_reason or "").strip()
            if not reason:
                messages.error(request, "Decline reason is required.")
                return render(
                    request,
                    "WareDGT/stockout/decline_form.html",
                    {"req": req, "reason": raw_reason},
                )
            req.reason = reason
            req.status = StockOutRequest.DECLINED
            req.save(update_fields=["status", "reason"])
            _notify_stockout_officer(req, approved=False)
            messages.success(request, "Stock out request declined.")
            return redirect("request_list")
    return render(request, "WareDGT/stockout/decline_form.html", {"req": req, "reason": ""})


@login_required
def stockout_request_review_sm(request, pk):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role != UserProfile.ADMIN:
        return HttpResponseForbidden()
    req = get_object_or_404(StockOutRequest, pk=pk)
    token_ok = request.GET.get("t") == req.approval_token
    fk_map = {"warehouse": Warehouse, "owner": Company}
    rows = []
    for name, value in req.payload.items():
        label = name.replace("_", " ").title()
        model = fk_map.get(name)
        if model and value:
            try:
                value = str(model.objects.get(pk=value))
            except Exception:
                pass
        rows.append((label, value))
    if req.is_borrow:
        rows.append(("Borrow", "Yes"))
        rows.append(("Borrower", str(req.borrower) if req.borrower else (req.borrower_name or "")))
    ctx = {"req": req, "rows": rows, "token_ok": token_ok}
    return render(request, "WareDGT/stockout/request_review.html", ctx)


@login_required
def approve_stockout_request_sm(request, pk):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role != UserProfile.ADMIN:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            StockOutRequest.objects.select_for_update(), pk=pk, status=StockOutRequest.PENDING_SM
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        # Weighbridge slip is optional for SM approval as well
        data = req.payload.copy()
        seed = data["seed_type"]
        stock_class = data["stock_class"]
        qty_val = Decimal(str(data["quantity"]))
        owner_id = data["owner"]
        warehouse_id = data["warehouse"]
        available = _available_qty_qtl(
            seed, stock_class, owner_id, warehouse_id, exclude_request=req.pk
        )
        if qty_val > available:
            req.reason = "Insufficient stock"
            req.status = StockOutRequest.DECLINED
            req.save(update_fields=["status", "reason"])
            _notify_stockout_officer(req, approved=False)
            messages.error(request, "Requested quantity exceeds available stock.")
            return redirect("request_list")
        # If borrow, make PDF description explicit with borrower name and class
        if req.is_borrow:
            d = req.payload.copy()
            cls = d.get("stock_class") or ""
            def _bname():
                if req.borrower:
                    return str(req.borrower)
                if getattr(req, 'borrower_name', None):
                    return str(req.borrower_name)
                return "Unknown"
            d["description"] = f"Borrowed out to {_bname()} – {cls.capitalize()}"
            data = d
        owner = req.owner
        entry = _process_stock_out(
            data,
            req.warehouse,
            owner,
            request.user,
            None,
            req.warehouse_document,
            req.weighbridge_certificate,
        )
        if entry and entry.pdf_file:
            req.pdf_file.name = entry.pdf_file.name
        from decimal import Decimal as _D
        req.status = StockOutRequest.APPROVED
        req.sm_approved_by = request.user
        req.sm_approved_at = timezone.now()
        req.borrowed_outstanding_kg = _D(str(qty_val)) * _D("100") if req.is_borrow else _D("0")
        req.save(update_fields=["status", "pdf_file", "sm_approved_by", "sm_approved_at", "borrowed_outstanding_kg"])

        # If borrower exists in the system and req is borrow, auto-post an inbound
        # entry to the borrower's stock with the correct class (cleaned/raw).
        if req.is_borrow and getattr(req, 'borrower', None):
            # Resolve seed type (payload may store symbol or id)
            seed = data.get("seed_type")
            st = SeedTypeDetail.objects.filter(symbol=str(seed)).first()
            if not st:
                try:
                    st = SeedTypeDetail.objects.filter(pk=int(seed)).first()
                except Exception:
                    st = None
            if st is not None:
                desc_in = f"Borrow received from {owner} – {stock_class.capitalize()}"
                cleaned_delta = qty_val if stock_class == "cleaned" else Decimal("0")
                raw_delta = qty_val if stock_class == "raw" else Decimal("0")
                try:
                    borrower_io = next_in_out_no(st, owner=req.borrower, warehouse=req.warehouse)
                    borrower_entry = BinCardEntry.objects.create(
                        seed_type=st,
                        owner=req.borrower,
                        grade="",
                        warehouse=req.warehouse,
                        in_out_no=borrower_io,
                        description=desc_in,
                        weight=qty_val,
                        cleaned_total_kg=cleaned_delta,
                        rejects_total_kg=Decimal("0"),
                        raw_balance_kg=raw_delta,
                    )
                    get_or_build_bincard_pdf(borrower_entry, request.user)
                except Exception:
                    # Do not block main approval if borrower inbound fails; continue
                    pass

        _notify_stockout_officer(req, approved=True)
        messages.success(request, "Borrow stock-out approved by System Manager.")
    return redirect("request_list")


@login_required
def decline_stockout_request_sm(request, pk):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role != UserProfile.ADMIN:
        return HttpResponseForbidden()
    with transaction.atomic():
        req = get_object_or_404(
            StockOutRequest.objects.select_for_update(), pk=pk, status=StockOutRequest.PENDING_SM
        )
        if not _require_token(req, request.GET.get("t")):
            raise Http404("Invalid or expired request.")
        if request.method == "POST":
            reason = (request.POST.get("reason", "") or "").strip()
            if not reason:
                messages.error(request, "Decline reason is required.")
                return render(request, "WareDGT/stockout/decline_form.html", {"req": req, "reason": ""})
            req.reason = reason
            req.status = StockOutRequest.DECLINED
            req.save(update_fields=["status", "reason"])
            _notify_stockout_officer(req, approved=False)
            messages.success(request, "Stock out request declined.")
            return redirect("request_list")
    return render(request, "WareDGT/stockout/decline_form.html", {"req": req, "reason": ""})


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@transaction.atomic
def register_borrow_return(request):
    """Record the return of borrowed stock back into the warehouse.

    Expects: request_id (StockOutRequest pk), quantity (qtl), optional attachments.
    Only Logistics Manager or System Manager may register returns.
    """
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in (UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN):
        return Response({"error": "Forbidden"}, status=403)
    try:
        req_id = int(request.data.get("request_id"))
    except Exception:
        return Response({"error": "request_id required"}, status=400)
    req = get_object_or_404(StockOutRequest, pk=req_id)
    if not req.is_borrow or req.status not in (StockOutRequest.APPROVED, StockOutRequest.RETURNED):
        return Response({"error": "Not an approved borrow request"}, status=400)
    try:
        qty_qtl = Decimal(str(request.data.get("quantity")))
    except Exception:
        return Response({"error": "Invalid quantity"}, status=400)
    if qty_qtl <= 0:
        return Response({"error": "Quantity must be > 0"}, status=400)
    qty_kg = qty_qtl * Decimal("100")
    if qty_kg > (req.borrowed_outstanding_kg or Decimal("0")):
        return Response({"error": "Return exceeds outstanding"}, status=409)

    data = req.payload.copy()
    seed = data["seed_type"]
    stock_class = data["stock_class"]
    # Seed may be stored as symbol (e.g., 'WHGSS') or as numeric id. Prefer symbol first.
    st = SeedTypeDetail.objects.filter(symbol=str(seed)).first()
    if not st:
        try:
            st = SeedTypeDetail.objects.filter(pk=int(seed)).first()
        except (TypeError, ValueError):
            st = None
    if not st:
        return Response({"error": "Seed type not found"}, status=404)
    # Create a positive ledger entry for the return
    def _borrower_str():
        if req.borrower:
            return str(req.borrower)
        if getattr(req, 'borrower_name', None):
            return str(req.borrower_name)
        return ""
    desc = f"Borrow return ({stock_class}) from {_borrower_str()}" if (req.borrower or req.borrower_name) else f"Borrow return ({stock_class})"
    cleaned_delta = qty_qtl if stock_class == "cleaned" else Decimal("0")
    reject_delta = qty_qtl if stock_class == "reject" else Decimal("0")
    raw_delta = qty_qtl if stock_class == "raw" else Decimal("0")
    entry = BinCardEntry.objects.create(
        seed_type=st,
        owner=req.owner,
        grade="",
        warehouse=req.warehouse,
        in_out_no=next_in_out_no(st, owner=req.owner, warehouse=req.warehouse),
        description=desc,
        weight=qty_qtl,
        cleaned_total_kg=cleaned_delta,
        rejects_total_kg=reject_delta,
        raw_balance_kg=raw_delta,
        car_plate_number=str(request.data.get("car_plate_number") or ""),
        loading_rate_etb_per_qtl=None,
        num_bags=int(request.data.get("num_bags") or 0),
        warehouse_document_number=str(request.data.get("warehouse_document_number") or ""),
        warehouse_document=request.FILES.get("warehouse_document"),
        weighbridge_certificate=request.FILES.get("weighbridge_certificate"),
    )
    get_or_build_bincard_pdf(entry, request.user)

    # Update outstanding
    req.borrowed_outstanding_kg = (req.borrowed_outstanding_kg or Decimal("0")) - qty_kg
    if req.borrowed_outstanding_kg <= 0:
        req.borrowed_outstanding_kg = Decimal("0")
        req.status = StockOutRequest.RETURNED
    req.save(update_fields=["borrowed_outstanding_kg", "status"])
    # Auto-deduct from borrower's stock (if known)
    if getattr(req, 'borrower', None):
        try:
            borrower_desc = f"Borrow return to {req.owner} – {stock_class.capitalize()}"
            borrower_io = next_in_out_no(st, owner=req.borrower, warehouse=req.warehouse)
            borrower_entry = BinCardEntry.objects.create(
                seed_type=st,
                owner=req.borrower,
                grade="",
                warehouse=req.warehouse,
                in_out_no=borrower_io,
                description=borrower_desc,
                weight=-qty_qtl,
                cleaned_total_kg= (-qty_qtl if stock_class == "cleaned" else Decimal("0")),
                rejects_total_kg= Decimal("0"),
                raw_balance_kg= (-qty_qtl if stock_class == "raw" else Decimal("0")),
            )
            get_or_build_bincard_pdf(borrower_entry, request.user)
        except Exception:
            pass
    return Response({"ok": True, "outstanding_kg": str(req.borrowed_outstanding_kg)})


@login_required
def attach_stockout_weighbridge(request, pk):
    """Allow a weighbridge operator to attach a weighbridge slip to a pending stock-out request.

    Once attached, notify the logistics managers and make the request visible in their queue.
    """
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in (UserProfile.WEIGHBRIDGE_OPERATOR, UserProfile.ADMIN):
        return HttpResponseForbidden()
    req = get_object_or_404(StockOutRequest, pk=pk, status=StockOutRequest.PENDING)
    if request.method == "POST":
        file = request.FILES.get("weighbridge_certificate")
        if not file:
            messages.error(request, "Please attach a weighbridge certificate file.")
            return render(request, "WareDGT/stockout/upload_weighbridge.html", {"req": req})
        req.weighbridge_certificate = file
        req.save(update_fields=["weighbridge_certificate"])
        # Notify managers now that the request is complete with required attachments
        try:
            _notify_stockout_managers(request, req)
        except Exception:
            pass
        messages.success(request, "Weighbridge certificate attached and managers notified.")
        # Weighbridge operators don't have access to the manager request list
        return redirect("dashboard")
    return render(request, "WareDGT/stockout/upload_weighbridge.html", {"req": req})


def _notify_bincard_managers(django_request, req):
    managers = User.objects.filter(profile__role=UserProfile.OPERATIONS_MANAGER, is_active=True)
    if not managers:
        return
    ctx = {
        "req": req,
        "approve_url": django_request.build_absolute_uri(
            reverse("approve_bincard_request", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "decline_url": django_request.build_absolute_uri(
            reverse("decline_bincard_request", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "review_url": django_request.build_absolute_uri(
            reverse("bincard_request_review", args=[req.pk]) + f"?t={req.approval_token}"
        ),
    }
    subject = "Action required: Bin Card Entry Approval"
    text = render_to_string("emails/bincard_request.txt", ctx)
    html = render_to_string("emails/bincard_request.html", ctx)
    msg = EmailMultiAlternatives(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [m.email for m in managers if m.email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)


def _notify_bincard_officer(req, approved):
    if not req.created_by.email:
        return
    ctx = {"req": req, "approved": approved}
    subject = ("Approved" if approved else "Declined") + " – Bin Card Entry"
    text = render_to_string("emails/bincard_result.txt", ctx)
    html = render_to_string("emails/bincard_result.html", ctx)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [req.created_by.email])
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)


def _notify_stockout_managers(django_request, req):
    managers = User.objects.filter(profile__role=UserProfile.OPERATIONS_MANAGER, is_active=True)
    if not managers:
        return
    ctx = {
        "req": req,
        "approve_url": django_request.build_absolute_uri(
            reverse("approve_stockout_request", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "decline_url": django_request.build_absolute_uri(
            reverse("decline_stockout_request", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "review_url": django_request.build_absolute_uri(
            reverse("stockout_request_review", args=[req.pk]) + f"?t={req.approval_token}"
        ),
    }
    subject = "Action required: Stock Out Approval"
    text = render_to_string("emails/stockout_request.txt", ctx)
    html = render_to_string("emails/stockout_request.html", ctx)
    msg = EmailMultiAlternatives(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [m.email for m in managers if m.email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)


@login_required
@block_ecx_officer
def local_purchases(request):
    """Read-only Local Purchases page with filters and summaries.

    The submission form has been removed. Local purchases are now registered
    through the Bin Card "Register Stock" workflow.
    """
    role = getattr(getattr(request.user, "profile", None), "role", None)
    if role not in [UserProfile.WAREHOUSE_OFFICER, UserProfile.OPERATIONS_MANAGER, UserProfile.ADMIN]:
        return HttpResponseForbidden("Forbidden")

    # Filters (GET)
    owners = Company.objects.all().order_by("name")
    dgt_wh = Warehouse.objects.filter(warehouse_type=Warehouse.DGT).order_by("name")
    seeds = SeedTypeDetail.objects.all().order_by("symbol")

    sel_owner = request.GET.get("owner") or ""
    sel_wh = request.GET.get("warehouse") or ""
    sel_seed = request.GET.get("seed") or ""
    start = request.GET.get("start") or ""
    end = request.GET.get("end") or ""

    # Base querysets
    pending_qs = (
        BinCardEntryRequest.objects.filter(direction="IN", status=BinCardEntryRequest.PENDING)
        .filter(payload__source_type=BinCardEntry.LOCAL)
        .order_by("-created_at")
    )
    recorded_qs = (
        BinCardEntry.objects.filter(source_type=BinCardEntry.LOCAL)
        .select_related("owner", "seed_type", "warehouse")
        .order_by("-date", "-id")
    )

    # Apply filters
    if sel_owner:
        try:
            recorded_qs = recorded_qs.filter(owner_id=sel_owner)
            pending_qs = pending_qs.filter(payload__owner=sel_owner)
        except Exception:
            pass
    if sel_wh:
        try:
            recorded_qs = recorded_qs.filter(warehouse_id=sel_wh)
            pending_qs = pending_qs.filter(warehouse_id=sel_wh)
        except Exception:
            pass
    if sel_seed:
        try:
            recorded_qs = recorded_qs.filter(seed_type_id=sel_seed)
            pending_qs = pending_qs.filter(payload__seed_type=sel_seed)
        except Exception:
            pass

    def _parse_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    d_start = _parse_date(start)
    d_end = _parse_date(end)
    if d_start:
        recorded_qs = recorded_qs.filter(date__gte=d_start)
        pending_qs = pending_qs.filter(created_at__date__gte=d_start)
    if d_end:
        recorded_qs = recorded_qs.filter(date__lte=d_end)
        pending_qs = pending_qs.filter(created_at__date__lte=d_end)

    # Summaries
    from decimal import Decimal as _D
    recorded = list(recorded_qs[:500])
    recorded_total = sum((_D(getattr(e, "weight", 0) or 0) for e in recorded), _D("0"))
    recorded_count = len(recorded)

    pending = list(pending_qs[:500])
    def _payload_weight(p):
        try:
            return _D(str((p or {}).get("weight") or "0"))
        except Exception:
            return _D("0")
    pending_total = sum((_payload_weight(getattr(r, "payload", {})) for r in pending), _D("0"))
    pending_count = len(pending)

    # Attach friendly names for pending rows (for easier templating)
    owner_map = {str(o.id): o.name for o in owners}
    seed_map = {str(s.id): f"{s.symbol} – {s.name}" for s in seeds}
    wh_map = {str(w.id): w.name for w in dgt_wh}
    for r in pending:
        p = getattr(r, "payload", {}) or {}
        # Avoid leading underscores: Django templates block them
        r.owner_name = owner_map.get(str(p.get("owner")) or "", p.get("owner") or "")
        r.seed_name = seed_map.get(str(p.get("seed_type")) or "", p.get("seed_type") or "")
        r.warehouse_name = getattr(r, "warehouse", None) or wh_map.get(str(p.get("warehouse")) or "", p.get("warehouse") or "")
        try:
            r.weight_display = _D(str(p.get("weight") or "0"))
        except Exception:
            r.weight_display = _D("0")

    ctx = {
        "role": role,
        # Filters
        "owners": owners,
        "warehouses": dgt_wh,
        "seeds": seeds,
        "selected_owner": sel_owner,
        "selected_warehouse": sel_wh,
        "selected_seed": sel_seed,
        "start": start,
        "end": end,
        # Data
        "pending": pending,
        "recorded": recorded,
        # Summaries
        "pending_count": pending_count,
        "pending_total": recorded_total.__class__(pending_total),
        "recorded_count": recorded_count,
        "recorded_total": recorded_total,
    }

    return render(request, "WareDGT/local_purchase_list.html", ctx)


def _notify_stockout_officer(req, approved):
    if not req.created_by.email:
        return
    ctx = {"req": req, "approved": approved}
    subject = ("Approved" if approved else "Declined") + " – Stock Out"
    text = render_to_string("emails/stockout_result.txt", ctx)
    html = render_to_string("emails/stockout_result.html", ctx)
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [req.created_by.email])
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)


def _notify_stockout_sysmanagers(django_request, req):
    """Notify System Managers (ADMIN) to approve borrow stock-outs."""
    admins = User.objects.filter(profile__role=UserProfile.ADMIN, is_active=True)
    if not admins:
        return
    ctx = {
        "req": req,
        "approve_url": django_request.build_absolute_uri(
            reverse("approve_stockout_request_sm", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "decline_url": django_request.build_absolute_uri(
            reverse("decline_stockout_request_sm", args=[req.pk]) + f"?t={req.approval_token}"
        ),
        "review_url": django_request.build_absolute_uri(
            reverse("stockout_request_review_sm", args=[req.pk]) + f"?t={req.approval_token}"
        ),
    }
    subject = "Action required: Borrow Stock Out (System Manager)"
    text = render_to_string("emails/stockout_request_sm.txt", ctx)
    html = render_to_string("emails/stockout_request_sm.html", ctx)
    msg = EmailMultiAlternatives(
        subject,
        text,
        settings.DEFAULT_FROM_EMAIL,
        [u.email for u in admins if u.email],
    )
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=False)


def _require_token(req_obj, token):
    return token and token == req_obj.approval_token


@method_decorator(login_required, name="dispatch")
class ContractMovementRequestReviewView(LoginRequiredMixin, RoleRequiredMixin, View):
    template_name = "WareDGT/contract_movement_request_review.html"
    allowed_roles = [UserProfile.ACCOUNTANT, UserProfile.ADMIN]

    def get(self, request, pk):
        cmr = ContractMovementRequest.objects.filter(pk=pk, status="PENDING").first()
        if not cmr:
            raise Http404("Invalid or expired request.")
        return render(request, self.template_name, {"cmr": cmr})

    def post(self, request, pk):
        with transaction.atomic():
            cmr = (
                ContractMovementRequest.objects.filter(pk=pk, status="PENDING")
                .select_for_update()
                .first()
            )
            if not cmr:
                raise Http404("Invalid or expired request.")

            action = request.POST.get("action")
            reason = (request.POST.get("reason") or "").strip()

            if action == "decline":
                if not reason:
                    messages.error(request, "Decline reason is required.")
                    return render(request, self.template_name, {"cmr": cmr})
                cmr.status = "DECLINED"
                cmr.decision_by = request.user
                cmr.decided_at = timezone.now()
                cmr.decision_note = reason
                cmr.save(
                    update_fields=["status", "decision_by", "decided_at", "decision_note"]
                )
                _notify_submitter_declined(cmr)
                cmr.delete()
                messages.success(request, "Declined and submitter notified.")
                return redirect("contract_movement_request_list")

            if action == "approve":
                data = cmr.payload or {}
                ContractMovement.objects.create(
                    owner=cmr.owner,
                    category=data.get("category", ""),
                    symbol=data.get("symbol", ""),
                    quantity_quintals=Decimal(str(data.get("quantity_quintals", 0))),
                    origin=data.get("origin", ""),
                    agent_name=data.get("agent_name", ""),
                    agent_phone=data.get("agent_phone", ""),
                    advice_number=data.get("advice_number", ""),
                    dispatch_number=data.get("dispatch_number", ""),
                    dispatch_image=cmr.dispatch_image,
                    notes=data.get("notes", ""),
                    created_by=cmr.created_by,
                )
                cmr.status = "APPROVED"
                cmr.decision_by = request.user
                cmr.decided_at = timezone.now()
                cmr.save(update_fields=["status", "decision_by", "decided_at"])
                messages.success(request, "Approved and registered contract stock.")
                return redirect("contract_movement_list")

        messages.error(request, "Invalid action.")
        return render(request, self.template_name, {"cmr": cmr})


@method_decorator(login_required, name="dispatch")
class ContractMovementRequestListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = ContractMovementRequest
    template_name = "WareDGT/contract_movement_request_list.html"
    allowed_roles = [UserProfile.ACCOUNTANT, UserProfile.ADMIN]
    ordering = ["-created_at"]

    def get_queryset(self):
        return super().get_queryset().filter(status="PENDING")
