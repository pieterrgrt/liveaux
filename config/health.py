from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Answers /health before the HTTPS redirect and host check, so the server can probe it on localhost."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in ("/health", "/health/"):
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
        return JsonResponse({"status": "ok"})
