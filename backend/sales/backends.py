from sales.models import AdminUser


class AdminUserBackend:
    """
    Custom authentication backend for the AdminUser model.
    Allows Django's login()/logout() and session middleware to work
    with our non-AbstractBaseUser model.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = AdminUser.objects.get(username=username, is_active=True, deleted=False)
            if user.check_password(password):
                return user
        except AdminUser.DoesNotExist:
            return None
        return None

    def get_user(self, user_id):
        try:
            return AdminUser.objects.get(pk=user_id, is_active=True, deleted=False)
        except AdminUser.DoesNotExist:
            return None
