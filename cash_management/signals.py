from __future__ import annotations

from django.db.models.signals import post_save
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import Group, Permission
from django.dispatch import receiver

from .models import Transaction, AuditLog


@receiver(post_save, sender=Transaction)
def log_transaction_create_or_update(sender, instance: Transaction, created: bool, **kwargs):
    try:
        action = 'created' if created else 'updated'
        note = instance.description or ''
        AuditLog.objects.create(
            action=action,
            model='Transaction',
            object_id=str(instance.pk),
            user=instance.created_by if created else instance.modified_by,
            note=note,
        )
    except Exception:
        # Do not block business flow on audit errors
        pass


@receiver(post_migrate)
def ensure_groups(sender, **kwargs):
    try:
        clerk, _ = Group.objects.get_or_create(name='Clerk')
        owner, _ = Group.objects.get_or_create(name='Owner')

        def get_perm(code, app_label, model):
            try:
                return Permission.objects.get_by_natural_key(code, app_label, model)
            except Permission.DoesNotExist:
                return None

        clerk_perms = [
            get_perm('view_bankaccount', 'cash_management', 'bankaccount'),
            get_perm('view_transaction', 'cash_management', 'transaction'),
            get_perm('add_transaction', 'cash_management', 'transaction'),
        ]
        for p in clerk_perms:
            if p and p not in clerk.permissions.all():
                clerk.permissions.add(p)

        owner_perms = [
            get_perm('view_bankaccount', 'cash_management', 'bankaccount'),
            get_perm('add_bankaccount', 'cash_management', 'bankaccount'),
            get_perm('change_bankaccount', 'cash_management', 'bankaccount'),
            get_perm('view_transaction', 'cash_management', 'transaction'),
        ]
        for p in owner_perms:
            if p and p not in owner.permissions.all():
                owner.permissions.add(p)
    except Exception:
        # Non-fatal if permissions aren't ready yet
        pass
