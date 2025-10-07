from typing import Dict

from django.contrib.auth.models import AnonymousUser

from .models import Staff, Driver, Trip


def header(request) -> Dict[str, bool]:
    """Context for global header controls.

    Exposes:
    - driver_can_start_trip: True only if the user is a DRIVER and has no active trip.
    """
    user = getattr(request, "user", None)
    if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
        return {"driver_can_start_trip": False}

    # Resolve role without importing view helpers to avoid circular imports
    if user.is_superuser:
        role = "ADMIN"
    else:
        staff = Staff.objects.filter(user=user).only("role").first()
        role = staff.role.strip().upper() if staff and staff.role else None

    if role != "DRIVER":
        return {"driver_can_start_trip": False}

    # For drivers, check if there is any active (in‑progress) trip
    driver_profile = None
    try:
        # Staff has related_name='driver_profile'
        staff = getattr(user, "staff", None)
        driver_profile = getattr(staff, "driver_profile", None) if staff else None
    except Exception:
        driver_profile = None

    if not driver_profile:
        # Without a driver profile, user cannot start trips from UI
        return {"driver_can_start_trip": False}

    has_active = Trip.objects.filter(driver=driver_profile, status=Trip.STATUS_IN_PROGRESS).exists()
    return {"driver_can_start_trip": not has_active}
