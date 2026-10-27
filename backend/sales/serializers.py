"""
API serializers. Cost/profit data is stripped for cashiers (handled by the
`include_cost` request context, applied in views).
"""

from rest_framework import serializers

from sales.models import ROLE_CHOICES, AdminUser, Category, Item


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, trim_whitespace=False)
    device_name = serializers.CharField(required=False, allow_blank=True, default="")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = (
            "external_id",
            "name",
            "size_required",
            "deleted",
            "updated_at",
        )
        read_only_fields = ("external_id", "deleted", "updated_at")


class ItemSerializer(serializers.ModelSerializer):
    external_id = serializers.UUIDField(read_only=True)
    category_external_id = serializers.CharField(source="category.external_id", read_only=True)

    class Meta:
        model = Item
        fields = (
            "external_id",
            "name",
            "unit_price",
            "cost_price",
            "quantity_in_stock",
            "category",
            "category_external_id",
            "brand",
            "size",
            "deleted",
            "updated_at",
        )
        read_only_fields = ("deleted", "updated_at")

    def _include_cost(self):
        return self.context.get("include_cost", True)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._include_cost():
            data.pop("cost_price", None)
        return data


class ItemUpdateSerializer(ItemSerializer):
    """Item updates: stock can ONLY change via stock deltas or sales."""

    class Meta(ItemSerializer.Meta):
        read_only_fields = ("deleted", "updated_at", "quantity_in_stock")


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminUser
        fields = (
            "external_id",
            "username",
            "full_name",
            "email",
            "role",
            "is_active",
            "created_at",
            "last_login",
        )
        read_only_fields = fields


class AdminUserCreateSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=[c[0] for c in ROLE_CHOICES])
    password = serializers.CharField(required=True, trim_whitespace=False)


class AdminUserUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    role = serializers.ChoiceField(required=False, choices=[c[0] for c in ROLE_CHOICES])
    is_active = serializers.BooleanField(required=False)
    password = serializers.CharField(required=False, trim_whitespace=False)


class SaleCreateSerializer(serializers.Serializer):
    """Validates an incoming sale before it is applied by the sync engine."""

    external_id = serializers.CharField(required=False, allow_blank=True)
    date = serializers.DateTimeField(required=False)
    items = serializers.ListField(child=serializers.DictField(), write_only=True)