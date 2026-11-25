from django.conf import settings
from django.http import Http404, HttpResponse
from django.views.decorators.http import require_safe

# The app holds a refresh token in the browser, so only let the page run our own
# scripts and talk to our own server. This limits what an injected script could do.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


@require_safe
def frontend_app(request, path=None):
    index_file = settings.FRONTEND_BUILD_DIR / "index.html"
    if not index_file.exists():
        raise Http404("The web app has not been built.")

    response = HttpResponse(index_file.read_text(encoding="utf-8"), content_type="text/html")
    response["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    # Always fetch this page again so a new deploy's files are picked up.
    response["Cache-Control"] = "no-cache"
    return response
