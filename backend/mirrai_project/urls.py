from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from django.http import JsonResponse

def root_check(request):
    return JsonResponse({"status": "django_running", "framework": "Django"})

try:
    from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
    HAS_SPECTACULAR = True
except ImportError:
    HAS_SPECTACULAR = False

urlpatterns = [
    path('', root_check),
    path('admin/', admin.site.urls),
    path('api/v1/', include('app.api.v1.urls_django')),
]

if HAS_SPECTACULAR:
    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
        path('docs/', SpectacularSwaggerView.as_view(url_name='schema')),
    ]
else:
    # Optional diagnostic path
    def swagger_error(request):
        return JsonResponse({
            "error": "drf-spectacular is not installed.",
            "message": "Please run 'pip install drf-spectacular' or re-run 'fix_all.bat'."
        }, status=500)
    urlpatterns += [path('docs/', swagger_error)]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
