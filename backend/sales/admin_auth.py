"""
Admin authentication and management utilities
"""

import secrets

from sales.models import AdminUser
from django.utils import timezone


class AdminAuthManager:
    """Manager class for admin authentication and password management"""

    @staticmethod
    def authenticate_admin(username, password):
        """
        Authenticate an admin user with username and password.
        Returns AdminUser object if credentials are valid, None otherwise.
        Updates last_login on successful authentication.
        """
        try:
            admin_user = AdminUser.objects.get(username=username, is_active=True)

            # Check password
            if admin_user.check_password(password):
                # Update last login
                admin_user.last_login = timezone.now()
                admin_user.save(update_fields=["last_login"])
                return admin_user

            return None
        except AdminUser.DoesNotExist:
            return None

    @staticmethod
    def change_password(admin_user, old_password, new_password):
        """
        Change password for an admin user.
        Returns (success, message) tuple.
        """
        if not admin_user.check_password(old_password):
            return False, "Current password is incorrect"

        if len(new_password) < 4:
            return False, "New password must be at least 4 characters long"

        if old_password == new_password:
            return False, "New password must be different from current password"

        admin_user.set_password(new_password)
        admin_user.save()
        return True, "Password changed successfully"

    @staticmethod
    def reset_password_to_default(admin_user):
        """
        Reset an admin user's password to a random temporary one.
        Returns (success, message, temporary_password) tuple.
        """
        temporary_password = secrets.token_urlsafe(12)
        admin_user.set_password(temporary_password)
        admin_user.save()
        return True, f"Temporary password generated for {admin_user.username}", temporary_password

    @staticmethod
    def update_admin_info(admin_user, full_name=None, email=None):
        """
        Update admin user information.
        Returns (success, message) tuple.
        """
        try:
            if full_name is not None:
                admin_user.full_name = full_name

            if email is not None:
                if email and AdminUser.objects.filter(email=email).exclude(id=admin_user.id).exists():
                    return False, "This email is already in use"
                admin_user.email = email or None

            admin_user.save()
            return True, "Admin information updated successfully"
        except Exception as e:
            return False, f"Error updating admin information: {str(e)}"

    @staticmethod
    def get_admin_info(admin_user):
        """
        Get admin user information (safe to send to frontend).
        Returns a dictionary with non-sensitive info.
        """
        return {
            "id": admin_user.id,
            "username": admin_user.username,
            "full_name": admin_user.full_name,
            "email": admin_user.email,
            "role": admin_user.role,
            "is_active": admin_user.is_active,
            "created_at": admin_user.created_at.isoformat(),
            "last_login": (
                admin_user.last_login.isoformat() if admin_user.last_login else None
            ),
            "last_password_changed": (
                admin_user.last_password_changed.isoformat()
                if admin_user.last_password_changed
                else None
            ),
        }

    @staticmethod
    def deactivate_admin(admin_user):
        """
        Deactivate an admin user account.
        Returns (success, message) tuple.
        """
        admin_user.is_active = False
        admin_user.save()
        return True, f"Admin user {admin_user.username} has been deactivated"

    @staticmethod
    def activate_admin(admin_user):
        """
        Activate an admin user account.
        Returns (success, message) tuple.
        """
        admin_user.is_active = True
        admin_user.save()
        return True, f"Admin user {admin_user.username} has been activated"

    @staticmethod
    def get_all_admins():
        """
        Get all admin users (for admin panel listing).
        Returns queryset of AdminUser objects.
        """
        return AdminUser.objects.all().order_by("-created_at")

    @staticmethod
    def create_admin_user(username, full_name, email, password=None, role=None):
        """
        Create a new admin user.
        Returns (success, user_or_message) tuple.
        """
        if not password:
            return False, "Password is required when creating a new admin user"

        if AdminUser.objects.filter(username=username).exists():
            return False, "Username already exists"

        if email and AdminUser.objects.filter(email=email).exists():
            return False, "Email already in use"

        try:
            from sales.models import ROLE_CHOICES

            valid_roles = dict(ROLE_CHOICES)
            admin_user = AdminUser.objects.create(
                username=username,
                full_name=full_name,
                email=email,
                is_active=True,
                role=role if role in valid_roles else ROLE_CHOICES[1][0],
            )

            admin_user.set_password(password)

            admin_user.save()
            return True, admin_user
        except Exception as e:
            return False, f"Error creating admin user: {str(e)}"
