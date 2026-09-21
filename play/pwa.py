"""Serve root-scoped PWA resources without caching any account content."""
from django.conf import settings
from django.http import FileResponse
from django.views.decorators.http import require_GET


def asset(name, content_type):
    response = FileResponse((settings.BASE_DIR / 'play/static/pwa' / name).open('rb'), content_type=content_type)
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def service_worker(request):
    response = asset('service-worker.js', 'application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


@require_GET
def manifest(request):
    return asset('manifest.webmanifest', 'application/manifest+json')


@require_GET
def favicon(request):
    return asset('favicon-v1.ico', 'image/x-icon')
