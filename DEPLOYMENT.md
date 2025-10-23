Thermo Fam ERP — VM + Cloudflare Tunnel Deployment

Overview
- Single Ubuntu VM (on Hyper‑V or bare metal) runs the Django app via Gunicorn and systemd.
- Local MariaDB/MySQL on the same VM.
- Cloudflare Tunnel exposes the app publicly without opening inbound firewall ports.

Prerequisites
- Ubuntu 20.04+ with Python 3.10+ and `venv`.
- MariaDB/MySQL server installed locally.
- Cloudflare account with your domain active on Cloudflare.

1) App Setup (on the VM)
- Create a directory and virtualenv:
  - `sudo apt update && sudo apt install -y python3-venv python3-dev build-essential`
  - `mkdir -p /opt/thermofam && cd /opt/thermofam`
  - `python3 -m venv venv && source venv/bin/activate`
  - Place project files in `/opt/thermofam` (e.g., via git or rsync)
  - `pip install --upgrade pip && pip install -r requirements.txt`
- Django initialization:
  - `python manage.py migrate`
  - `python manage.py collectstatic --noinput`

2) Database (local MariaDB/MySQL)
- Create DB and user (aligned with repo defaults):
  - `sudo mysql -u root`
  - `CREATE DATABASE fleet CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;`
  - `CREATE USER IF NOT EXISTS 'admin'@'localhost' IDENTIFIED WITH mysql_native_password BY 'Admin_thermo';`
  - `CREATE USER IF NOT EXISTS 'admin'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY 'Admin_thermo';`
  - `GRANT ALL PRIVILEGES ON fleet.* TO 'admin'@'localhost';`
  - `GRANT ALL PRIVILEGES ON fleet.* TO 'admin'@'127.0.0.1';`
  - `FLUSH PRIVILEGES;`
- Configure environment (next section) to point Django to this DB.

3) Systemd Service (Gunicorn)
- Create `/etc/systemd/system/thermofam.service`:
  
  [Unit]
  Description=Thermo Fam ERP (Gunicorn)
  After=network.target

  [Service]
  User=www-data
  Group=www-data
  WorkingDirectory=/opt/thermofam
  Environment=DJANGO_SETTINGS_MODULE=transport_mgmt.settings
  Environment=DJANGO_ALLOWED_HOSTS=your.domain.com,127.0.0.1,localhost
  Environment=CSRF_TRUSTED_ORIGINS=https://your.domain.com
  Environment=DB_NAME=fleet
  Environment=DB_USER=admin
  Environment=DB_PASSWORD=Admin_thermo
  Environment=DB_HOST=127.0.0.1
  Environment=DB_PORT=3306
  ExecStart=/opt/thermofam/venv/bin/gunicorn -b 127.0.0.1:8000 transport_mgmt.wsgi:application
  Restart=always
  RestartSec=3

  [Install]
  WantedBy=multi-user.target

- Enable and start:
  - `sudo systemctl daemon-reload`
  - `sudo systemctl enable --now thermofam.service`
  - Check: `sudo systemctl status thermofam.service` and `journalctl -u thermofam -f`

4) Cloudflare Tunnel
- Install cloudflared:
  - `curl -fsSL https://pkg.cloudflare.com/install.sh | sudo bash`
  - `sudo apt-get install -y cloudflared`
- Authenticate & create a tunnel:
  - `cloudflared tunnel login` (opens browser to authorize)
  - `cloudflared tunnel create thermofam`
- Configure ingress at `/etc/cloudflared/config.yml`:
  
  tunnel: <TUNNEL_ID>
  credentials-file: /etc/cloudflared/<TUNNEL_ID>.json
  ingress:
    - hostname: your.domain.com
      service: http://127.0.0.1:8000
    - service: http_status:404

- Route DNS (one-time):
  - `cloudflared tunnel route dns thermofam your.domain.com`
- Run as a service:
  - `sudo systemctl enable --now cloudflared`
  - Check: `sudo systemctl status cloudflared` and `journalctl -u cloudflared -f`

5) Security & Settings
- Configure `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` to include your Cloudflare hostname.
- UFW (optional): allow SSH, deny inbound HTTP; Gunicorn listens on 127.0.0.1 only.
- Backups: set up DB dumps via cron and file snapshots as needed.

Notes
- Docker and AWS are removed from this project. Static files are served via WhiteNoise, media via local filesystem.
- Database defaults to local MySQL/MariaDB; no RDS SSL bundle is used.

Media files in production (DEBUG=False)
- By default, Django does not serve `/media/` when `DEBUG=False`.
- For this deployment (no Nginx), the URL config includes a fallback that serves `/media/` directly from Django when `DEBUG=False`.
- For better performance at scale, prefer one of:
  - Nginx/Apache to serve `/media/` from the filesystem; or
  - Object storage (e.g., S3/Cloudflare R2) and point uploads there.

Ensure uploads directory exists and is writable by Gunicorn user:
```
sudo mkdir -p /opt/thermofam/media
sudo chown -R www-data:www-data /opt/thermofam/media
sudo chmod -R u+rwX,g+rwX /opt/thermofam/media
```

Sync existing media from your dev/source to the server:
```
rsync -avz media/ user@server:/opt/thermofam/media/
```
