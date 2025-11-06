from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from email.mime.image import MIMEImage

try:
    from PyPDF2 import PdfReader, PdfWriter
except Exception:  # pragma: no cover - optional
    PdfReader = None  # type: ignore
    PdfWriter = None  # type: ignore

from weasyprint import HTML, CSS


def _get_model(label: str):
    app_label, model_name = label.split('.')
    return apps.get_model(app_label, model_name)


def _get_font_data_uri(font_path: str) -> str:
    absolute_path = finders.find(font_path)
    if not absolute_path:
        raise Exception(f"Font file {font_path} not found.")
    with open(absolute_path, "rb") as f:
        data = f.read()
    base64_data = base64.b64encode(data).decode("utf-8")
    return f"data:font/truetype;charset=utf-8;base64,{base64_data}"


def send_trip_completion_email(trip, base_url: Optional[str] = None) -> None:
    """Send the completion email (with PDF) to management for a Trip.

    Works without a request. Uses file-based URLs for assets when needed.
    """
    TripFinancial = _get_model('transportation.TripFinancial')
    Invoice = _get_model('transportation.Invoice')
    Staff = _get_model('transportation.Staff')

    # Ensure we have financial data
    try:
        financial, _ = TripFinancial.objects.get_or_create(trip=trip)
        try:
            financial.update_financials()
        except Exception:
            pass
    except Exception:
        financial = None

    # Collect related objects
    invoice = None
    try:
        invoice = Invoice.objects.filter(trip_id=trip.id).first()
    except Exception:
        pass

    # Build context
    context = {
        'trip': trip,
        'financial': financial,
        'expenses': list(getattr(financial, 'expenses', []).all()) if financial else [],
        'invoice': invoice,
        'user': None,
        'current_time': timezone.now(),
        'font_data_uri': _get_font_data_uri("fonts/NotoSansEthiopic-Regular.ttf"),
        'map_data_url': '',
        'user_role': None,
        'company_name': getattr(settings, 'COMPANY_NAME', 'Thermofam Trading PLC'),
        'company_tagline': getattr(settings, 'COMPANY_TAGLINE', 'Exporter of Superior Quality'),
    }

    # Absolute paths/URLs for images in PDF
    if invoice and getattr(invoice, 'attached_image', None):
        try:
            path = invoice.attached_image.path
            context['absolute_invoice_image_url'] = f"file://{path}"
        except Exception:
            context['absolute_invoice_image_url'] = None
    else:
        context['absolute_invoice_image_url'] = None

    details_list = []
    if financial and hasattr(financial, 'expense_details'):
        for detail in financial.expense_details.all():
            try:
                if detail.image:
                    detail.absolute_image_url = f"file://{detail.image.path}"
                else:
                    detail.absolute_image_url = None
            except Exception:
                detail.absolute_image_url = None
            details_list.append(detail)
    context['operational_expense_details'] = details_list

    # Render PDF content
    html_string = render_to_string("transportation/trip_pdf_email.html", context)
    css_path = finders.find('css/pdf_styles.css')
    if not css_path:
        raise Exception("CSS file for PDF styling not found.")
    pdf_css = CSS(filename=css_path)

    # Use a filesystem base URL so WeasyPrint can resolve local assets
    if not base_url:
        # Prefer STATIC_ROOT if set (collected files), else BASE_DIR
        base_url = getattr(settings, 'STATIC_ROOT', None) or getattr(settings, 'BASE_DIR', '.')

    pdf_file = HTML(string=html_string, base_url=base_url).write_pdf(stylesheets=[pdf_css])

    # Embed invoice image into PDF as attachment if possible
    if PdfReader and PdfWriter and invoice and getattr(invoice, 'attached_image', None):
        try:
            reader = PdfReader(BytesIO(pdf_file))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            filename = getattr(invoice.attached_image, 'name', 'invoice_image')
            with invoice.attached_image.open('rb') as fh:
                writer.add_attachment(filename.split('/')[-1], fh.read())
            buf = BytesIO()
            writer.write(buf)
            pdf_file = buf.getvalue()
            buf.close()
        except Exception:
            pass

    # Recipients: all superusers + ADMIN/MANAGER staff with emails
    recipients = []
    try:
        User = get_user_model()
        superuser_emails = {u.email for u in User.objects.filter(is_superuser=True, is_active=True) if u.email}
        staff_emails = {s.user.email for s in Staff.objects.filter(role__in=['ADMIN', 'MANAGER']) if s.user.email}
        recipients = list(superuser_emails.union(staff_emails))
    except Exception:
        pass
    if not recipients:
        fallback = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
        if fallback:
            recipients = [fallback]

    # Email body (HTML)
    logo_path = finders.find('images/Thermologo.jpg')
    inline_css = """
    <style>
      html, body { height: 100%; margin: 0; padding: 0; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; background-color: #f9f9f9; color: #333; line-height: 1.4; }
      .header { background-color: #017335; padding: 1rem 2rem; text-align: center; }
      .header h1 { color: #fff; font-size: 2rem; margin: 0; }
      .content { padding: 2rem; }
      .detail { margin-bottom: 1rem; }
      .detail strong { color: #017335; }
      .footer { background-color: #017335; color: #fff; text-align: center; padding: 1rem 0; margin-top: 2rem; }
    </style>
    """

    subject = f"Trip Completed: Trip #{trip.truck_trip_number or trip.pk}"
    margin = getattr(financial, 'net_profit_margin', None)
    margin_str = f"{margin:.1f}%" if margin is not None else 'N/A'
    html_body = f"""
    <html>
      <head>
        <meta charset=\"UTF-8\">{inline_css}
      </head>
      <body>
        <div class=\"header\">
          <img src=\"cid:logo\" alt=\"Thermo Fam Trading PLC\" style=\"max-width: 150px; border: 2px solid #fff; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.3); margin-bottom: 10px;\">
          <h1>Thermofam Trading PLC</h1>
        </div>
        <div class=\"content\">
          <p>Dear Admin/Manager,</p>
          <p>We are pleased to inform you that <strong>Trip #{trip.truck_trip_number or trip.pk}</strong> has been successfully completed.</p>
          <div class=\"detail\">
            <p><strong>Truck:</strong> {trip.truck.plate_number}</p>
            <p><strong>Driver:</strong> {trip.driver.staff_profile.user.username if trip.driver else 'N/A'}</p>
            <p><strong>Route:</strong> {trip.start_location} → {trip.end_location}</p>
          </div>
          <div class=\"detail\">
            <p><strong>Total Revenue:</strong> {getattr(financial, 'total_revenue', '')} ETB</p>
            <p><strong>Total Expense:</strong> {getattr(financial, 'total_expense', '')} ETB</p>
            <p><strong>Profit Before Tax:</strong> {getattr(financial, 'income_before_tax', '')} ETB</p>
            <p><strong>Net Profit Margin:</strong> {margin_str}</p>
            <p><strong>Payable/Receivable:</strong> {getattr(financial, 'payable_receivable_amount', '')} ETB</p>
          </div>
          <p>For full details, please see the attached PDF.</p>
          <p>Regards,<br>Your Fleet Management System</p>
        </div>
        <div class=\"footer\">
          <p>&copy; {timezone.now().year} Fleet Management System</p>
        </div>
      </body>
    </html>
    """

    email = EmailMultiAlternatives(
        subject=subject,
        body="Please view the HTML version of this email.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    email.attach_alternative(html_body, "text/html")
    email.attach(f"trip_{trip.pk}.pdf", pdf_file, "application/pdf")

    if logo_path:
        with open(logo_path, "rb") as lf:
            logo = MIMEImage(lf.read())
            logo.add_header('Content-ID', '<logo>')
            logo.add_header('Content-Disposition', 'inline', filename='Thermologo.jpg')
            email.attach(logo)

    email.send()
