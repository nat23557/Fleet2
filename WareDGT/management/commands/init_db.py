import os
import MySQLdb
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create the MySQL database and grant the app user. Uses DB_ADMIN_* envs."

    def handle(self, *args, **options):
        cfg = settings.DATABASES['default']
        name = cfg['NAME']
        host = cfg.get('HOST', '127.0.0.1')
        port = int(cfg.get('PORT', 3306))
        app_user = cfg['USER']
        app_pass = cfg['PASSWORD']

        # Admin credentials from env
        admin_user = os.getenv('DB_ADMIN_USER')
        admin_pass = os.getenv('DB_ADMIN_PASSWORD') or os.getenv('MARIADB_ROOT_PASSWORD') or ''

        if not admin_user:
            raise CommandError(
                "Admin credentials not provided. Set DB_ADMIN_USER and DB_ADMIN_PASSWORD (or MARIADB_ROOT_PASSWORD)."
            )

        self.stdout.write(
            f"Connecting to MySQL as admin '{admin_user}' on {host}:{port} to create DB '{name}'…"
        )
        conn = MySQLdb.connect(host=host, port=port, user=admin_user, passwd=admin_pass)
        cursor = conn.cursor()

        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )

        # Ensure app user exists for both TCP and socket connections
        for h in ('127.0.0.1', 'localhost'):
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{app_user}'@'{h}' IDENTIFIED BY %s;",
                (app_pass,),
            )
            cursor.execute(
                f"GRANT ALL PRIVILEGES ON `{name}`.* TO '{app_user}'@'{h}';"
            )

        cursor.execute("FLUSH PRIVILEGES;")
        cursor.close()
        conn.close()
        self.stdout.write(self.style.SUCCESS(f"Database '{name}' ready and privileges granted to '{app_user}'."))

