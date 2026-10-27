"""Tiny REST client for the NASS central server API (all endpoints under /api/)."""

import requests

from sync import profile
from sync.profile import ProfileViolation

TIMEOUT_SECONDS = 15
RETRY_COUNT = 1


class ApiError(Exception):
    def __init__(self, message, status_code=None, response=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class NotAuthenticated(ApiError):
    """HTTP 401 — token missing/expired/revoked."""


class NASSClient:
    def __init__(self, server_url, token=None, device_id=None, timeout=TIMEOUT_SECONDS):
        self.base_url = (server_url or "").rstrip("/")
        # Enforced here, not in the UI, so that EVERY request path is covered
        # -- including a config file that was hand-edited to point a dev run at
        # the production host. Raises ProfileViolation for a forbidden pairing.
        profile.assert_allowed(self.base_url)
        self.token = token or ""
        self.device_id = device_id or ""
        self.timeout = timeout

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    def _url(self, path):
        path = path.lstrip("/")
        # Always use a trailing slash — Django's CommonMiddleware would
        # otherwise redirect POST requests to the canonical URL, turning them
        # into GETs and dropping the request body.
        if not path.endswith("/"):
            path += "/"
        return f"{self.base_url}/api/{path}"

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        return headers

    def _request(self, method, path, json_data=None):
        last_error = None
        for _ in range(RETRY_COUNT + 1):
            try:
                resp = requests.request(
                    method,
                    self._url(path),
                    headers=self._headers(),
                    json=json_data,
                    timeout=self.timeout,
                )
                if 200 <= resp.status_code < 300:
                    return resp.json() if resp.content else None
                if resp.status_code == 401:
                    raise NotAuthenticated(
                        "Authentication failed (401).", 401, resp
                    )
                raise ApiError(
                    f"{method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}",
                    resp.status_code,
                    resp,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
        raise ApiError(f"Network error contacting {self._url(path)}: {last_error}")

    # ------------------------------------------------------------------
    # endpoints
    # ------------------------------------------------------------------
    def health(self):
        return self._request("GET", "health")

    def login(self, username, password, device_name=""):
        data = {"username": username, "password": password, "device_name": device_name}
        return self._request("POST", "auth/login", data)

    def pair(
        self,
        connection_hash,
        username,
        password_hash="",
        device_name="",
    ):
        """Bind this desktop to a server account using a connection hash from
        ``manage.py generate_connection_hash``. Anonymous endpoint: returns
        {token, device_id, username}."""
        data = {
            "hash": connection_hash,
            "username": username,
            "password_hash": password_hash,
            "device_name": device_name,
        }
        return self._request("POST", "auth/pair", data)

    def logout(self):
        return self._request("POST", "auth/logout")

    def pull(self, since=None):
        data = {}
        if since:
            data["since"] = since
        if self.device_id:
            data["device_id"] = self.device_id
        return self._request("POST", "sync/pull", data)

    def push(self, payload):
        if self.device_id:
            payload["device_id"] = self.device_id
        return self._request("POST", "sync/push", payload)