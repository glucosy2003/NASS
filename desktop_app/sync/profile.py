"""Build profile: keeps the PRODUCTION desktop app and the DEVELOPMENT app
completely separated.

Why this exists
---------------
The desktop app runs in two very different modes on a developer machine:

    PROD  the frozen build (PyInstaller) shipped to the shop -> the real
          server, the real shop's data.  It must NEVER be influenced by
          whatever the developer is experimenting with.
    DEV   `python desktop_app/main.py` from a source checkout -> throwaway
          data, and its own sandbox server.

They used to share `%LOCALAPPDATA%\\NASS\\sync_config.json`, so whichever ran
last handed its server URL, API token and sync cursors to the other. A dev run
could therefore push a development database into the production server, where
`sales.sync.apply_changes` would happily overwrite the production admin
account's password hash (same username, different `external_id`) and rewrite
category identities. This module makes that impossible:

  1. each profile gets its OWN config directory, so credentials are never
     shared;
  2. each profile has its OWN default server URL;
  3. `assert_allowed()` refuses to let the DEV profile talk to the production
     host, no matter how the config file was edited.
"""

import os
import sys
from urllib.parse import urlparse

PROFILE_PROD = "prod"
PROFILE_DEV = "dev"

# Default production server for the frozen (shop) build. Set
# NASS_PRODUCTION_SERVER_URL before building to point at your own server.
DEFAULT_PRODUCTION_SERVER_URL = "https://your-server.example.com"
PRODUCTION_SERVER_URL = (
    os.getenv("NASS_PRODUCTION_SERVER_URL", "").strip()
    or DEFAULT_PRODUCTION_SERVER_URL
).rstrip("/")

_extra_production_hosts = {
    host.strip().lower()
    for host in os.getenv("NASS_PRODUCTION_HOSTS", "").split(",")
    if host.strip()
}
PRODUCTION_HOSTS = frozenset(
    filter(None, {urlparse(PRODUCTION_SERVER_URL).hostname} | _extra_production_hosts)
)

# Where a dev server is expected. Override with NASS_DEV_SERVER_URL, e.g. to
# point at a second PythonAnywhere account instead of a local one.
DEFAULT_DEV_SERVER_URL = "http://127.0.0.1:8000"


class ProfileViolation(Exception):
    """Raised when a client tries to reach a server its profile forbids."""


def current_profile():
    """PROD for the frozen/shop build, DEV for a source checkout."""
    return PROFILE_PROD if getattr(sys, "frozen", False) else PROFILE_DEV


def is_development():
    return current_profile() == PROFILE_DEV


def config_dir_name():
    """Config folder per profile, so dev and prod never share credentials."""
    return "NASS-dev" if is_development() else "NASS"


def default_server_url(profile=None):
    profile = profile or current_profile()
    if profile == PROFILE_PROD:
        return PRODUCTION_SERVER_URL
    return os.getenv("NASS_DEV_SERVER_URL", "").strip() or DEFAULT_DEV_SERVER_URL


def is_production_server(server_url):
    host = urlparse((server_url or "").strip()).hostname or ""
    return host.lower() in PRODUCTION_HOSTS


def assert_allowed(server_url, profile=None):
    """Raise ProfileViolation if this profile may not use `server_url`.

    The one direction that matters: development must never write to
    production. A production build pointing at a dev server is merely
    pointless, not dangerous, so it is allowed.
    """
    profile = profile or current_profile()
    if profile != PROFILE_DEV:
        return server_url
    if is_production_server(server_url):
        raise ProfileViolation(
            "Blocked: the development app cannot connect to the production "
            f"server ({PRODUCTION_SERVER_URL}).\n\n"
            "The dev app uses its own database and its own sandbox server, so "
            "development data can never be pushed into the live shop.\n\n"
            f"Point the dev app at your sandbox server instead, or set "
            f"NASS_DEV_SERVER_URL (default: {DEFAULT_DEV_SERVER_URL})."
        )
    return server_url
