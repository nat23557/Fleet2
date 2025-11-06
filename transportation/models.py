"""
Menu Order:
1. Staff Model           - Extends Django's User model with extra staff information.
2. Driver Model          - Contains driver-specific details and licenses; linked to Staff.
3. Truck Model           - Stores truck/vehicle details including status, mileage, and assignment.
4. MajorAccident Model   - Records accident details associated with trucks.
5. ServiceRecord Model   - Tracks maintenance and service records for trucks.
6. ReplacedItem Model    - Logs replaced parts and their details for trucks.
7. Cargo Model           - Stores details about cargo being transported.
8. Trip Model            - Records trips including route, odometer, and cargo info.
9. TripFinancial Model   - Summarizes financial data for each trip.
10. Expense Model        - Details individual expense items linked to a trip’s financial record.
11. Invoice Model        - Stores invoicing and billing details for trips.
12. OfficeUsage Model    - Tracks usage of office (non-cargo) vehicles.
"""

from django.db import models
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db.models import Sum, Max
from django.core.exceptions import ValidationError
from decimal import Decimal, ROUND_HALF_UP


# 1. Staff Model
class Staff(models.Model):
    """
    Extends Django's built-in User model to store extra info
    for administrative or managerial staff.
    A new user account is created when a Staff member is registered.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    ROLE_CHOICES = [
        ('ADMIN', 'Administrator'),
        ('MANAGER', 'Manager'),
        ('DRIVER', 'Driver'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='OTHER')
    phone = models.CharField(max_length=15, blank=True, null=True)

    # National ID upload (only images allowed)
    national_id = models.FileField(
        upload_to='national_ids/', 
        blank=False, 
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])]
    )

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


# 2. Driver Model
class Driver(models.Model):
    """
    Separate model for drivers (chauffeurs).
    Now includes:
    - Employment Date
    - Salary
    - Djibouti License (Image & Expiration Date)
    - Ethiopian License (Image & Expiration Date)
    """
    staff_profile = models.OneToOneField(
        Staff, 
        on_delete=models.CASCADE, 
        related_name='driver_profile'
    )
    license_number = models.CharField(max_length=50, unique=True)
    years_of_experience = models.PositiveIntegerField(default=0)
    
    # Employment Details
    employ_date = models.DateField(null=True, blank=True)
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Djibouti License
    djibouti_license_image = models.ImageField(upload_to='licenses/djibouti/', blank=True, null=True)
    djibouti_license_expiration = models.DateField(null=True, blank=True)

    # Ethiopian License
    ethiopian_license_image = models.ImageField(upload_to='licenses/ethiopia/', blank=True, null=True)
    ethiopian_license_expiration = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Driver: {self.staff_profile.user.username} - {self.license_number}"

class Truck(models.Model):
    plate_number = models.CharField(max_length=20, unique=True)
    truck_type = models.CharField(max_length=50, blank=True)
    capacity_in_tons = models.DecimalField(max_digits=6, decimal_places=2)
    
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('IN_USE', 'In Use'),
        ('MAINTENANCE', 'Maintenance'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    is_in_duty = models.BooleanField(default=False, help_text="Check if this truck is currently in use.")
    mileage_km = models.PositiveIntegerField(default=0, help_text="Total mileage in kilometers.")
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, null=True, blank=True)
    VEHICLE_TYPE_CHOICES = [
        ('CARGO', 'Cargo Truck'),
        ('OFFICE', 'Office Car'),
    ]
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES, default='CARGO')
    fuel_consumption_liters = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Total fuel used over time (optional for office cars)."
    )
    assigned_user = models.ForeignKey(
        'Staff', 
        null=True, 
        blank=True, 
        on_delete=models.SET_NULL,
        help_text="If it’s an office car, record which staff is currently using it."
    )

    def __str__(self):
        return f"{self.plate_number} - {self.truck_type} ({self.status})"
    
    def update_mileage(self, new_odometer):
        """
        Updates the truck's mileage if new_odometer is higher than the current mileage.
        new_odometer: a value (Decimal or string) representing the latest odometer reading.
        """
        try:
            new_value = Decimal(new_odometer)
            current_value = Decimal(self.mileage_km)
            if new_value > current_value:
                self.mileage_km = int(new_value)
                self.save(update_fields=['mileage_km'])
        except Exception as e:
            # Optionally log the error
            print("Error updating mileage:", e)

class GPSRecord(models.Model):
    """
    Model to store GPS data received from the API.
    Linked to Truck via its unique plate_number.
    """
    truck = models.ForeignKey(
        'Truck',
        to_field='plate_number',
        on_delete=models.CASCADE,
        help_text="Truck associated with this GPS record, linked via its unique plate number."
    )
    imei = models.CharField(max_length=50, help_text="Unique device identifier")
    name = models.CharField(max_length=100, help_text="Truck name or plate number as received from the API")
    group = models.CharField(max_length=100, null=True, blank=True)
    odometer = models.DecimalField(max_digits=15, decimal_places=3, help_text="Odometer reading")
    engine = models.CharField(max_length=10, help_text="Engine status (on/off)")
    status = models.CharField(max_length=100, help_text="Status string from the GPS device")
    dt_server = models.DateTimeField(help_text="Server timestamp when data was received")
    dt_tracker = models.DateTimeField(help_text="Timestamp when the tracker recorded the data")
    lat = models.DecimalField(max_digits=9, decimal_places=6, help_text="Latitude")
    lng = models.DecimalField(max_digits=9, decimal_places=6, help_text="Longitude")
    loc = models.TextField(null=True, blank=True, help_text="Human-readable location")
    nearset_zone = models.CharField(max_length=50, null=True, blank=True, help_text="Nearest zone information")
    altitude = models.DecimalField(max_digits=10, decimal_places=2, help_text="Altitude in meters")
    angle = models.IntegerField(help_text="Direction angle in degrees")
    speed = models.DecimalField(max_digits=6, decimal_places=2, help_text="Speed in km/h")
    fuel_1 = models.DecimalField(max_digits=6, decimal_places=2, help_text="Fuel level from sensor 1")
    fuel_2 = models.DecimalField(max_digits=6, decimal_places=2, help_text="Fuel level from sensor 2")
    fuel_can_level_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text="Fuel can level in percent")
    fuel_can_level_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Fuel can level value")
    params = models.JSONField(help_text="Additional sensor and diagnostic data from the GPS device")
    custom_fields = models.JSONField(null=True, blank=True, help_text="Custom fields sent from the GPS device")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Timestamp when this record was created")
    
    def __str__(self):
        return f"GPSRecord for {self.truck.plate_number} at {self.dt_tracker}"
    
    def save(self, *args, **kwargs):
        # Save the GPSRecord first
        super().save(*args, **kwargs)
        # Then update the truck's mileage using the new odometer reading
        self.truck.update_mileage(self.odometer)


class Geofence(models.Model):
    """Persist geofences so they appear across devices.

    geometry:
      - {"type":"circle","center":[lat,lng],"radius":m}
      - {"type":"rect","sw":[lat,lng],"ne":[lat,lng]}
      - {"type":"polygon","points":[[lat,lng],...]}
    """
    TYPE_CHOICES = (
        ("circle", "Circle"),
        ("rect", "Rectangle"),
        ("polygon", "Polygon"),
    )
    truck = models.ForeignKey('Truck', on_delete=models.CASCADE, related_name='geofences')
    name = models.CharField(max_length=128, blank=True)
    type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    geometry = models.JSONField()
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["truck", "active"]),
        ]

    def __str__(self):
        return f"Fence({self.type}) {self.name or ''} for {self.truck}"







# 4. MajorAccident Model
class MajorAccident(models.Model):
    truck = models.ForeignKey('Truck', on_delete=models.CASCADE, related_name='accidents')
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    location = models.CharField(max_length=255, blank=True, help_text="Accident location")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    severity = models.CharField(
        max_length=10,
        choices=[('MINOR', 'Minor'), ('MAJOR', 'Major'), ('TOTAL', 'Total Loss')],
        default='MINOR'
    )
    description = models.TextField(blank=True)
    accident_image = models.ImageField(upload_to='accidents/', null=True, blank=True)
    cost_of_damage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insurance_claim_number = models.CharField(max_length=100, null=True, blank=True)
    is_reported = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.truck.plate_number} accident on {self.date} ({self.severity})"


# 5. ServiceRecord Model
class ServiceRecord(models.Model):
    """
    Tracks services/maintenance for a single truck.
    """
    truck = models.ForeignKey(
        'Truck',
        on_delete=models.CASCADE,
        related_name='services',
        help_text="Truck that received this service."
    )
    date = models.DateField()
    service_type = models.CharField(max_length=255, help_text="e.g. Engine repair, Oil change")
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    service_image = models.ImageField(
        upload_to='service_docs/',
        null=True,
        blank=True,
        help_text="Receipt or photo from the service."
    )
    vendor = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the vendor or garage."
    )
    next_service_date = models.DateField(
        null=True, blank=True,
        help_text="Suggested next service date."
    )
    notes = models.TextField(
        blank=True,
        help_text="Additional notes about this service."
    )

    def __str__(self):
        return f"{self.truck.plate_number} service on {self.date} ({self.service_type})"


# 6. ReplacedItem Model
class ReplacedItem(models.Model):
    """
    Tracks replaced parts for a single truck.
    """
    truck = models.ForeignKey(
        'Truck',
        on_delete=models.CASCADE,
        related_name='replaced_items',
        help_text="Truck that had this item replaced."
    )
    part_name = models.CharField(max_length=255)
    date_replaced = models.DateField()
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    replacement_image = models.ImageField(
        upload_to='replacement_docs/',
        null=True,
        blank=True,
        help_text="Picture of replaced part or receipt."
    )
    part_serial_number = models.CharField(max_length=100, blank=True)
    warranty_expiration = models.DateField(null=True, blank=True, help_text="Expiration date of the part's warranty.")
    notes = models.TextField(blank=True, help_text="Any notes regarding this replacement.")

    def __str__(self):
        return f"{self.truck.plate_number} replaced {self.part_name} on {self.date_replaced}"


# 7. Cargo Model
class Cargo(models.Model):
    """
    Stores details about the cargo being transported.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    weight_in_kg = models.DecimalField(max_digits=10, decimal_places=2)
    fragile = models.BooleanField(default=False)  # e.g. for “Handle with care”
    origin = models.CharField(max_length=200)
    destination = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    is_in_duty = models.BooleanField(default=False, help_text="Check if cargo is currently being transported.")

    def __str__(self):
        return f"Cargo: {self.name} ({self.origin} -> {self.destination})"


# 8. Trip Model
class Trip(models.Model):
    truck = models.ForeignKey('Truck', on_delete=models.CASCADE)
    driver = models.ForeignKey('Driver', on_delete=models.SET_NULL, null=True, blank=True)
    start_location = models.CharField(max_length=200)
    start_latitude = models.FloatField(null=True, blank=True)
    start_longitude = models.FloatField(null=True, blank=True)
    end_location = models.CharField(max_length=200)
    end_latitude = models.FloatField(null=True, blank=True)
    end_longitude = models.FloatField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    initial_kilometer = models.PositiveIntegerField(null=True, blank=True)
    final_kilometer = models.PositiveIntegerField(null=True, blank=True)
    cargo_type = models.CharField(max_length=100, null=True, blank=True)
    cargo_load = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tariff_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    STATUS_IN_PROGRESS = 'IN_PROGRESS'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, 'In Progress'),
        (STATUS_COMPLETED, 'Completed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    is_in_duty = models.BooleanField(default=False)
    distance_traveled = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    trip_purpose = models.CharField(max_length=200, null=True, blank=True)
    route = models.JSONField(default=list, blank=True)
    # New: per-truck sequence number for trips
    truck_trip_number = models.PositiveIntegerField(null=True, blank=True, help_text="Per-truck trip sequence number")

    def calculated_distance(self):
        if self.initial_kilometer is not None and self.final_kilometer is not None:
            return self.final_kilometer - self.initial_kilometer
        return self.distance_traveled

    def clean(self):
        """ Prevent trip completion without an invoice """
        if self.status == self.STATUS_COMPLETED and not hasattr(self, 'invoice'):
            raise ValidationError("Trip cannot be completed without an invoice.")

    def save(self, *args, **kwargs):
        """ Override save method to enforce invoice check before completing a trip """
        if self.status == self.STATUS_COMPLETED and not hasattr(self, 'invoice'):
            raise ValidationError("Trip cannot be completed without an invoice.")
        # Assign per-truck trip number for new trips if missing
        if self.truck_id and not self.pk and not self.truck_trip_number:
            current_max = Trip.objects.filter(truck_id=self.truck_id).aggregate(m=Max('truck_trip_number'))['m'] or 0
            self.truck_trip_number = current_max + 1

        super().save(*args, **kwargs)
        if self.status == self.STATUS_COMPLETED and self.final_kilometer is not None:
            if self.initial_kilometer is not None and self.final_kilometer < self.initial_kilometer:
                return
            truck = self.truck
            if self.final_kilometer > truck.mileage_km:
                truck.mileage_km = self.final_kilometer
                truck.save(update_fields=['mileage_km'])

    def __str__(self):
        return f"Trip #{self.pk} | {self.truck.plate_number} - {self.get_status_display()}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['truck', 'truck_trip_number'], name='uniq_truck_trip_number_per_truck')
        ]


# 9. TripFinancial Model
class TripFinancial(models.Model):
    """
    Stores the high-level financial summary for a Trip,
    excluding odometer readings and cargo tariff (now tracked in Trip).
    """
    trip = models.OneToOneField('Trip', on_delete=models.CASCADE, related_name="financial")
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True,
                                          validators=[MinValueValidator(Decimal('0.00'))],
                                          help_text="Total revenue realized for the trip")
    total_expense = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True,
                                        validators=[MinValueValidator(Decimal('0.00'))],
                                        help_text="Sum of all operational and other expenses for the trip")
    operational_expense = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True,
                                                validators=[MinValueValidator(Decimal('0.00'))],
                                                help_text="Amount given to the driver as an operational expense budget")
    income_before_tax = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True,
                                              help_text="Calculated as (total_revenue - total_expense)")
    payable_receivable_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True,
                                                    help_text="Calculated as (operational_expense - total_expense). A positive value indicates money receivable from the driver; a negative value means extra money should be paid to the driver.")
    net_profit_margin = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True,
                                            help_text="Net profit margin as a percentage (one decimal), calculated as (income_before_tax / total_revenue) * 100.")

    def update_financials(self):
        """Recalculate financial figures based on trip data, driver expenses, and aggregated operational expense entries."""
        trip = self.trip
        if trip.cargo_load and trip.tariff_rate:
            total_revenue = trip.cargo_load * trip.tariff_rate
        else:
            total_revenue = Decimal('0.00')
        self.total_revenue = total_revenue

        # Aggregate driver-registered expenses from the Expense model.
        expense_aggregate = self.expenses.aggregate(total=Sum('amount'))
        total_expense = expense_aggregate['total'] or Decimal('0.00')
        self.total_expense = total_expense

        self.income_before_tax = total_revenue - total_expense

        # Aggregate operational expense entries (money given by the manager).
        op_expense_aggregate = self.expense_details.aggregate(total=Sum('amount'))
        total_operational_expense = op_expense_aggregate['total'] or Decimal('0.00')
        # Update the operational_expense field with the summed value.
        self.operational_expense = total_operational_expense

        # Calculate payable/receivable as the difference between the aggregated operational expense and driver expenses.
        self.payable_receivable_amount = self.operational_expense - total_expense

        if total_revenue != Decimal('0.00'):
            pct = (self.income_before_tax / total_revenue) * Decimal('100.0')
            self.net_profit_margin = pct.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        else:
            self.net_profit_margin = None

        self.save()





from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
class OperationalExpenseDetail(models.Model):
    financial = models.ForeignKey(
        'TripFinancial', 
        on_delete=models.CASCADE, 
        related_name='expense_details'
    )
    amount = models.DecimalField(
        max_digits=15, 
        decimal_places=2, 
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Expense amount given at this instance"
    )
    image = models.ImageField(
        upload_to='operational_expense_images/', 
        null=True, 
        blank=True,
        help_text="Upload a receipt or related image"
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    # NEW FIELD
    note = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        help_text="Optional description or comment about this expense."
    )

    def __str__(self):
        return f"Expense {self.pk}: {self.amount}"









# 10. Expense Model

class Expense(models.Model):
    """
    Represents an individual expense item linked to a Trip's financial record.
    This granular detail allows for a precise breakdown of costs.
    """
    EXPENSE_CATEGORIES = [
        ('ነዳጅ', 'ነዳጅ'),
        ('አጋዥ', 'አጋዥ'),
        ('መንገድ ፈንድ', 'መንገድ ፈንድ'),
        ('ፍተሻ', 'ፍተሻ'),
        ('ሰንሰለት', 'ሰንሰለት'),
        ('ሚዛን', 'ሚዛን'),
        ('መንገድ ትራንስፖርት', 'መንገድ ትራንስፖርት'),
        ('ጥገና', 'ጥገና'),
        ('ጎማ፣ ደብራተር እና ነፋስ', 'ጎማ፣ ደብራተር እና ነፋስ'),
        ('የሹፌር አበል', 'የሹፌር አበል'),
        ('ቻይና/ዶላሬ መግቢያ', 'ቻይና/ዶላሬ መግቢያ'),
        ('ደላላ', 'ደላላ'),
        ('የደረሰኝ ወጪ', 'የደረሰኝ ወጪ'),
        ('መኪና ጥበቃ እና ማሳደሪያ', 'መኪና ጥበቃ እና ማሳደሪያ'),
        ('የመኪና እጥበት', 'የመኪና እጥበት'),
        ('ሰርቪስ/ታፒሰሪ', 'ሰርቪስ/ታፒሰሪ'),
        ('ታፒሰሪ', 'ታፒሰሪ'),
        ('የመኪና ማሳደሪያ', 'የመኪና ማሳደሪያ'),
        ('ተሳቢ ማዘያ እና ማውረጃ', 'ተሳቢ ማዘያ እና ማውረጃ'),
        ('Other', 'Other'),


    ]
    
    trip_financial = models.ForeignKey(TripFinancial, on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=50, choices=EXPENSE_CATEGORIES, default='ነዳጅ')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    note = models.CharField(max_length=120, blank=True, null=True, help_text="Additional details for this expense")

    def __str__(self):
        return f"{self.get_category_display()} - {self.amount} for Trip #{self.trip_financial.trip.pk}"


# 11. Invoice Model

from django.utils import timezone

class Invoice(models.Model):
    trip = models.OneToOneField('Trip', on_delete=models.CASCADE, related_name="invoice")
    issue_date = models.DateField(null=True, blank=True)  # New field to track the issue date
    due_date = models.DateField(null=True, blank=True)
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    attached_image = models.ImageField(
        upload_to='invoices/',
        null=True,
        blank=True,
        help_text="Upload invoice image"
    )

    def save(self, *args, **kwargs):
        # If issue_date is not set, auto populate it with the current date.
        if not self.issue_date:
            self.issue_date = timezone.now().date()
        # If due_date not provided but trip already has an end_time, default to +10 days
        try:
            from datetime import timedelta as _td
            if not self.due_date and getattr(self, 'trip', None) and getattr(self.trip, 'end_time', None):
                self.due_date = (self.trip.end_time.date() + _td(days=10))
        except Exception:
            # Avoid blocking save due to date edge cases
            pass
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Invoice {self.invoice_number} | Trip #{self.trip.id}"




# 12. OfficeUsage Model
class OfficeUsage(models.Model):
    """
    Tracks usage of an office vehicle (non-cargo).
    For example, a staff member using a car for errands.
    """
    truck = models.ForeignKey(
        'Truck', 
        on_delete=models.CASCADE, 
        limit_choices_to={'vehicle_type': 'OFFICE'},
        help_text="Select the office car"
    )
    user = models.ForeignKey(
        'Staff',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Staff member who used the car (not necessarily a driver)."
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    start_odometer = models.PositiveIntegerField(null=True, blank=True)
    end_odometer = models.PositiveIntegerField(null=True, blank=True)
    fuel_consumed = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True, help_text="Liters of fuel consumed")
    purpose = models.CharField(max_length=255, blank=True, help_text="Reason for usage (e.g. errands, official visits).")
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"OfficeUsage #{self.pk} - {self.truck.plate_number}"

    @property
    def distance_traveled(self):
        if self.start_odometer is not None and self.end_odometer is not None:
            return self.end_odometer - self.start_odometer
        return 0
