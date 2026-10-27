"""
API authentication: token-based.

The desktop client (and web UI) logs in with username + password ONCE and
receives a random token bound to that device. That token is sent on every
API call in the `Authorization: Token <token>` header.
"""

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from sales.models import ApiToken


class TokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith(self.keyword + " "):
            return None
        token_value = header[len(self.keyword) + 1 :].strip()
        if not token_value:
            return None

        try:
            token = ApiToken.objects.select_related("user").get(token=token_value)
        except ApiToken.DoesNotExist:
            raise AuthenticationFailed("Invalid or expired token.", code="invalid_token")

        if not token.is_valid:
            raise AuthenticationFailed("Token revoked or account inactive.", code="revoked")

        token.last_used_at = timezone.now()
        token.save(update_fields=["last_used_at"])
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword