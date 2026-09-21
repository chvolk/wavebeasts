from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from play import views as play_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django auth stays as the fallback (used when Clerk isn't configured). When Clerk keys are set the
    # nav + LOGIN_URL point at /sign-in/ (Clerk) instead — see settings.LOGIN_URL and base.html.
    path("login/", auth_views.LoginView.as_view(template_name="login.html"), name="login"),
    path("logout/", play_views.sign_out, name="logout"),  # GET-friendly (Clerk afterSignOutUrl) + clears Django session
    path("", include("play.urls")),
]
