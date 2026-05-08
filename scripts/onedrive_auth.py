"""One-time Microsoft OneDrive OAuth helper for AISO private beta storage.

Run locally:
    .venv/bin/python scripts/onedrive_auth.py

The script opens Microsoft login, listens on localhost for the callback, and
prints the MICROSOFT_REFRESH_TOKEN value to place in Railway. Do not commit or
share the printed token.
"""

from __future__ import annotations

import os
import secrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import requests


HOST = "127.0.0.1"
PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = "offline_access Files.ReadWrite User.Read"
TOKEN_BASE_URL = "https://login.microsoftonline.com"


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "AISOOneDriveAuth/1.0"
    code: str | None = None
    error: str | None = None
    state: str | None = None

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        CallbackHandler.code = (query.get("code") or [None])[0]
        CallbackHandler.error = (query.get("error_description") or query.get("error") or [None])[0]
        CallbackHandler.state = (query.get("state") or [None])[0]

        success = CallbackHandler.code and not CallbackHandler.error
        body = (
            "<h1>AISO OneDrive connected</h1><p>You can close this browser tab.</p>"
            if success
            else "<h1>AISO OneDrive connection failed</h1><p>Return to the terminal for details.</p>"
        )
        encoded = body.encode("utf-8")
        self.send_response(200 if success else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        print(f"Missing {name}. Export it locally before running this helper.", file=sys.stderr)
        sys.exit(1)
    return value


def _exchange_code_for_tokens(
    *,
    tenant: str,
    client_id: str,
    client_secret: str,
    code: str,
) -> dict[str, Any]:
    response = requests.post(
        f"{TOKEN_BASE_URL}/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        print("Microsoft token exchange failed.", file=sys.stderr)
        try:
            payload = response.json()
        except ValueError:
            payload = {"error": response.text[:500]}
        print(payload, file=sys.stderr)
        sys.exit(1)
    return response.json()


def main() -> None:
    tenant = os.getenv("MICROSOFT_TENANT", "consumers").strip() or "consumers"
    client_id = _required_env("MICROSOFT_CLIENT_ID")
    client_secret = _required_env("MICROSOFT_CLIENT_SECRET")
    expected_state = secrets.token_urlsafe(24)
    auth_url = (
        f"{TOKEN_BASE_URL}/{tenant}/oauth2/v2.0/authorize?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "response_mode": "query",
                "scope": SCOPES,
                "state": expected_state,
                "prompt": "consent",
            }
        )
    )

    print("Opening Microsoft login...")
    print(f"If the browser does not open, paste this URL:\n{auth_url}\n")
    webbrowser.open(auth_url)

    with HTTPServer((HOST, PORT), CallbackHandler) as server:
        print(f"Waiting for Microsoft callback on {REDIRECT_URI}")
        server.handle_request()

    if CallbackHandler.error:
        print(f"Microsoft authorization failed: {CallbackHandler.error}", file=sys.stderr)
        sys.exit(1)
    if CallbackHandler.state != expected_state:
        print("OAuth state mismatch. Try again.", file=sys.stderr)
        sys.exit(1)
    if not CallbackHandler.code:
        print("No authorization code was received. Try again.", file=sys.stderr)
        sys.exit(1)

    tokens = _exchange_code_for_tokens(
        tenant=tenant,
        client_id=client_id,
        client_secret=client_secret,
        code=CallbackHandler.code,
    )
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    if not refresh_token:
        print("Microsoft did not return a refresh token. Confirm offline_access permission.", file=sys.stderr)
        sys.exit(1)

    print("\nAdd this value to Railway backend variables:")
    print(f"MICROSOFT_REFRESH_TOKEN={refresh_token}")
    print("\nKeep it secret. Do not commit it or paste it into chat.")


if __name__ == "__main__":
    main()
