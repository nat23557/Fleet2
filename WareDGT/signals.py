from django.contrib.auth.models import User
from django.contrib.auth.signals import (
    user_logged_in,
    user_login_failed,
    user_logged_out,
)
from django.db.models.signals import post_save, pre_save, m2m_changed, post_delete
from django.dispatch import receiver
from django.utils import timezone

from .models import (
    UserProfile,
    EcxLoad,
    EcxTrade,
    AuthEvent,
    UserEvent,
    DailyRecord,
    BinCardEntry,
    QualityCheck,
)


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Ensure each user has an associated profile."""
    if created and not hasattr(instance, "profile"):
        role = UserProfile.ADMIN if instance.is_superuser else UserProfile.WAREHOUSE_OFFICER
        UserProfile.objects.create(user=instance, role=role)


@receiver(pre_save, sender=User)
def capture_user_state(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = User.objects.get(pk=instance.pk)
            instance._old_is_active = old.is_active
            instance._old_role = (
                old.profile.role if hasattr(old, "profile") else None
            )
        except User.DoesNotExist:
            pass


@receiver(post_save, sender=User)
def log_user_event(sender, instance, created, **kwargs):
    if created:
        UserEvent.objects.create(subject=instance, event="CREATE")
    else:
        old_active = getattr(instance, "_old_is_active", instance.is_active)
        old_role = getattr(instance, "_old_role", None)
        if old_active != instance.is_active:
            UserEvent.objects.create(
                subject=instance,
                event="ACTIVATE" if instance.is_active else "DEACTIVATE",
            )
        elif old_role and instance.profile.role != old_role:
            UserEvent.objects.create(
                subject=instance,
                event="ROLE_CHANGE",
                meta={"from": old_role, "to": instance.profile.role},
            )


@receiver(user_logged_in)
def log_login(sender, user, request, **kwargs):
    AuthEvent.objects.create(username=user.username, event="LOGIN_OK")


@receiver(user_logged_out)
def log_logout(sender, user, request, **kwargs):
    if user and user.is_authenticated:
        AuthEvent.objects.create(username=user.username, event="LOGOUT")


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    AuthEvent.objects.create(
        username=credentials.get("username", ""),
        event="LOGIN_FAIL",
    )


@receiver(m2m_changed, sender=EcxLoad.trades.through)
def update_trade_loaded(sender, instance, action, pk_set, **kwargs):
    """Mark trades as loaded/unloaded when linked to a load."""
    if action == "post_add":
        EcxTrade.objects.filter(pk__in=pk_set).update(
            loaded=True,
            loaded_at=timezone.now(),
        )
    elif action == "post_remove":
        EcxTrade.objects.filter(pk__in=pk_set).update(
            loaded=False,
            loaded_at=None,
        )


@receiver(pre_save, sender=DailyRecord)
def _capture_prev_status(sender, instance, **kwargs):
    if instance.pk:
        prev = sender.objects.filter(pk=instance.pk).values(
            "status",
            "weight_in",
            "weight_out",
            "rejects",
            "cleaning_labor_rate_etb_per_qtl",
            "reject_weighing_rate_etb_per_qtl",
            "labor_rate_per_qtl",
            "reject_labor_payment_per_qtl",
        ).first() or {}
        instance._prev_status = prev.get("status")
        instance._prev_fields = prev
    else:
        instance._prev_status = None
        instance._prev_fields = {}


@receiver(post_save, sender=DailyRecord)
def _mark_pdf_dirty_on_cleaning(sender, instance, created, **kwargs):
    CLEAN_OPS = (DailyRecord.CLEANING, DailyRecord.RECLEANING)
    if instance.operation_type not in CLEAN_OPS:
        return
    entry = instance.lot
    if not entry:
        return
    became_posted = (
        instance.status == DailyRecord.STATUS_POSTED
        and (created or instance._prev_status != DailyRecord.STATUS_POSTED)
    )
    if became_posted:
        type(entry).objects.filter(pk=entry.pk).update(
            pdf_dirty=True, pdf_generated_at=None
        )
        return
    if instance.status != DailyRecord.STATUS_POSTED:
        return
    prev = getattr(instance, "_prev_fields", {})
    for f in [
        "weight_in",
        "weight_out",
        "rejects",
        "cleaning_labor_rate_etb_per_qtl",
        "reject_weighing_rate_etb_per_qtl",
        "labor_rate_per_qtl",
        "reject_labor_payment_per_qtl",
    ]:
        if prev.get(f) != getattr(instance, f):
            type(entry).objects.filter(pk=entry.pk).update(
                pdf_dirty=True, pdf_generated_at=None
            )
            break



@receiver(pre_save, sender=BinCardEntry)
def _snapshot_entry_files(sender, instance, **kwargs):
    if instance.pk:
        prev = sender.objects.filter(pk=instance.pk).values(
            "weighbridge_certificate",
            "warehouse_document",
            "quality_form",
        ).first() or {}
    else:
        prev = {}
    instance._prev_files = prev


@receiver(post_save, sender=BinCardEntry)
def _mark_pdf_dirty_on_entry_files(sender, instance, **kwargs):
    prev = getattr(instance, "_prev_files", {})
    changed = False
    for field in [
        "weighbridge_certificate",
        "warehouse_document",
        "quality_form",
    ]:
        old_name = prev.get(field) or ""
        new_name = getattr(instance, field).name if getattr(instance, field) else ""
        if old_name != new_name:
            changed = True
            break
    if changed:
        sender.objects.filter(pk=instance.pk).update(
            pdf_dirty=True, pdf_generated_at=None
        )


@receiver(pre_save, sender=BinCardEntry)
def _snapshot_unloading_rate(sender, instance, **kwargs):
    instance._prev_unload_rate = None
    if instance.pk:
        instance._prev_unload_rate = (
            sender.objects.filter(pk=instance.pk)
            .values_list("unloading_rate_etb_per_qtl", flat=True)
            .first()
        )


@receiver(post_save, sender=BinCardEntry)
def _dirty_on_unloading_rate_change(sender, instance, **kwargs):
    if getattr(instance, "_prev_unload_rate", None) != instance.unloading_rate_etb_per_qtl:
        type(instance).objects.filter(pk=instance.pk).update(
            pdf_dirty=True, pdf_generated_at=None
        )


@receiver(pre_save, sender=BinCardEntry)
def _snapshot_balance_fields(sender, instance, **kwargs):
    if instance.pk:
        prev = (
            sender.objects.filter(pk=instance.pk)
            .values(
                "weight",
                "balance",
                "cleaned_total_kg",
                "rejects_total_kg",
                "seed_type_id",
                "grade",
            )
            .first()
            or {}
        )
    else:
        prev = {}
    instance._prev_balance = prev


@receiver(post_save, sender=BinCardEntry)
def _dirty_on_balance_change(sender, instance, **kwargs):
    prev = getattr(instance, "_prev_balance", {})
    for f in [
        "weight",
        "balance",
        "cleaned_total_kg",
        "rejects_total_kg",
        "seed_type_id",
        "grade",
    ]:
        if prev.get(f) != getattr(instance, f):
            sender.objects.filter(pk=instance.pk).update(
                pdf_dirty=True, pdf_generated_at=None
            )
            break


@receiver([post_save, post_delete], sender=QualityCheck)
def _dirty_on_qc_change(sender, instance, **kwargs):
    record = instance.daily_record
    if (
        record
        and record.operation_type in (DailyRecord.CLEANING, DailyRecord.RECLEANING)
        and record.status == DailyRecord.STATUS_POSTED
        and record.lot_id
    ):
        BinCardEntry.objects.filter(pk=record.lot_id).update(
            pdf_dirty=True, pdf_generated_at=None
        )

