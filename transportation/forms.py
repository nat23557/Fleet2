from django import forms
from .models import Staff, Driver, Truck, Cargo, Trip
from django import forms
from django.contrib.auth.models import User
from .models import Staff
from django.contrib.auth.models import Group
from django.db.models import Q

from django import forms
from django.contrib.auth.models import User
from .models import Staff
from django.core.exceptions import ValidationError


class StaffForm(forms.ModelForm):
    """
    A form for creating and updating Staff records.
    Automatically creates a User account when a new Staff is added,
    and updates the existing User on update.
    """
    username = forms.CharField(
        max_length=150, 
        required=True, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter username'})
    )
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Enter email'})
    )

    password = forms.CharField(
        required=True,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter password'})
    )

    class Meta:
        model = Staff
        fields = ["username", "email", "password", "role", "phone", "national_id"]
        labels = {
            'role': 'Staff Role',
            'phone': 'Phone Number',
            'national_id': 'National ID Document (Only Images)',
        }
        widgets = {
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter phone number'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
        }
        help_texts = {
            'role': 'Administrator can manage everything, Manager has limited rights, etc.',
            'national_id': 'Upload a valid image file (JPG, PNG, GIF).',
        }

    def clean_national_id(self):
        national_id = self.cleaned_data.get("national_id")
        if national_id and hasattr(national_id, 'content_type'):
            valid_mime_types = ['image/jpeg', 'image/png', 'image/gif']
            file_type = national_id.content_type
            if file_type not in valid_mime_types:
                raise ValidationError("Invalid file format. Please upload an image file (JPG, PNG, GIF).")
        return national_id

    def save(self, commit=True):
        staff = super().save(commit=False)
        if self.instance.pk:
            # Update existing user
            user = self.instance.user
            user.username = self.cleaned_data['username']
            user.email = self.cleaned_data['email']
            password = self.cleaned_data.get('password')
            if password:
                user.set_password(password)
            if commit:
                user.save()
                staff.save()
                _sync_groups_for_role(user, staff.role)
        else:
            # Create new user and link to staff
            user = User.objects.create_user(
                username=self.cleaned_data['username'],
                email=self.cleaned_data['email'],
                password=self.cleaned_data['password']
            )
            staff.user = user
            if commit:
                staff.save()
                _sync_groups_for_role(user, staff.role)
        return staff


def _sync_groups_for_role(user: User, role: str) -> None:
    """Ensure Django auth Group membership matches Staff.role for finance permissions.

    - If role == 'CLERK': add user to 'Clerk' group (create if missing)
    - If role == 'ADMIN'/'MANAGER' remove from 'Clerk' (they may have broader rights anyway)
    """
    try:
        clerk_group, _ = Group.objects.get_or_create(name='Clerk')
        if (role or '').upper() == 'CLERK':
            user.groups.add(clerk_group)
        else:
            user.groups.remove(clerk_group)
    except Exception:
        # Non-fatal; group will be ensured by cash_management signals on migrate
        pass

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordChangeForm

class UpdateUserForm(forms.ModelForm):
    """
    A form to allow users to update their profile information.
    """
    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

class ChangePasswordForm(PasswordChangeForm):
    """
    A form to allow users to securely change their password.
    """
    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Current Password'}),
        label="Old Password"
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'New Password'}),
        label="New Password"
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm New Password'}),
        label="Confirm New Password"
    )








class DriverForm(forms.ModelForm):
    """
    A form for the Driver model with:
    - Employment Date
    - Salary
    - Djibouti License Image & Expiration
    - Ethiopian License Image & Expiration
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show staff with role DRIVER who do NOT already
        # have an associated Driver profile. When editing an
        # existing driver, also include the currently selected
        # staff in the queryset so the form remains valid.
        base_qs = Staff.objects.filter(role='DRIVER')
        if getattr(self.instance, 'pk', None):
            current_staff_id = self.instance.staff_profile_id
            qs = base_qs.filter(Q(driver_profile__isnull=True) | Q(pk=current_staff_id))
        else:
            qs = base_qs.filter(driver_profile__isnull=True)
        self.fields['staff_profile'].queryset = qs.order_by('user__username')

    class Meta:
        model = Driver
        fields = [
            "staff_profile", "license_number", "years_of_experience",
            "employ_date", "salary",
            "djibouti_license_image", "djibouti_license_expiration",
            "ethiopian_license_image", "ethiopian_license_expiration"
        ]
        labels = {
            "staff_profile": "Linked Staff Member",
            "license_number": "License Number",
            "years_of_experience": "Experience (Years)",
            "employ_date": "Employment Date",
            "salary": "Salary (ETB)",
            "djibouti_license_image": "Djibouti License",
            "djibouti_license_expiration": "Djibouti License Expiration",
            "ethiopian_license_image": "Ethiopian License",
            "ethiopian_license_expiration": "Ethiopian License Expiration",
        }
        widgets = {
            "employ_date": forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            "salary": forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            "djibouti_license_expiration": forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            "ethiopian_license_expiration": forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def clean_salary(self):
        salary = self.cleaned_data.get("salary")
        if salary and salary < 0:
            raise forms.ValidationError("Salary must be a positive value.")
        return salary





# forms.py
from django import forms
from .models import MajorAccident, ServiceRecord, ReplacedItem, Truck
from django import forms
from .models import MajorAccident

class MajorAccidentForm(forms.ModelForm):
    latitude = forms.CharField(widget=forms.HiddenInput(), required=False)
    longitude = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = MajorAccident
        fields = [
            'driver', 'date', 'location', 'latitude', 'longitude', 'severity',
            'description', 'accident_image', 'cost_of_damage',
            'insurance_claim_number', 'is_reported'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Select location on map'}),
        }

class ServiceRecordForm(forms.ModelForm):
    class Meta:
        model = ServiceRecord
        fields = [
             'date', 'service_type', 'cost',
            'service_image', 'vendor', 'next_service_date', 'notes'
        ]
        widgets = {
        'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        'next_service_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }



class ReplacedItemForm(forms.ModelForm):
    class Meta:
        model = ReplacedItem
        fields = [
            'part_name', 'date_replaced', 'cost',
            'replacement_image', 'part_serial_number', 'warranty_expiration',
            'notes'
        ]
        widgets = {
            'date_replaced': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'warranty_expiration': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

class TruckForm(forms.ModelForm):
    class Meta:
        model = Truck
        fields = [
            'plate_number', 'truck_type', 'capacity_in_tons', 'driver', 'vehicle_type'
        ]
        widgets = {
            'plate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'truck_type': forms.TextInput(attrs={'class': 'form-control'}),
            'capacity_in_tons': forms.NumberInput(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'driver': forms.Select(attrs={'class': 'form-select'}),
            'vehicle_type': forms.Select(attrs={'class': 'form-select'}),

        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import Driver
        # Filter the driver field to include only drivers not assigned to any truck.
        self.fields['driver'].queryset = Driver.objects.filter(truck__isnull=True)






class CargoForm(forms.ModelForm):
    """
    A form for Cargo with placeholders, validation checks,
    and a boolean field for is_in_duty.
    """
    class Meta:
        model = Cargo
        fields = [
            "name", "description", "weight_in_kg", 
            "fragile", "origin", "destination", "is_in_duty"
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'e.g. Electronics',
            }),
            'description': forms.Textarea(attrs={'rows': 3}),
            'weight_in_kg': forms.NumberInput(attrs={'min': 0}),
            'origin': forms.TextInput(attrs={}),
            'destination': forms.TextInput(attrs={}),
        }
        labels = {
            'weight_in_kg': 'Weight (kg)',
            'is_in_duty': 'Is Cargo in Duty?',
        }
        help_texts = {
            'fragile': 'Check if cargo is easily breakable or needs special handling.',
            'is_in_duty': 'Check if cargo is currently being transported.',
        }



# forms.py
from django import forms
from .models import Trip, TripFinancial, Expense, Invoice
from django import forms
from .models import Trip


class DriverTripCreateForm(forms.ModelForm):
    class Meta:
        model = Trip
        fields = ['cargo_type', 'cargo_load', 'tariff_rate']  # ONLY these fields
        widgets = {
            'cargo_load': forms.NumberInput(attrs={'placeholder': 'Enter cargo load'}),
            'tariff_rate': forms.NumberInput(attrs={'placeholder': 'Enter tariff rate per unit'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields optional so driver can start trip without them
        self.fields['cargo_load'].required = False
        self.fields['tariff_rate'].required = False
        # Optional: improve labels
        self.fields['cargo_load'].label = self.fields['cargo_load'].label or 'Cargo Load'
        self.fields['tariff_rate'].label = self.fields['tariff_rate'].label or 'Tariff Rate'
        # No hard validation here; driver can fill later via update




from django import forms
from .models import TripFinancial

class TripFinancialForm(forms.ModelForm):
    class Meta:
        model = TripFinancial
        fields = [
            
            "operational_expense",
           
        ]
from django import forms
from .models import OperationalExpenseDetail

class OperationalExpenseDetailForm(forms.ModelForm):
    class Meta:
        model = OperationalExpenseDetail
        fields = ['amount', 'image']
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Enter expense amount'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
        }
    
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'content_type'):
            valid_mime_types = ['image/jpeg', 'image/png', 'image/gif']
            file_type = image.content_type
            if file_type not in valid_mime_types:
                raise forms.ValidationError("Invalid file format. Please upload an image file (JPG, PNG, GIF).")
        return image



class ExpenseForm(forms.ModelForm):
    # Custom message to explain the condition
    condition_message = "Note: If you select 'Other' as the expense category, you must provide an explanation in the note field."

    class Meta:
        model = Expense
        fields = [
            "category",
            "amount",
            "note",
        ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Attach the condition message as help text for the note field
        self.fields["note"].help_text = self.condition_message

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        note = cleaned_data.get("note")
        
        if category == "Other" and not note:
            self.add_error("note", "Please provide an explanation when 'Other' is selected.")
        return cleaned_data



class InvoiceForm(forms.ModelForm):
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Optional. If left blank, it will default to 10 days after trip completion."
    )

    class Meta:
        model = Invoice
        fields = ["attached_image", "due_date"]

from django import forms
from .models import OfficeUsage

class OfficeUsageForm(forms.ModelForm):
    class Meta:
        model = OfficeUsage
        # Remove 'truck' and 'user' so they are set automatically
        fields = [
            'start_time',
            'end_time',
            'start_odometer',
            'end_odometer',
            'fuel_consumed',
            'purpose',
            'notes',
        ]
        widgets = {
            'start_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
            'end_time': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_odometer = cleaned_data.get("start_odometer")
        end_odometer = cleaned_data.get("end_odometer")
        if end_odometer is not None and start_odometer is not None:
            if end_odometer < start_odometer:
                self.add_error("end_odometer", "End odometer cannot be less than start odometer.")
        return cleaned_data
# forms.py
from django import forms

class CompletedTripsFilterForm(forms.Form):
    TIMEFRAME_CHOICES = [
        ('1_month', 'Last 1 Month'),
        ('3_months', 'Last 3 Months'),
        ('1_year', 'Last 1 Year'),
        ('2_years', 'Last 2 Years'),
        ('custom', 'Custom Range'),
    ]
    timeframe = forms.ChoiceField(
        choices=TIMEFRAME_CHOICES, 
        required=True, 
        label="Timeframe"
    )
    # New: how many latest trips per truck to show in the matrix
    TRIP_COUNT_CHOICES = [
        (3, '3 trips'),
        (5, '5 trips'),
        (6, '6 trips'),
        (10, '10 trips'),
        (15, '15 trips'),
        (20, '20 trips'),
    ]
    per_truck = forms.ChoiceField(
        choices=TRIP_COUNT_CHOICES,
        required=False,
        label="Trips per truck",
        initial=6,
        help_text="How many latest trips to include for each truck"
    )
    start_date = forms.DateField(
        required=False, 
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Start Date"
    )
    end_date = forms.DateField(
        required=False, 
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="End Date"
    )

    def clean(self):
        cleaned_data = super().clean()
        timeframe = cleaned_data.get('timeframe')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        # If custom range is selected, both dates must be provided and valid.
        if timeframe == 'custom':
            if not start_date or not end_date:
                raise forms.ValidationError("Please provide both start and end dates for a custom range.")
            if start_date > end_date:
                raise forms.ValidationError("Start date cannot be after the end date.")
        # normalize per_truck to int if provided
        per = cleaned_data.get('per_truck')
        if per:
            try:
                cleaned_data['per_truck'] = int(per)
            except (TypeError, ValueError):
                cleaned_data['per_truck'] = 6
        return cleaned_data
