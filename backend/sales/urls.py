from django.urls import path

from sales import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="api-health"),
    path("auth/login/", views.LoginView.as_view(), name="api-login"),
    path("auth/logout/", views.LogoutView.as_view(), name="api-logout"),
    path("auth/pair/", views.PairView.as_view(), name="api-pair"),
    path("categories/", views.CategoryListCreateView.as_view(), name="api-categories"),
    path(
        "categories/<uuid:external_id>/",
        views.CategoryDetailView.as_view(),
        name="api-category-detail",
    ),
    path("items/", views.ItemListCreateView.as_view(), name="api-items"),
    path(
        "items/<uuid:external_id>/",
        views.ItemDetailView.as_view(),
        name="api-item-detail",
    ),
    path(
        "items/<uuid:external_id>/stock/",
        views.ItemStockAdjustView.as_view(),
        name="api-item-stock",
    ),
    path("sales/", views.SaleListCreateView.as_view(), name="api-sales"),
    path(
        "sales/<uuid:external_id>/",
        views.SaleDetailView.as_view(),
        name="api-sale-detail",
    ),
    path("sync/pull/", views.SyncPullView.as_view(), name="api-sync-pull"),
    path("sync/push/", views.SyncPushView.as_view(), name="api-sync-push"),
    path("users/", views.UserListCreateView.as_view(), name="api-users"),
    path("users/<uuid:external_id>/", views.UserDetailView.as_view(), name="api-user-detail"),
    path("auditlog/", views.AuditLogView.as_view(), name="api-auditlog"),
]