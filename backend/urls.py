"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
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
"""
from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.conf import settings
from django.conf.urls.static import static

def home_view(request):
    return JsonResponse({
        'message': 'Online Exam API Server',
        'status': 'running',
        'endpoints': {
            'admin': '/admin/',
            'api': '/api/',
            'register': '/api/register/',
            'login': '/api/login/',
        }
    })

def health_view(request):
    return JsonResponse({
        'status': 'ok',
        'service': 'onlineexam-backend',
    })

urlpatterns = [
    path('', home_view, name='home'),
    path('health/', health_view, name='health'),
    path('admin/', admin.site.urls),
    path('api/', include('user.urls')), 
    path('api/exams/', include('exams.urls')),
    path('api/notifications/', include('notifications.urls')),
    path('api/audit/', include('audit.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
