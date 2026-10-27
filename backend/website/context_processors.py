from django.conf import settings
from sales.models import ROLE_ADMIN


def website_context(request):
    """Global template context for all website pages."""
    ctx = {
        "shop_name": getattr(settings, "SHOP_NAME", "My Shop"),
        "nass_version": getattr(settings, "NASS_VERSION", "1.0.1"),
        "is_admin": False,
        "is_cashier": False,
    }
    if hasattr(request, "user") and request.user is not None:
        user = request.user
        if hasattr(user, "role"):
            ctx["is_admin"] = user.role == ROLE_ADMIN
            ctx["is_cashier"] = user.role != ROLE_ADMIN
    return ctx
