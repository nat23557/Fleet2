from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class BankAccount(models.Model):
    name = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=100)
    currency = models.CharField(max_length=10, default='ETB')
    threshold = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    large_txn_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.bank_name})"


class Transaction(models.Model):
    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    date = models.DateField()
    description = models.TextField()
    reference = models.CharField(max_length=100, blank=True)
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    attachment = models.ImageField(upload_to='cash/attachments/', null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='transactions_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transactions_modified',
    )
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self) -> str:
        sign = '+' if self.credit else '-'
        amount = self.credit if self.credit else self.debit
        return f"{self.date} {sign}{amount} {self.account}"


class AuditLog(models.Model):
    action = models.CharField(max_length=50)
    model = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.model}#{self.object_id}"


class ExchangeRate(models.Model):
    """Daily exchange rate as published by Commercial Bank of Ethiopia.

    Stores "ETB per 1 unit of currency" (sell rate) for conversion to ETB.
    For ETB itself, use rate=1.0.
    """
    date = models.DateField(default=timezone.now)
    currency = models.CharField(max_length=10)  # e.g., USD, EUR
    rate = models.DecimalField(max_digits=16, decimal_places=6)  # ETB per 1 unit
    source = models.CharField(max_length=100, default='CBE')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("date", "currency")
        ordering = ["-date", "currency"]

    def __str__(self) -> str:
        return f"{self.date} {self.currency}={self.rate} ETB"
