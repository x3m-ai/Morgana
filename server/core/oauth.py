"""
Morgana - OAuth2 / OIDC provider abstraction.

Implements the authorization-code flow for:
  - Google       (OIDC via accounts.google.com)
  - GitHub       (OAuth2 + user API)
  - Microsoft    (Azure AD OIDC, configurable tenant)
  - Enterprise   (generic OIDC via .well-known/openid-configuration discovery)

Each provider returns a standardised UserInfo dict:
    { "sub": str, "email": str, "name": str, "provider": str }

State parameter is a compact HMAC-signed token so no server-side session storage
is needed:
    state = base64url( provider + ":" + nonce + ":" + return_to )  +  "." + hmac_sig

Usage (in routers/auth.py):
    from core.oauth import get_provider, build_state, verify_state

    url   = get_provider("google").auth_url(redirect_uri, state, extra_scopes=[])
    info  = await get_provider("google").exchange(code, redirect_uri, db)
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Optional

import httpx

from config import settings

log = logging.getLogger("morgana.oauth")

VALID_PROVIDERS = {"google", "github", "microsoft", "oidc"}

# Cached OIDC discovery docs (issuer -> discovery doc)
_oidc_discovery_cache: dict = {}


# ---------------------------------------------------------------------------
# State helpers (HMAC, no session storage needed)
# ---------------------------------------------------------------------------

def build_state(provider: str, return_to: str = "/ui/") -> str:
    """
    Build a signed state token:
        payload = base64url({"p": provider, "n": nonce, "r": return_to, "t": ts})
        state   = payload + "." + hmac_sha256(secret_key, payload)
    """
    nonce   = secrets.token_hex(8)
    payload = base64.urlsafe_b64encode(
        json.dumps({"p": provider, "n": nonce, "r": return_to, "t": int(time.time())}).encode()
    ).rstrip(b"=").decode()
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}.{sig}"


def verify_state(state: str) -> dict:
    """
    Verify state token. Returns decoded payload or raises ValueError.
    Rejects tokens older than 10 minutes.
    """
    try:
        payload_b64, sig = state.rsplit(".", 1)
    except ValueError:
        raise ValueError("Malformed state token")

    expected = hmac.new(settings.secret_key.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expected, sig):
        raise ValueError("State signature invalid")

    # Restore base64 padding
    padding = 4 - len(payload_b64) % 4
    padded  = payload_b64 + ("=" * (padding % 4))
    data = json.loads(base64.urlsafe_b64decode(padded))

    if time.time() - data.get("t", 0) > 600:  # 10 min window
        raise ValueError("State token expired")

    return data  # keys: p, n, r, t


# ---------------------------------------------------------------------------
# Provider base class
# ---------------------------------------------------------------------------

class OAuthProvider:
    name: str = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def auth_url(self, redirect_uri: str, state: str) -> str:
        raise NotImplementedError

    async def exchange(self, code: str, redirect_uri: str) -> dict:
        """Exchange authorization code for UserInfo. Returns {"sub","email","name"}."""
        raise NotImplementedError

    def _params(self, redirect_uri: str, state: str, scope: str, client_id: str, auth_url: str) -> str:
        from urllib.parse import urlencode
        p = {
            "client_id":     client_id,
            "redirect_uri":  redirect_uri,
            "response_type": "code",
            "scope":         scope,
            "state":         state,
        }
        return f"{auth_url}?{urlencode(p)}"

    async def _post_token(self, token_url: str, params: dict, headers: Optional[dict] = None) -> dict:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(token_url, data=params, headers=headers or {})
        r.raise_for_status()
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            return r.json()
        # GitHub returns www-form-urlencoded
        from urllib.parse import parse_qs
        qs = parse_qs(r.text)
        return {k: v[0] for k, v in qs.items()}


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

class GoogleProvider(OAuthProvider):
    name = "google"
    _AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
    _TOKEN_URL = "https://oauth2.googleapis.com/token"
    _INFO_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

    def is_configured(self) -> bool:
        return bool(settings.oauth_google_client_id)

    def auth_url(self, redirect_uri: str, state: str) -> str:
        return self._params(
            redirect_uri, state,
            "openid email profile",
            settings.oauth_google_client_id,
            self._AUTH_URL,
        ) + "&access_type=offline&prompt=select_account"

    async def exchange(self, code: str, redirect_uri: str) -> dict:
        tokens = await self._post_token(self._TOKEN_URL, {
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  redirect_uri,
            "client_id":     settings.oauth_google_client_id,
            "client_secret": settings.oauth_google_client_secret,
        })
        access_token = tokens.get("access_token") or tokens.get("id_token")
        if not access_token:
            raise ValueError(f"Google token exchange failed: {tokens}")

        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(self._INFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
        r.raise_for_status()
        info = r.json()
        return {
            "sub":      info.get("sub"),
            "email":    (info.get("email") or "").lower(),
            "name":     info.get("name") or info.get("email", ""),
            "provider": "google",
        }


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

class GitHubProvider(OAuthProvider):
    name = "github"
    _AUTH_URL     = "https://github.com/login/oauth/authorize"
    _TOKEN_URL    = "https://github.com/login/oauth/access_token"
    _USER_URL     = "https://api.github.com/user"
    _EMAILS_URL   = "https://api.github.com/user/emails"

    def is_configured(self) -> bool:
        return bool(settings.oauth_github_client_id)

    def auth_url(self, redirect_uri: str, state: str) -> str:
        from urllib.parse import urlencode
        p = {
            "client_id":    settings.oauth_github_client_id,
            "redirect_uri": redirect_uri,
            "scope":        "read:user user:email",
            "state":        state,
        }
        from urllib.parse import urlencode
        return f"{self._AUTH_URL}?{urlencode(p)}"

    async def exchange(self, code: str, redirect_uri: str) -> dict:
        tokens = await self._post_token(
            self._TOKEN_URL,
            {
                "client_id":     settings.oauth_github_client_id,
                "client_secret": settings.oauth_github_client_secret,
                "code":          code,
                "redirect_uri":  redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError(f"GitHub token exchange failed: {tokens}")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=15) as c:
            u_resp  = await c.get(self._USER_URL,   headers=headers)
            em_resp = await c.get(self._EMAILS_URL, headers=headers)
        u_resp.raise_for_status()

        user_info = u_resp.json()
        email     = user_info.get("email")

        # GitHub may hide email; get primary from /user/emails
        if not email and em_resp.status_code == 200:
            for entry in em_resp.json():
                if entry.get("primary") and entry.get("verified"):
                    email = entry.get("email")
                    break

        if not email:
            raise ValueError("GitHub account has no accessible verified email")

        return {
            "sub":      str(user_info.get("id")),
            "email":    email.lower(),
            "name":     user_info.get("name") or user_info.get("login", ""),
            "provider": "github",
        }


# ---------------------------------------------------------------------------
# Microsoft (Azure AD)
# ---------------------------------------------------------------------------

class MicrosoftProvider(OAuthProvider):
    name = "microsoft"

    def is_configured(self) -> bool:
        return bool(settings.oauth_microsoft_client_id)

    def _base(self) -> str:
        tenant = settings.oauth_microsoft_tenant or "common"
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    def auth_url(self, redirect_uri: str, state: str) -> str:
        return self._params(
            redirect_uri, state,
            "openid email profile User.Read",
            settings.oauth_microsoft_client_id,
            f"{self._base()}/authorize",
        ) + "&response_mode=query"

    async def exchange(self, code: str, redirect_uri: str) -> dict:
        tokens = await self._post_token(f"{self._base()}/token", {
            "grant_type":    "authorization_code",
            "client_id":     settings.oauth_microsoft_client_id,
            "client_secret": settings.oauth_microsoft_client_secret,
            "code":          code,
            "redirect_uri":  redirect_uri,
            "scope":         "openid email profile User.Read",
        })
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError(f"Microsoft token exchange failed: {tokens}")

        # Decode id_token claims (no need to verify sig locally - we trusted the token endpoint)
        id_token = tokens.get("id_token", "")
        claims   = _decode_jwt_unverified(id_token) if id_token else {}
        email    = claims.get("email") or claims.get("preferred_username", "")
        name     = claims.get("name", email)
        sub      = claims.get("sub") or claims.get("oid", "")

        if not email:
            # Fallback: call /me endpoint
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    "https://graph.microsoft.com/v1.0/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if r.status_code == 200:
                me = r.json()
                email = me.get("mail") or me.get("userPrincipalName", "")
                name  = me.get("displayName", name)
                sub   = me.get("id", sub)

        if not email:
            raise ValueError("Microsoft account has no accessible email")

        return {
            "sub":      sub,
            "email":    email.lower(),
            "name":     name,
            "provider": "microsoft",
        }


# ---------------------------------------------------------------------------
# Enterprise OIDC (generic, configurable)
# ---------------------------------------------------------------------------

class OIDCProvider(OAuthProvider):
    name = "oidc"

    def is_configured(self) -> bool:
        return bool(settings.oidc_client_id and settings.oidc_issuer_url)

    async def _discover(self) -> dict:
        issuer = settings.oidc_issuer_url.rstrip("/")
        if issuer in _oidc_discovery_cache:
            return _oidc_discovery_cache[issuer]
        url = f"{issuer}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url)
        r.raise_for_status()
        doc = r.json()
        _oidc_discovery_cache[issuer] = doc
        return doc

    def auth_url(self, redirect_uri: str, state: str) -> str:
        # Sync wrapper - discovery is done at callback time
        issuer = settings.oidc_issuer_url.rstrip("/")
        # Use standard OIDC auth endpoint pattern
        auth_ep = f"{issuer}/authorize"
        return self._params(
            redirect_uri, state,
            "openid email profile",
            settings.oidc_client_id,
            auth_ep,
        )

    async def _auth_url_async(self, redirect_uri: str, state: str) -> str:
        doc = await self._discover()
        return self._params(
            redirect_uri, state,
            "openid email profile",
            settings.oidc_client_id,
            doc["authorization_endpoint"],
        )

    async def exchange(self, code: str, redirect_uri: str) -> dict:
        doc      = await self._discover()
        token_ep = doc["token_endpoint"]

        tokens = await self._post_token(token_ep, {
            "grant_type":    "authorization_code",
            "client_id":     settings.oidc_client_id,
            "client_secret": settings.oidc_client_secret,
            "code":          code,
            "redirect_uri":  redirect_uri,
        })
        id_token = tokens.get("id_token", "")
        claims   = _decode_jwt_unverified(id_token) if id_token else {}

        email = (
            claims.get("email")
            or claims.get("preferred_username")
            or ""
        )
        name = claims.get("name") or claims.get("given_name") or email
        sub  = claims.get("sub", "")

        if not email and "userinfo_endpoint" in doc:
            access_token = tokens.get("access_token", "")
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    doc["userinfo_endpoint"],
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if r.status_code == 200:
                info  = r.json()
                email = info.get("email") or info.get("preferred_username", "")
                name  = info.get("name", name)
                sub   = info.get("sub", sub)

        if not email:
            raise ValueError("OIDC provider returned no email claim")

        return {
            "sub":      sub,
            "email":    email.lower(),
            "name":     name,
            "provider": "oidc",
        }


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict = {
    "google":    GoogleProvider(),
    "github":    GitHubProvider(),
    "microsoft": MicrosoftProvider(),
    "oidc":      OIDCProvider(),
}


def get_provider(name: str) -> OAuthProvider:
    if name not in _PROVIDERS:
        raise ValueError(f"Unknown OAuth provider: {name}")
    return _PROVIDERS[name]


def configured_providers() -> list:
    """Return list of currently configured provider names."""
    return [name for name, p in _PROVIDERS.items() if p.is_configured()]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _decode_jwt_unverified(token: str) -> dict:
    """Decode JWT payload without signature verification (used for id_token claims)."""
    try:
        parts   = token.split(".")
        padding = 4 - len(parts[1]) % 4
        payload = base64.urlsafe_b64decode(parts[1] + "=" * (padding % 4))
        return json.loads(payload)
    except Exception:
        return {}
