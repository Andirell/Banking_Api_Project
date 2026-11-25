from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import ( SpectacularAPIView, SpectacularSwaggerView )
from django.http import JsonResponse


def health_check(request):
    # Render calls /health/ to check the API is running
    return JsonResponse({"status": "ok", "service": "banking-api"})


urlpatterns = [
    path("", health_check, name="home"),
    path("health/", health_check, name="health"),
    path("admin/", admin.site.urls),
    path("users/", include("users.urls")),
    path("transactions/", include("transactions.urls")),
    path("analytics/", include("analytics.urls")),
    path("loans/", include("loans.urls")),
    path("wallets/", include("wallets.urls")),
    re_path(r"^app(/.*)?$", frontend_app, name="frontend_app"),
]

# The API docs list every endpoint, so in production they are only shown
# when API_DOCS_PUBLIC is turned on. Locally (DEBUG) they are always on.
if settings.API_DOCS_PUBLIC:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema")),
    ]

# Note: there is no /media/ URL on purpose. KYC documents are private and
# can only be downloaded through /users/kyc/documents/.
