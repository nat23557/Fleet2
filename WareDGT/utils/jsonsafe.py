from decimal import Decimal
from uuid import UUID
from datetime import date, datetime, time
from django.db.models import Model, QuerySet
from django.core.files.uploadedfile import UploadedFile


def json_safe(obj):
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
        pk = getattr(obj, "pk", None)
        return json_safe(pk)
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
