"""
URL configuration for transport_mgmt project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
v   """
from django.contrib import admin
from django.urls import path, include
import os
from django.urls import re_path
import re
from django.views.static import serve as media_serve
# transport_mgmt/urls.py
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.urls import path

def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('admin/', admin.site.urls),
    # Make 'transportation.urls' handle the root URL:
    path('', include('transportation.urls')), 
    # Finance (cash management)
    path('cash/', include('cash_management.urls')),
    # WareDGT (Warehouse) UI and API mounted under a prefix to avoid clashes
    path('warehouse/', include('WareDGT.urls')),
    path('warehouse/api/', include('WareDGT.api_urls')),
    # Also expose WareDGT API at root /api/ to satisfy existing JS that calls absolute /api/...
    path('api/', include('WareDGT.api_urls')),
    path("healthz/", healthz),
]

from django.conf import settings
from django.conf.urls.static import static


# Serve media files even when DEBUG is False (for this deployment)
# In production behind a real web server (nginx), remove this and let nginx serve media.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    media_prefix = settings.MEDIA_URL.lstrip('/')
    urlpatterns += [
        re_path(r'^%s(?P<path>.*)$' % re.escape(media_prefix), media_serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
