from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from .models import Transaction, BankAccount
from django.contrib.auth.models import Group


class TransactionForm(forms.ModelForm):
    attachment = forms.ImageField(required=False)

    class Meta:
        model = Transaction
        fields = [
            'account',
            'date',
            'description',
            'reference',
            'debit',
            'credit',
            'attachment',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={'placeholder': 'Describe the transaction'}),
            'reference': forms.TextInput(attrs={'placeholder': 'Reference / Document #'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        # Hide debit/credit default labels in UI if custom JS present; keep fields for validation
        self.fields['debit'].widget.attrs.setdefault('id', 'id_debit')
        self.fields['credit'].widget.attrs.setdefault('id', 'id_credit')
        from datetime import date as _date
        self.fields['attachment'].widget.attrs.update({'accept': 'image/*'})
        # Default date to today for better UX (works without JS)
        if not self.fields['date'].initial:
            self.fields['date'].initial = _date.today()

    def clean(self):
        cleaned = super().clean()
        debit = cleaned.get('debit') or 0
        credit = cleaned.get('credit') or 0
        date_val = cleaned.get('date')
        if (debit and credit) and (debit > 0 and credit > 0):
            raise forms.ValidationError('Only one of debit or credit can be greater than zero.')
        if (not debit or debit == 0) and (not credit or credit == 0):
            raise forms.ValidationError('Provide either a debit or a credit amount.')

        # Require an image attachment when the user is not superuser
        user_is_super = getattr(self.user, 'is_superuser', False)
        file = self.cleaned_data.get('attachment')
        if not user_is_super:
            if not file:
                raise forms.ValidationError('An image attachment is required for this transaction.')
            # Basic size limit (10 MB)
            try:
                if file.size > 10 * 1024 * 1024:
                    raise forms.ValidationError('Attachment must be under 10 MB.')
            except Exception:
                pass
        # Clerks may only post for today
        try:
            is_clerk = self.user and self.user.groups.filter(name='Clerk').exists()
        except Exception:
            is_clerk = False
        if is_clerk and date_val is not None:
            from datetime import date as _date
            if date_val != _date.today():
                raise forms.ValidationError('Clerk can only register transactions for today.')

        return cleaned


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['name', 'bank_name', 'currency', 'branch', 'purpose', 'account_number', 'threshold', 'large_txn_limit']


class BankRegistrationForm(forms.ModelForm):
    CURRENCY_CHOICES = (
        ("ETB", "ETB (Birr)"),
        ("USD", "USD (Dollar)"),
    )

    bank_name = forms.CharField(label="Bank Name", widget=forms.TextInput(attrs={
        "placeholder": "e.g. Commercial Bank of Ethiopia",
    }))
    currency = forms.ChoiceField(label="Type", choices=CURRENCY_CHOICES, widget=forms.RadioSelect)
    branch = forms.CharField(label="Branch", required=False, widget=forms.TextInput(attrs={
        "placeholder": "e.g. Piassa Branch",
    }))
    purpose = forms.CharField(label="Purpose", required=False, widget=forms.TextInput(attrs={
        "placeholder": "e.g. Payroll, Operations, ECX",
    }))
    account_number = forms.CharField(
        label="Account Number",
        help_text="Digits only — no spaces.",
        widget=forms.TextInput(attrs={
            "placeholder": "e.g. 1000123456789",
            "inputmode": "numeric",
            "pattern": "\\d*",
            "maxlength": "32",
            "autocomplete": "off",
        }),
        validators=[RegexValidator(r"^\\d{4,32}$", message="Provide 4-32 digits.")],
    )

    class Meta:
        model = BankAccount
        # Name is derived from bank name + branch for simplicity
        fields = ["bank_name", "currency", "branch", "purpose", "account_number"]

    def save(self, commit=True):
        obj: BankAccount = super().save(commit=False)
        # Derive a simple, friendly account name if not explicitly set
        bn = (self.cleaned_data.get("bank_name") or "").strip()
        br = (self.cleaned_data.get("branch") or "").strip()
        obj.name = f"{bn} ({br})" if br else bn
        obj.account_number = (self.cleaned_data.get("account_number") or "").strip()
        if commit:
            obj.save()
        return obj

    def clean_account_number(self):
        num = (self.cleaned_data.get("account_number") or "").strip()
        if not num.isdigit():
            raise ValidationError("Account number must be digits only.")
        if len(num) < 4 or len(num) > 32:
            raise ValidationError("Provide 4-32 digits.")
        return num
