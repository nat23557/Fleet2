"""Utilities for generating PDF summaries."""

from io import BytesIO
from datetime import datetime, time
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageOps
from PyPDF2 import PdfReader, PdfWriter

from decimal import Decimal
from django.db.models import Sum, Q
from .utils.ethiopian_dates import to_ethiopian_date_str_en
from ethiopian_date import EthiopianDateConverter

from .models import (
    DailyRecord,
    QualityAnalysis,
    QualityCheck,
    BinCardEntry,
)

"""
ReportLab font setup
--------------------

The application uses the Noto Sans Ethiopic typeface to render Amharic text in
generated PDFs. We try, in order:
1) fonts/ folder next to this module
2) common system path /usr/share/fonts/truetype/noto/
3) graceful fallback to Helvetica if unavailable
"""


def _register_font_if_exists(font_name: str, path: Path):
    try:
        if path.exists():
            pdfmetrics.registerFont(TTFont(font_name, str(path)))
            return True
    except Exception:
        pass
    return False


# Try module-local fonts first
FONT_DIR = Path(__file__).resolve().parent / "fonts"
_registered_regular = _register_font_if_exists(
    "NotoSansEthiopic", FONT_DIR / "NotoSansEthiopic-Regular.ttf"
)
_registered_bold = _register_font_if_exists(
    "NotoSansEthiopic-Bold", FONT_DIR / "NotoSansEthiopic-Bold.ttf"
)

# If not found, try common system path
if not _registered_regular:
    _registered_regular = _register_font_if_exists(
        "NotoSansEthiopic",
        Path("/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf"),
    )
if not _registered_bold:
    _registered_bold = _register_font_if_exists(
        "NotoSansEthiopic-Bold",
        Path("/usr/share/fonts/truetype/noto/NotoSansEthiopic-Bold.ttf"),
    )

AMHARIC_FONT = (
    "NotoSansEthiopic"
    if "NotoSansEthiopic" in pdfmetrics.getRegisteredFontNames()
    else "Helvetica"
)
AMHARIC_FONT_BOLD = (
    "NotoSansEthiopic-Bold"
    if "NotoSansEthiopic-Bold" in pdfmetrics.getRegisteredFontNames()
    else "Helvetica-Bold"
)


def _latest_cleaning_ts(entry):
    return (
        DailyRecord.objects.filter(
            lot_id=entry.id,
            operation_type__in=[DailyRecord.CLEANING, DailyRecord.RECLEANING],
            status=DailyRecord.STATUS_POSTED,
        )
        .order_by("-updated_at")
        .values_list("updated_at", flat=True)
        .first()
    )


def is_stale(entry):
    if not entry.pdf_generated_at:
        return True
    latest = _latest_cleaning_ts(entry)
    return bool(latest and latest > entry.pdf_generated_at)


def get_or_build_bincard_pdf(entry, user):
    # Ensure ECX receipt files from the selected movement are linked
    if (
        entry.ecx_movement_id
        and not entry.attachments.filter(kind="ecx_receipt").exists()
    ):
        from .services.bincard import link_ecx_receipts_and_delete_movement

        link_ecx_receipts_and_delete_movement(entry)

    if (not entry.pdf_file) or entry.pdf_dirty or is_stale(entry):
        generate_bincard_pdf(entry, user)
        entry.pdf_generated_at = timezone.now()
        entry.pdf_dirty = False
        if entry.ecx_movement and entry.ecx_movement.pk is None:
            entry.ecx_movement = None
        entry.save(update_fields=["pdf_file", "pdf_generated_at", "pdf_dirty"])
    return entry.pdf_file


def compute_balances_as_of(entry, grade, as_of_ts):
    """Return balances at the current entry using the same rules as the list.

    Series = owner + warehouse + seed symbol.
    We walk the series in order to capture the running totals immediately
    BEFORE the current entry, then apply only the current entry's own deltas
    with the class-specific rule for stock-out rows:
      - cleaned stock-out: reduce cleaned total; keep reject unchanged
      - reject stock-out: reduce reject total; keep cleaned unchanged
    """
    symbol = getattr(entry.seed_type, "symbol", None)
    lot_qs = BinCardEntry.objects.filter(
        owner_id=entry.owner_id,
        warehouse_id=entry.warehouse_id,
    )
    if symbol is not None:
        lot_qs = lot_qs.filter(seed_type__symbol=symbol)
    else:
        lot_qs = lot_qs.filter(seed_type=entry.seed_type)
    lot_qs = lot_qs.order_by("date", "id")
    # Consider up to and including the current entry for ordering, but we will
    # split the running totals into "before current" and apply current deltas.
    lot_qs = lot_qs.filter(
        Q(date__lt=entry.date) | Q(date=entry.date, id__lte=entry.id)
    )

    prev_stock_type = Decimal("0")
    prev_cleaned_type = Decimal("0")
    prev_reject_type = Decimal("0")

    prev_stock_grade = Decimal("0")
    prev_cleaned_grade = Decimal("0")
    prev_reject_grade = Decimal("0")

    for e in lot_qs:
        if e.id == entry.id:
            break
        prev_stock_type += Decimal(e.weight or 0)
        prev_cleaned_type += Decimal(e.cleaned_total_kg or 0)
        prev_reject_type += Decimal(e.rejects_total_kg or 0)
        if (grade or "") == (e.grade or ""):
            prev_stock_grade += Decimal(e.weight or 0)
            prev_cleaned_grade += Decimal(e.cleaned_total_kg or 0)
            prev_reject_grade += Decimal(e.rejects_total_kg or 0)

    # Apply only the current entry deltas, mirroring the list logic
    w = Decimal(entry.weight or 0)
    d_clean = Decimal(entry.cleaned_total_kg or 0)
    d_rej = Decimal(entry.rejects_total_kg or 0)

    stock_type = prev_stock_type + w
    stock_grade = (
        prev_stock_grade + w
        if (grade or "") == (entry.grade or "")
        else prev_stock_grade
    )

    cleaned_type = prev_cleaned_type + d_clean
    reject_type = prev_reject_type + d_rej

    if (grade or "") == (entry.grade or ""):
        cleaned_grade = prev_cleaned_grade + d_clean
        reject_grade = prev_reject_grade + d_rej
    else:
        cleaned_grade = prev_cleaned_grade
        reject_grade = prev_reject_grade

    if not grade:
        stock_grade = stock_type
        cleaned_grade = cleaned_type
        reject_grade = reject_type

    return {
        "stock_type": stock_type,
        "cleaned_type": cleaned_type,
        "reject_type": reject_type,
        "stock_tg": stock_grade,
        "cleaned_tg": cleaned_grade,
        "reject_tg": reject_grade,
    }


def generate_bincard_pdf(entry, user):
    """Generate a styled PDF summary for a bin card entry."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # settings.BASE_DIR may be a string in this project; coerce to Path
    logo_path = Path(settings.BASE_DIR) / "logo.png"
    accent_color = HexColor("#8BC34A")
    subtitle_color = HexColor("#666666")
    side_margin = 72  # 2.5 cm
    page_top_margin = 72
    logo_top_margin = 42  # 1.5 cm
    bottom_margin = 72

    def draw_first_page_header():
        y_header = height - logo_top_margin
        if logo_path.exists():
            logo = ImageReader(str(logo_path))
            logo_w = 230
            img_w, img_h = logo.getSize()
            logo_h = logo_w * img_h / img_w
            c.drawImage(
                logo,
                width / 2 - logo_w / 2,
                y_header - logo_h,
                logo_w,
                logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
            y_header -= logo_h

        y_header -= 14
        c.setFont(AMHARIC_FONT_BOLD, 18)
        c.drawCentredString(width / 2, y_header, "Bin Card Entry")
        y_header -= 22
        c.setFont(AMHARIC_FONT, 14)
        c.setFillColor(subtitle_color)
        c.drawCentredString(width / 2, y_header, "Exporter of Superior Quality")
        c.setFillColor(colors.black)
        y_header -= 20
        c.setStrokeColor(accent_color)
        c.line(side_margin, y_header, width - side_margin, y_header)
        y_header -= 30
        return y_header

    def draw_footer():
        c.setStrokeColor(accent_color)
        c.line(side_margin, 40, width - side_margin, 40)
        c.setFillColor(colors.black)
        c.setFont(AMHARIC_FONT, 9)
        # Keep footer minimal and brand-neutral; contact can be configured later
        c.drawString(
            side_margin, 30, "ThermoFam Trading PLC"
        )
        c.drawRightString(width - side_margin, 30, f"Page {c.getPageNumber()}")

    def new_page():
        draw_footer()
        c.showPage()
        return height - page_top_margin

    y = draw_first_page_header()
    content_width = width - 2 * side_margin
    content_height = height - page_top_margin - bottom_margin
    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        s.fontName = AMHARIC_FONT
    if "Heading1" in styles:
        styles["Heading1"].fontName = AMHARIC_FONT_BOLD
    if "Heading2" in styles:
        styles["Heading2"].fontName = AMHARIC_FONT_BOLD
    if "Heading3" in styles:
        styles["Heading3"].fontName = AMHARIC_FONT_BOLD

    normal = styles["Normal"]
    table_data = [
        ["Date", to_ethiopian_date_str_en(entry.date)],
        ["Owner", str(entry.owner)],
        ["Seed Type", str(entry.seed_type)],
        ["Grade", str(entry.grade or "")],
        ["In/Out No", entry.in_out_no],
    ]
    if entry.car_plate_number:
        table_data.append(["Car Plate Number", entry.car_plate_number])
    table_data.extend(
        [
            ["Description", Paragraph(entry.description or "", normal)],
            ["Weight", f"{entry.weight} quintals"],
        ]
    )
    # Limited scope (third-party) – include simplified refs and rates
    if getattr(entry, "tracking_scope", None) == getattr(
        BinCardEntry, "LIMITED", "LIMITED"
    ):
        if entry.num_bags:
            table_data.append(["Bags", entry.num_bags])
        if entry.pl_no:
            table_data.append(["PL No.", entry.pl_no])
        if entry.r_no:
            table_data.append(["R No.", entry.r_no])
        if entry.service_rate_etb_per_qtl is not None:
            table_data.append(
                ["Service Rate (ETB/qtl)", entry.service_rate_etb_per_qtl]
            )
        if entry.storage_rate_etb_per_day is not None:
            table_data.append(
                ["Storage Rate (ETB/day)", entry.storage_rate_etb_per_day]
            )
        if entry.storage_days is not None:
            table_data.append(["Storage Days", entry.storage_days])
        if entry.storage_fee_etb is not None:
            table_data.append(["Storage Fee (ETB)", entry.storage_fee_etb])
    else:
        # Full scope – include purity as before
        table_data.append(["Purity %", entry.purity])
    header_rows = []
    span_rows = []

    if entry.ecx_movement and getattr(entry, "tracking_scope", None) != getattr(
        BinCardEntry, "LIMITED", "LIMITED"
    ):
        mv = entry.ecx_movement
        header_rows.append(len(table_data))
        table_data.append(["ECX Movement", ""])
        table_data.append(["Warehouse", mv.warehouse])
        table_data.append(["Warehouse Receipt", mv.warehouse_receipt_no])
        table_data.append(["Net Obligation", mv.net_obligation_receipt_no])
        if mv.item_type and len(str(mv.item_type)) > 40:
            table_data.append(["Item Type", ""])
            table_data.append([Paragraph(str(mv.item_type), normal), ""])
            span_rows.append(len(table_data) - 1)
        else:
            table_data.append(["Item Type", str(mv.item_type)])

        table_data.extend(
            [
                ["Quantity", f"{mv.quantity_quintals} qtls"],
                ["Purchase Date", to_ethiopian_date_str_en(mv.purchase_date)],
                ["Owner", mv.owner],
            ]
        )

    qa = (
        QualityAnalysis.objects.select_related("movement")
        .filter(movement__owner_id=entry.owner_id)
        .order_by("-second_test_datetime")
        .first()
    )
    if qa and getattr(entry, "tracking_scope", None) != getattr(
        BinCardEntry, "LIMITED", "LIMITED"
    ):
        header_rows.append(len(table_data))
        table_data.append(["Quality Analysis", ""])
        qa_lines = [
            ("Sound Weight", f"{qa.first_sound_weight}/{qa.second_sound_weight}"),
            ("Foreign Weight", f"{qa.first_foreign_weight}/{qa.second_foreign_weight}"),
            ("Purity %", f"{qa.first_purity_percent}/{qa.second_purity_percent}"),
        ]
        table_data.extend(qa_lines)

    # Collect posted cleaning operations for this lot
    cleaning_qs = list(
        DailyRecord.objects.select_related("warehouse", "lot", "recorded_by")
        .filter(
            lot_id=entry.id,
            operation_type__in=[DailyRecord.CLEANING, DailyRecord.RECLEANING],
            status=DailyRecord.STATUS_POSTED,
        )
        .order_by("date", "id")
    )
    latest_dr = cleaning_qs[-1] if cleaning_qs else None

    table = Table(table_data, colWidths=[150, content_width - 150])
    style_cmds = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
    ]
    for row in header_rows:
        style_cmds.extend(
            [
                ("SPAN", (0, row), (1, row)),
                ("BACKGROUND", (0, row), (1, row), accent_color),
                ("TEXTCOLOR", (0, row), (1, row), colors.white),
                ("FONTNAME", (0, row), (1, row), AMHARIC_FONT_BOLD),
                ("ALIGN", (0, row), (1, row), "CENTER"),
            ]
        )
    for row in span_rows:
        style_cmds.append(("SPAN", (0, row), (1, row)))
    table.setStyle(TableStyle(style_cmds))
    tw, th = table.wrap(content_width, y - bottom_margin)
    if th > y - bottom_margin:
        y = new_page()
    table.drawOn(c, side_margin, y - th)
    y = y - th - 20

    # Cleaning history table (multiple partial operations)
    if cleaning_qs:
        hist_data = [["Cleaning History (Posted)", "", "", "", "", ""]]
        hist_data.append(["Date", "Type", "In", "Out", "Rejects", "Purity (→)"])
        sum_in = Decimal("0")
        sum_out = Decimal("0")
        sum_rej = Decimal("0")
        for dr in cleaning_qs:
            # Numerical Ethiopian date (YYYY-MM-DD) for compact, unambiguous display
            try:
                eth = EthiopianDateConverter.date_to_ethiopian(dr.date)
                date_label = f"{eth.year}-{eth.month:02d}-{eth.day:02d}"
            except Exception:
                # Fallback to Gregorian ISO
                date_label = dr.date.strftime("%Y-%m-%d")

            # Purity change: show with 2 decimals and % sign; handle missing values gracefully
            pur = "—"
            pb = getattr(dr, "purity_before", None)
            pa = getattr(dr, "purity_after", None)
            if pb is not None or pa is not None:
                try:
                    pb_s = "—" if pb is None else f"{Decimal(pb):.2f}%"
                    pa_s = "—" if pa is None else f"{Decimal(pa):.2f}%"
                    pur = f"{pb_s} → {pa_s}"
                except Exception:
                    pur = f"{pb} → {pa}"

            # Numeric columns to 2 decimals for consistency
            try:
                win = f"{Decimal(dr.weight_in):.2f}"
            except Exception:
                win = f"{dr.weight_in}"
            try:
                wout = f"{Decimal(dr.weight_out):.2f}"
            except Exception:
                wout = f"{dr.weight_out}"
            try:
                rj = f"{Decimal(dr.rejects):.2f}"
            except Exception:
                rj = f"{dr.rejects}"

            # Accumulate totals
            try:
                sum_in += Decimal(dr.weight_in or 0)
                sum_out += Decimal(dr.weight_out or 0)
                sum_rej += Decimal(dr.rejects or 0)
            except Exception:
                pass

            hist_data.append([
                date_label,
                dr.get_operation_type_display(),
                win,
                wout,
                rj,
                pur,
            ])
        # Totals row
        hist_data.append(["Totals", "", f"{sum_in:.2f}", f"{sum_out:.2f}", f"{sum_rej:.2f}", ""])
        # Balanced columns: numeric date allows tighter layout
        # Date(100), Type(85), In(65), Out(65), Rejects(65), Purity(rest)
        hist_table = Table(hist_data, colWidths=[100, 85, 65, 65, 65, content_width - 380])
        hist_style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
            ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
            ("FONTNAME", (0, 1), (-1, 1), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 2), (1, -1), "LEFT"),
            ("ALIGN", (2, 2), (4, -1), "RIGHT"),
        ]
        # Emphasize totals row
        last_idx = len(hist_data) - 1
        hist_style += [
            ("FONTNAME", (0, last_idx), (-1, last_idx), AMHARIC_FONT_BOLD),
            ("BACKGROUND", (0, last_idx), (-1, last_idx), colors.HexColor("#eef6f0")),
            ("SPAN", (0, last_idx), (1, last_idx)),
        ]
        hist_table.setStyle(TableStyle(hist_style))
        tw, th = hist_table.wrap(content_width, y - bottom_margin)
        if th > y - bottom_margin:
            y = new_page()
        hist_table.drawOn(c, side_margin, y - th)
        y = y - th - 20

    # Latest cleaning details block (preserve detail view and tests)
    if latest_dr:
        detail_rows = [["Cleaning Details", ""]]
        detail_rows.append(["Operation Type", latest_dr.get_operation_type_display()])
        date_val = to_ethiopian_date_str_en(latest_dr.date)
        if latest_dr.start_time or latest_dr.end_time:
            start = latest_dr.start_time.strftime("%H:%M") if latest_dr.start_time else ""
            end = latest_dr.end_time.strftime("%H:%M") if latest_dr.end_time else ""
            date_val += f" ({start}–{end})"
        detail_rows.append(["Date", date_val])
        if latest_dr.warehouse or latest_dr.lot_id:
            lot_ref = latest_dr.lot.in_out_no if latest_dr.lot else ""
            detail_rows.append(["Warehouse / Lot", f"{latest_dr.warehouse} / {lot_ref}"])
        if latest_dr.passes:
            detail_rows.append(["Passes", latest_dr.passes])
        detail_rows.append(["Weight In/Out", f"{latest_dr.weight_in} / {latest_dr.weight_out} qtl"])
        if latest_dr.rejects:
            detail_rows.append(["Rejects", f"{latest_dr.rejects} qtl ({latest_dr.get_reject_disposition_display()})"])
        if latest_dr.purity_before or latest_dr.purity_after or latest_dr.target_purity:
            pur_line = f"{latest_dr.purity_before} / {latest_dr.purity_after}%"
            if latest_dr.target_purity:
                pur_line += f" (Target {latest_dr.target_purity}%)"
            detail_rows.append(["Purity Before/After", pur_line])
        if latest_dr.shrink_margin:
            detail_rows.append(["Shrink Margin", f"{latest_dr.shrink_margin}%"])
        if latest_dr.cleaning_equipment:
            detail_rows.append(["Equipment / Method", Paragraph(latest_dr.cleaning_equipment, normal)])
        if latest_dr.chemicals_used:
            detail_rows.append(["Chemicals / Materials Used", Paragraph(latest_dr.chemicals_used, normal)])
        personnel = []
        if latest_dr.recorded_by:
            personnel.append(str(latest_dr.recorded_by))
        try:
            personnel.extend(str(u) for u in latest_dr.workers.all())
        except Exception:
            pass
        if personnel:
            detail_rows.append(["Personnel", ", ".join(personnel)])
        if latest_dr.remarks or (latest_dr.operation_type == DailyRecord.RECLEANING and latest_dr.recleaning_reason):
            remark_parts = []
            if latest_dr.remarks:
                remark_parts.append(latest_dr.remarks)
            if latest_dr.operation_type == DailyRecord.RECLEANING and latest_dr.recleaning_reason:
                remark_parts.append(latest_dr.recleaning_reason)
            detail_rows.append(["Remarks", Paragraph(". ".join(remark_parts), normal)])
        detail_table = Table(detail_rows, colWidths=[150, content_width - 150])
        detail_style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
            ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ]
        detail_table.setStyle(TableStyle(detail_style))
        tw, th = detail_table.wrap(content_width, y - bottom_margin)
        if th > y - bottom_margin:
            y = new_page()
        detail_table.drawOn(c, side_margin, y - th)
        y = y - th - 20

    # Balance Summary matrix
    def fmt_q(value):
        return "" if value is None else f"{Decimal(value):.2f}"

    as_of_ts = getattr(entry, "posted_at", None) or getattr(entry, "created_at", None)
    if as_of_ts is None:
        as_of_ts = timezone.make_aware(datetime.combine(entry.date, time.max))
    if latest_dr:
        as_of_ts = latest_dr.posted_at or latest_dr.updated_at or as_of_ts

    agg = compute_balances_as_of(entry, entry.grade, as_of_ts)

    stock_type = entry.initial_stock_balance_type_qtl or agg["stock_type"]
    stock_grade = entry.initial_stock_balance_grade_qtl or agg["stock_tg"]

    balance_data = [
        ["Balance Summary (qtls)", "", ""],
        ["", "Seed Type", "Seed Type & Grade"],
        ["Stock Balance", fmt_q(stock_type), fmt_q(stock_grade)],
        ["Cleaned Balance", fmt_q(agg["cleaned_type"]), fmt_q(agg["cleaned_tg"])],
        ["Reject Balance", fmt_q(agg["reject_type"]), fmt_q(agg["reject_tg"])],
    ]

    bs_table = Table(
        balance_data,
        colWidths=[150, (content_width - 150) / 2, (content_width - 150) / 2],
    )
    bs_style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), AMHARIC_FONT_BOLD),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
        ("FONTNAME", (0, 1), (-1, 1), AMHARIC_FONT_BOLD),
        ("ALIGN", (1, 2), (-1, -1), "RIGHT"),
    ]
    bs_table.setStyle(TableStyle(bs_style))
    tw, th = bs_table.wrap(content_width, y - bottom_margin)
    if th > y - bottom_margin:
        y = new_page()
    bs_table.drawOn(c, side_margin, y - th)
    y = y - th - 20

    # Labor section
    labor_rows = []
    total_labor = Decimal("0")
    if entry.unloading_rate_etb_per_qtl and entry.weight:
        rate = Decimal(entry.unloading_rate_etb_per_qtl)
        qty = Decimal(abs(entry.weight))
        total = (rate * qty).quantize(Decimal("0.01"))
        labor_rows.append(["Unloading", f"{rate}", f"{qty}", f"{total}"])
        total_labor += total
    if entry.loading_rate_etb_per_qtl and entry.weight:
        rate = Decimal(entry.loading_rate_etb_per_qtl)
        qty = Decimal(abs(entry.weight))
        total = (rate * qty).quantize(Decimal("0.01"))
        labor_rows.append(["Loading", f"{rate}", f"{qty}", f"{total}"])
        total_labor += total
    if (
        latest_dr
        and latest_dr.weight_in
        and (
            latest_dr.cleaning_labor_rate_etb_per_qtl
            or latest_dr.labor_rate_per_qtl
        )
    ):
        rate_val = (
            latest_dr.cleaning_labor_rate_etb_per_qtl
            or latest_dr.labor_rate_per_qtl
        )
        rate = Decimal(rate_val)
        qty = Decimal(latest_dr.weight_in)
        total = (rate * qty).quantize(Decimal("0.01"))
        labor_rows.append(["Cleaning", f"{rate}", f"{qty}", f"{total}"])
        total_labor += total
    if (
        latest_dr
        and latest_dr.rejects
        and (
            latest_dr.reject_weighing_rate_etb_per_qtl
            or latest_dr.reject_labor_payment_per_qtl
        )
    ):
        rate_val = (
            latest_dr.reject_weighing_rate_etb_per_qtl
            or latest_dr.reject_labor_payment_per_qtl
        )
        rate = Decimal(rate_val)
        qty = Decimal(latest_dr.rejects)
        total = (rate * qty).quantize(Decimal("0.01"))
        labor_rows.append(["Reject Weighing", f"{rate}", f"{qty}", f"{total}"])
        total_labor += total
    if labor_rows:
        labor_rows.append(
            ["Total Labor (ETB)", "", "", f"{total_labor.quantize(Decimal('0.01'))}"]
        )
        labor_data = [
            ["Labor", "", "", ""],
            ["Operation", "Rate (ETB/qtl)", "Quantity (qtls)", "Total (ETB)"],
        ] + labor_rows
        labor_table = Table(labor_data, colWidths=[120, 100, 100, content_width - 320])
        labor_style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
            ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
            ("FONTNAME", (0, 1), (-1, 1), AMHARIC_FONT_BOLD),
            ("SPAN", (0, len(labor_data) - 1), (2, len(labor_data) - 1)),
            ("ALIGN", (3, 2), (3, len(labor_data) - 1), "RIGHT"),
        ]
        labor_table.setStyle(TableStyle(labor_style))
        tw, th = labor_table.wrap(content_width, y - bottom_margin)
        if th > y - bottom_margin:
            y = new_page()
        labor_table.drawOn(c, side_margin, y - th)
        y = y - th - 20

    # Hourly QC section
    qc_rows = []
    if latest_dr:
        qc_qs = latest_dr.quality_checks.all().order_by("timestamp")
        cumulative_out = Decimal("0.00")
        for qc in qc_qs:
            # Amount taken from logged piece size (qtl)
            amt = getattr(qc, "amount", None) or getattr(qc, "piece_quintals", None)
            # Incremental Out for this QC = piece * purity%
            inc_out = None
            try:
                if amt is not None and qc.purity_percent is not None:
                    piece = Decimal(amt)
                    purity = Decimal(qc.purity_percent)
                    inc_out = (piece * purity / Decimal("100")).quantize(Decimal("0.01"))
                    cumulative_out = (cumulative_out + inc_out).quantize(Decimal("0.01"))
            except Exception:
                inc_out = None
            # Format fields
            try:
                amt_str = f"{Decimal(amt):.2f}" if amt is not None else ""
            except Exception:
                amt_str = f"{amt}" if amt is not None else ""
            out_val = f"{cumulative_out}" if inc_out is not None else ""

            qc_rows.append(
                [
                    amt_str,
                    out_val,
                    f"{qc.purity_percent}",
                    qc.timestamp.strftime("%H:%M"),
                ]
            )
    if qc_rows:
        qc_data = [
            ["Hourly QC (Posted Cleaning)", "", "", ""],
            ["Amt", "Out", "Purity", "Time"],
        ] + qc_rows
        qc_table = Table(qc_data, colWidths=[80, 80, 80, content_width - 240])
        qc_style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTNAME", (0, 0), (-1, -1), AMHARIC_FONT),
            ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), accent_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("BACKGROUND", (0, 1), (-1, 1), colors.lightgrey),
            ("FONTNAME", (0, 1), (-1, 1), AMHARIC_FONT_BOLD),
            ("ALIGN", (0, 2), (-2, -1), "RIGHT"),
        ]
        qc_table.setStyle(TableStyle(qc_style))
        tw, th = qc_table.wrap(content_width, y - bottom_margin)
        if th > y - bottom_margin:
            y = new_page()
        qc_table.drawOn(c, side_margin, y - th)
        y = y - th - 20

    # Removed: Daily Record Output Receipt section

    # Images
    receipt_imgs = []
    wb_field = entry.weighbridge_certificate or (
        entry.ecx_movement.weighbridge_certificate
        if getattr(entry, "ecx_movement", None)
        else None
    )
    other_fields = [
        ("Weighbridge", wb_field),
        ("Warehouse Doc", entry.warehouse_document),
        ("Quality Form", entry.quality_form),
    ]

    receipts = list(entry.attachments.filter(kind="ecx_receipt"))
    for rf in receipts:
        try:
            with Image.open(rf.file.path) as pil_img:
                pil_img = ImageOps.exif_transpose(pil_img)
                receipt_imgs.append(("ECX Receipt", ImageReader(pil_img)))
        except Exception:
            continue

    other_imgs = []

    def draw_two_images(images):
        """Draw up to two images on a page with consistent styling."""
        label_h = 20
        caption_offset = 12
        spacing = 10
        slot_h = (content_height - 40) / 2

        for idx, (label, img) in enumerate(images):
            img_w, img_h = img.getSize()
            max_w = content_width
            max_h = slot_h - label_h - caption_offset - 2 * spacing
            scale = min(max_w / img_w, max_h / img_h)
            draw_w = img_w * scale
            draw_h = img_h * scale
            x = (width - draw_w) / 2
            slot_top = height - page_top_margin - idx * slot_h

            band_bottom = slot_top - label_h
            c.setFillColor(accent_color)
            c.rect(side_margin, band_bottom, content_width, label_h, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont(AMHARIC_FONT_BOLD, 12)
            c.drawCentredString(width / 2, band_bottom + 5, label)

            y_img = band_bottom - spacing - draw_h
            c.setFillColor(colors.lightgrey)
            c.roundRect(x + 3, y_img - 3, draw_w, draw_h, 5, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.drawImage(img, x, y_img, draw_w, draw_h, mask="auto")
            c.setStrokeColor(colors.grey)
            c.roundRect(x, y_img, draw_w, draw_h, 5, stroke=1, fill=0)

            c.setFont(AMHARIC_FONT, 10)
            c.setFillColor(colors.black)
            c.drawCentredString(width / 2, y_img - caption_offset, f"Figure: {label}")

    def draw_full_page_image(label, img):
        """Draw a single image taking an entire page width."""
        label_h = 20
        caption_offset = 12
        spacing = 10

        img_w, img_h = img.getSize()
        max_w = content_width
        max_h = content_height - label_h - caption_offset - 2 * spacing
        scale = min(max_w / img_w, max_h / img_h)
        draw_w = img_w * scale
        draw_h = img_h * scale
        x = (width - draw_w) / 2
        band_bottom = height - page_top_margin - label_h

        c.setFillColor(accent_color)
        c.rect(side_margin, band_bottom, content_width, label_h, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(AMHARIC_FONT_BOLD, 12)
        c.drawCentredString(width / 2, band_bottom + 5, label)

        y_img = band_bottom - spacing - draw_h
        c.setFillColor(colors.lightgrey)
        c.roundRect(x + 3, y_img - 3, draw_w, draw_h, 5, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.drawImage(img, x, y_img, draw_w, draw_h, mask="auto")
        c.setStrokeColor(colors.grey)
        c.roundRect(x, y_img, draw_w, draw_h, 5, stroke=1, fill=0)

        c.setFont(AMHARIC_FONT, 10)
        c.setFillColor(colors.black)
        c.drawCentredString(width / 2, y_img - caption_offset, f"Figure: {label}")

    # Render ECX receipt images first, one per page
    # If this is a Contract Farming entry with no ECX receipts, try to use the
    # dispatch image (saved under warehouse doc attachments) in their place so
    # it appears prominently as the first image section.
    dispatch_promoted = False
    promoted_path = None
    if (
        not receipt_imgs
        and getattr(entry, "source_type", None) == BinCardEntry.CONTRACT
    ):
        # Prefer BinCardAttachment of kind WAREHOUSE_DOC that can be opened as an image
        # Fallback to the entry.warehouse_document file if it is an image
        try:
            doc_atts = list(
                entry.attachments.filter(kind="warehouse_doc").order_by("created_at")
            )
        except Exception:
            doc_atts = []
        found = False
        for att in doc_atts:
            try:
                with Image.open(att.file.path) as pil_img:
                    pil_img = ImageOps.exif_transpose(pil_img)
                    receipt_imgs.append(("Dispatch Image", ImageReader(pil_img)))
                    found = True
                    dispatch_promoted = True
                    promoted_path = getattr(att.file, "path", None)
                    break
            except Exception:
                continue
        if not found and entry.warehouse_document:
            try:
                with Image.open(entry.warehouse_document.path) as pil_img:
                    pil_img = ImageOps.exif_transpose(pil_img)
                    receipt_imgs.append(("Dispatch Image", ImageReader(pil_img)))
                    dispatch_promoted = True
                    promoted_path = getattr(entry.warehouse_document, "path", None)
            except Exception:
                pass
    # (Re)build the gallery images, skipping the promoted dispatch image
    # 1) Model file fields (weighbridge, warehouse doc, quality form)
    other_imgs = []
    for label, file_field in other_fields:
        if not file_field:
            continue
        try:
            path = getattr(file_field, "path", None)
            if promoted_path and path == promoted_path:
                continue
            with Image.open(path) as pil_img:
                pil_img = ImageOps.exif_transpose(pil_img)
                other_imgs.append((label, ImageReader(pil_img)))
        except Exception:
            continue

    # 2) Include weighbridge attachments (extra certificates)
    try:
        wb_atts = list(
            entry.attachments.filter(kind="weighbridge").order_by("created_at")
        )
    except Exception:
        wb_atts = []
    for att in wb_atts:
        try:
            path = getattr(att.file, "path", None)
            with Image.open(path) as pil_img:
                pil_img = ImageOps.exif_transpose(pil_img)
                other_imgs.append(("Weighbridge", ImageReader(pil_img)))
        except Exception:
            continue

    # 3) Include any warehouse_doc attachments (dispatch images), except the promoted one
    try:
        doc_atts_all = list(
            entry.attachments.filter(kind="warehouse_doc").order_by("created_at")
        )
    except Exception:
        doc_atts_all = []
    for att in doc_atts_all:
        try:
            path = getattr(att.file, "path", None)
            if promoted_path and path == promoted_path:
                continue
            with Image.open(path) as pil_img:
                pil_img = ImageOps.exif_transpose(pil_img)
                # Avoid duplicate if already promoted to full page
                label = (
                    "Dispatch Image"
                    if getattr(entry, "source_type", None) == BinCardEntry.CONTRACT
                    else "Warehouse Doc"
                )
                other_imgs.append((label, ImageReader(pil_img)))
        except Exception:
            continue
    for label, img in receipt_imgs:
        y = new_page()
        draw_full_page_image(label, img)

    # Render remaining images two per page
    for i in range(0, len(other_imgs), 2):
        y = new_page()
        draw_two_images(other_imgs[i : i + 2])

    draw_footer()
    c.save()

    pdf_content = buffer.getvalue()
    buffer.close()

    # Attach original ECX receipt files to the generated PDF
    receipts = list(entry.attachments.filter(kind="ecx_receipt"))
    if entry.source_type == BinCardEntry.ECX and not receipts:
        raise ValueError("ECX movement requires attached receipt files")

    attach_fields = [wb_field, entry.warehouse_document]
    # For Contract Farming, also attach dispatch image(s) saved as warehouse docs
    contract_docs = []
    if getattr(entry, "source_type", None) == BinCardEntry.CONTRACT:
        try:
            contract_docs = list(entry.attachments.filter(kind="warehouse_doc"))
        except Exception:
            contract_docs = []

    # Additional weighbridge attachments beyond the main field
    try:
        wb_docs = list(entry.attachments.filter(kind="weighbridge"))
    except Exception:
        wb_docs = []

    if receipts or any(attach_fields) or contract_docs or wb_docs:
        reader = PdfReader(BytesIO(pdf_content))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for rf in receipts:
            filename = Path(rf.file.name).name
            with rf.file.open("rb") as fh:
                writer.add_attachment(filename, fh.read())
        for ff in attach_fields:
            if ff:
                filename = Path(ff.name).name
                with ff.open("rb") as fh:
                    writer.add_attachment(filename, fh.read())
        for att in contract_docs:
            try:
                filename = Path(att.file.name).name
                with att.file.open("rb") as fh:
                    writer.add_attachment(filename, fh.read())
            except Exception:
                continue
        for att in wb_docs:
            try:
                filename = Path(att.file.name).name
                with att.file.open("rb") as fh:
                    writer.add_attachment(filename, fh.read())
            except Exception:
                continue
        out_buf = BytesIO()
        writer.write(out_buf)
        pdf_content = out_buf.getvalue()
        out_buf.close()

    path = f"bincard/{entry.pk}.pdf"
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(pdf_content))
    entry.pdf_file.name = path


def generate_dailyrecord_receipt_pdf(record):
    """Deprecated: Daily Record Output Receipt removed. Kept for backward imports."""
    # Return an empty 1-page PDF note for compatibility if ever called
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont(AMHARIC_FONT_BOLD, 14)
    c.drawCentredString(A4[0]/2, A4[1]/2, "Daily Record Output Receipt is discontinued")
    c.showPage()
    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    return ContentFile(pdf, name=f"dailyrecord_{record.pk}_receipt_removed.pdf")


def generate_ecxtrade_pdf(trade):
    """Generate a simple PDF summary for a single ECX trade, including NOR.

    The resulting PDF includes a summary table with key fields and attaches any
    uploaded receipt files for that trade (images or PDFs) as embedded attachments.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header with logo and title
    logo_path = settings.BASE_DIR / "logo.png"
    top = height - 72
    if logo_path.exists():
        try:
            logo = ImageReader(str(logo_path))
            c.drawImage(logo, 72, top - 40, 80, 40, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFont(AMHARIC_FONT_BOLD, 16)
    c.drawString(72 + 90, top - 16, "ECX Trade Summary")

    # Summary table
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    data = [
        ["Warehouse", str(trade.warehouse)],
        ["Owner", str(getattr(trade, "owner", "") or "-")],
        ["Commodity", str(trade.commodity)],
        ["Net Obligation", str(trade.net_obligation_receipt_no)],
        ["Warehouse Receipt", str(getattr(trade, "warehouse_receipt_no", ""))],
        ["Quantity", f"{trade.quantity_quintals} qtls"],
        ["Purchase Date", to_ethiopian_date_str_en(trade.purchase_date)],
    ]
    table = Table(data, colWidths=[130, width - 130 - 144])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#2b3942")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1a21")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#c8d1d9")),
                ("FONT", (0, 0), (-1, -1), AMHARIC_FONT, 10),
                ("FONT", (0, 0), (-1, 0), AMHARIC_FONT_BOLD, 10),
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    # Draw table below the header
    w, h = table.wrapOn(c, width - 144, height)
    table.drawOn(c, 72, top - 60 - h)

    c.showPage()
    c.save()

    pdf_content = buffer.getvalue()
    buffer.close()

    # Attach trade receipt files (if any)
    files = list(getattr(trade, "receipt_files", []).all())
    if files:
        try:
            reader = PdfReader(BytesIO(pdf_content))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            for rf in files:
                try:
                    name = Path(rf.file.name).name
                    with rf.file.open("rb") as fh:
                        writer.add_attachment(name, fh.read())
                except Exception:
                    continue
            out_buf = BytesIO()
            writer.write(out_buf)
            pdf_content = out_buf.getvalue()
            out_buf.close()
        except Exception:
            pass

    return ContentFile(pdf_content, name=f"ecx_trade_{trade.pk}.pdf")
