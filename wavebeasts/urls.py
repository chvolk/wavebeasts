from django.contrib import admin
from django.urls import include, path

from play import views as play_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django auth stays as the fallback (used when Clerk isn't configured). When Clerk keys are set,
    # /login/ redirects to /sign-in/ (Clerk) — see play_views.login_page, settings.LOGIN_URL, base.html.
    path("login/", play_views.login_page, name="login"),
    path("logout/", play_views.sign_out, name="logout"),  # GET-friendly (Clerk afterSignOutUrl) + clears Django session
    path("", include("play.urls")),
]
