"""Verify Clerk session JWTs so the site can trust a Clerk-authenticated user. Clerk runs the sign-in/up
UI on the frontend; after sign-in the page hands us the session token, we verify it here (RS256 against
Clerk's JWKS), then map it to a Django user and start a normal Django session. This keeps all existing
@login_required / request.user code working - Clerk is just the sign-in provider."""
import base64
import time

import jwt
import requests
from django.conf import settings


def account_profile(sub):
    """Read the primary email and display name from Clerk's authenticated backend API."""
    key = getattr(settings, "CLERK_SECRET_KEY", "")
    if not key or not sub:
        return None
    try:
        r = requests.get(f"https://api.clerk.com/v1/users/{sub}",
                         headers={"Authorization": f"Bearer {key}"}, timeout=6)
        r.raise_for_status()
        u = r.json()
        emails = u.get("email_addresses") or []
        primary = next((e for e in emails if e.get("id") == u.get("primary_email_address_id")), {})
        email = primary.get("email_address", "")
        name = " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x).strip()
        name = name or u.get("username") or email.split("@")[0]
        return {"name": str(name or "")[:40], "email": str(email or "")[:254]}
    except (requests.RequestException, ValueError, TypeError):
        return None


def sync_profile(user):
    profile = account_profile(user.username)
    if profile is not None:
        user.first_name = profile["name"]
        user.email = profile["email"]
        user.save(update_fields=["first_name", "email"])
    return profile


def friendly_name(sub):
    return (account_profile(sub) or {}).get("name", "")

_jwks_client = None


def frontend_api_host():
    """Derive Clerk's Frontend API host from the publishable key (pk_test_<base64('<host>$')>)."""
    pk = settings.CLERK_PUBLISHABLE_KEY or ""
    parts = pk.split("_", 2)
    if len(parts) < 3:
        return ""
    try:
        dec = base64.b64decode(parts[2] + "==").decode()
        return dec.rstrip("$")
    except Exception:
        return ""


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        host = frontend_api_host()
        if not host:
            return None
        _jwks_client = jwt.PyJWKClient(f"https://{host}/.well-known/jwks.json")
    return _jwks_client


def verify_clerk_token(token):
    """Return the verified claims (incl. 'sub' = Clerk user id) or None."""
    if not token:
        return None
    client = _jwks()
    if client is None:
        return None
    try:
        key = client.get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], options={"verify_aud": False})
    except Exception:
        return None
    # issuer + expiry sanity (Clerk 'iss' is the frontend API URL)
    host = frontend_api_host()
    if host and str(claims.get("iss", "")).rstrip("/") != f"https://{host}":
        return None
    if claims.get("exp", 0) < time.time() - 10:
        return None
    if not claims.get("sub"):
        return None
    return claims
