# myapp/management/commands/reset_db.py
import os
import MySQLdb
from django.conf import settings
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Drop and recreate the default MySQL database"

    def handle(self, *args, **options):
        cfg = settings.DATABASES['default']
        name = cfg['NAME']
        # Use TCP loopback by default to avoid socket auth differences
        host = cfg.get('HOST', '127.0.0.1')
        port = int(cfg.get('PORT', 3306))
        # Prefer admin credentials via env if present, else app user
        admin_user = os.getenv('DB_ADMIN_USER')
        admin_pass = os.getenv('DB_ADMIN_PASSWORD')
        if admin_user:
            user = admin_user
            passwd = admin_pass or ''
        else:
            user = cfg['USER']
            passwd = cfg['PASSWORD']

        self.stdout.write(f"Dropping database `{name}` if it exists…")
        conn = MySQLdb.connect(host=host, port=port, user=user, passwd=passwd)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{name}`;")
        self.stdout.write(f"Recreating database `{name}`…")
        cursor.execute(
            f"CREATE DATABASE `{name}` "
            "CHARACTER SET utf8mb4 "
            "COLLATE utf8mb4_unicode_ci;"
        )
        cursor.close()
        conn.close()
        self.stdout.write(self.style.SUCCESS(f"Database `{name}` has been reset."))
