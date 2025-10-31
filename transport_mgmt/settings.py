import os
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Read secret from env in production; fall back to the existing
# development key so local setup continues to work.
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-(0ic)q_*o-j8!=utd@1vx7ui#-h+88xifh)vo+elwcb^e^ac76'
)
# Also honor DJANGO_SECRET_KEY if provided (e.g., Render)
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', SECRET_KEY)

DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')

_hosts_env = os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost')
ALLOWED_HOSTS = [h.strip() for h in _hosts_env.split(',') if h.strip()]
# Allow any ngrok-free.app subdomain for previews (use leading dot per Django docs)
if '.ngrok-free.app' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('.ngrok-free.app')

INSTALLED_APPS = [
    'crispy_forms',
    'transportation',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Ensure WhiteNoise is present (avoid duplicates)
if 'whitenoise.middleware.WhiteNoiseMiddleware' not in MIDDLEWARE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'transport_mgmt.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Global header state (e.g., driver_can_start_trip)
                'transportation.context_processors.header',
            ],
        },
    },
]

WSGI_APPLICATION = 'transport_mgmt.wsgi.application'

# Database configuration
# Default: MySQL via env vars. For smoke tests on EB without a DB,
# set USE_SQLITE=1 to boot with a local SQLite database.
if os.environ.get('USE_SQLITE', '0') in ('1', 'true', 'True', 'YES', 'yes'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.environ.get('DB_NAME', 'fleet'),
            'USER': os.environ.get('DB_USER', 'admin'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'Admin_thermo'),
            'HOST': os.environ.get('DB_HOST', '127.0.0.1'),
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }

# If explicit Postgres env vars are provided (e.g., Render), prefer them
if any(k in os.environ for k in ['POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_HOST', 'POSTGRES_PORT']):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'render'),
            'USER': os.environ.get('POSTGRES_USER', 'render'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', 'localhost'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
        }
    }

# Optional: allow DATABASE_URL override (e.g., Render Postgres)
try:
    import dj_database_url  # type: ignore
    _db_url = os.environ.get('DATABASE_URL')
    if _db_url:
        _ssl_req = os.environ.get('DB_SSL_REQUIRE', '1').lower() in ('1', 'true', 'yes')
        DATABASES['default'] = dj_database_url.parse(_db_url, conn_max_age=600, ssl_require=_ssl_req)
except Exception:
    pass

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
# … everything above unchanged …

# Static files storage
# Use manifest-based storage only in production so missing entries
# don’t crash development while editing static assets.
if DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'
    # Let Whitenoise auto-refresh and use finders in dev so collectstatic
    # isn’t required every time a static file changes.
    WHITENOISE_AUTOREFRESH = True
    WHITENOISE_USE_FINDERS = True
else:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Local static/media configuration
STATIC_URL = '/static/'
MEDIA_URL = '/media/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'transportation', 'static'),
]

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# … the rest of your settings …


# Crispy Forms config
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'

_csrf_env = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf_env.split(',') if o.strip()] if _csrf_env else []
# Wildcard for all ngrok-free.app subdomains (Django 4.2 supports this)
if 'https://*.ngrok-free.app' not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append('https://*.ngrok-free.app')

# Trust proxy HTTPS header so Django sees requests as secure behind ngrok
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO'},
        'django.request': {'handlers': ['console'], 'level': 'WARNING', 'propagate': True},
    },
}

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_HOST_USER = 'no.reply.thermofam@gmail.com'
EMAIL_HOST_PASSWORD = 'qxphstuffakvmyme'
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
