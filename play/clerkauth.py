"""Verify Clerk session JWTs so the site can trust a Clerk-authenticated user. Clerk runs the sign-in/up
UI on the frontend; after sign-in the page hands us the session token, we verify it here (RS256 against
Clerk's JWKS), then map it to a Django user and start a normal Django session. This keeps all existing
@login_required / request.user code working - Clerk is just the sign-in provider."""
import base64
import time

import jwt
import requests
from django.conf import settings


def friendly_name(sub):
    """Fetch a display name for a Clerk user id via the Backend API (needs CLERK_SECRET_KEY). Returns a
    nice label (name / username / email local-part) or "" on any failure - never raises."""
    key = getattr(settings, "CLERK_SECRET_KEY", "")
    if not key or not sub:
        return ""
    try:
        r = requests.get(f"https://api.clerk.com/v1/users/{sub}",
                         headers={"Authorization": f"Bearer {key}"}, timeout=6)
        if r.status_code != 200:
            return ""
        u = r.json()
        name = " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x).strip()
        if name:
            return name[:40]
        if u.get("username"):
            return str(u["username"])[:40]
        emails = u.get("email_addresses") or []
        if emails and emails[0].get("email_address"):
            return emails[0]["email_address"].split("@")[0][:40]
    except Exception:
        pass
    return ""

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
