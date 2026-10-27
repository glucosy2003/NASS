"""
Role-based permissions for the API.

Exactly TWO roles exist:
    - admin   : everything (stock, prices, cost/profit, users, sync, reports)
    - cashier : make sales + view stock availability (no cost/profit, no edits)
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from sales.models import ROLE_ADMIN


class IsAuthenticatedUser(BasePermission):
    """Any active, logged-in user (admin OR cashier)."""

    def has_permission(self, request, view):
        return bool(
            request.user is not None
            and request.user.is_active
            and not request.user.deleted
        )


class IsAdmin(BasePermission):
    """Admins only."""

    def has_permission(self, request, view):
        return bool(
            request.user is not None
            and request.user.is_active
            and not request.user.deleted
            and request.user.role == ROLE_ADMIN
        )


class ReadOnlyBoth(BasePermission):
    """
    Cashier + admin can read; only admins can write.
    Cashiers can still create SALES (handled separately in the sale view).
    """

    def has_permission(self, request, view):
        user_ok = bool(
            request.user is not None
            and request.user.is_active
            and not request.user.deleted
        )
        if not user_ok:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role == ROLE_ADMIN