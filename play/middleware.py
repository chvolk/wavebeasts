"""Keep signed-in pages out of browser caches. Firefox on Android served a stale /battle/ from its HTTP
cache after a ladder match ran from another device; every logged-in HTML response is now private,
no-store unless the view chose its own Cache-Control (sprites, API endpoints)."""


class NoStoreForAuthenticatedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated and "Cache-Control" not in response
                and response.get("Content-Type", "").startswith("text/html")):
            response["Cache-Control"] = "private, no-store"
        return response
