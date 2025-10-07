# transport_mgmt/celery.py
from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'transport_mgmt.settings')

app = Celery('transport_mgmt')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'update-gps-records-every-60-seconds': {
        'task': 'transportation.tasks.update_gps_records',  # Use the new task path
        'schedule': 60.0,  # Adjust the interval as needed
    },
}
