from django.urls import path
from . import views

app_name = "web"

urlpatterns = [
    # Root redirect
    path("", views.root_view, name="root"),

    # Auth
    path("login/", views.login_view, name="login-alt"),
    path("logout/", views.logout_view, name="logout"),
    path("setup/", views.setup_view, name="setup"),

    # Dashboard
    path("dashboard/", views.dashboard_view, name="dashboard"),

    # Sales
    path("sales/", views.sales_entry_view, name="sales_entry"),
    path("sales/complete/", views.sales_complete_view, name="sales_complete"),
    path("sales/api/items/", views.sales_api_items, name="sales_api_items"),

    # Partial payments
    path("sales/partial/", views.partial_payments_view, name="partial_payments"),
    path("sales/partial/create/", views.partial_payment_create_view, name="partial_create"),
    path("sales/partial/record/", views.partial_payment_record_view, name="partial_record"),
    path("sales/partial/collect/", views.partial_payment_collect_view, name="partial_collect"),
    path("sales/partial/settle/", views.partial_payment_settle_view, name="partial_settle"),

    # Admin dashboard
    path("admin-panel/", views.admin_dashboard_view, name="admin_dashboard"),

    # Stock management
    path("admin-panel/stock/", views.stock_view, name="stock"),
    path("admin-panel/stock/add/", views.stock_add_item_view, name="stock_add"),
    path("admin-panel/stock/<int:item_id>/update/", views.stock_update_item_view, name="stock_update"),
    path("admin-panel/stock/<int:item_id>/delete/", views.stock_delete_item_view, name="stock_delete"),
    path("admin-panel/stock/<int:item_id>/adjust/", views.stock_adjust_view, name="stock_adjust"),

    # Categories
    path("admin-panel/categories/", views.categories_view, name="categories"),
    path("admin-panel/categories/create/", views.category_create_view, name="category_create"),
    path("admin-panel/categories/<int:cat_id>/update/", views.category_update_view, name="category_update"),
    path("admin-panel/categories/<int:cat_id>/delete/", views.category_delete_view, name="category_delete"),

    # Services
    path("admin-panel/services/", views.services_view, name="services"),
    path("admin-panel/services/create/", views.service_create_view, name="service_create"),
    path("admin-panel/services/<int:service_id>/update/", views.service_update_view, name="service_update"),
    path("admin-panel/services/<int:service_id>/delete/", views.service_delete_view, name="service_delete"),
    path("admin-panel/services/entry/", views.service_entry_create_view, name="service_entry_create"),
    path("admin-panel/services/entries/", views.service_entries_filter_view, name="services_entries"),
    path("admin-panel/services/export/", views.services_export_view, name="services_export"),

    # Expenses
    path("admin-panel/expenses/", views.expenses_view, name="expenses"),
    path("admin-panel/expenses/create/", views.expense_create_view, name="expense_create"),
    path("admin-panel/expenses/<int:expense_id>/delete/", views.expense_delete_view, name="expense_delete"),
    path("admin-panel/expenses/filter/", views.expense_filter_view, name="expense_filter"),
    path("admin-panel/expenses/export/", views.expenses_export_view, name="expenses_export"),

    # Reports
    path("admin-panel/reports/", views.reports_view, name="reports"),
    path("admin-panel/reports/filter/", views.reports_filter_view, name="reports_filter"),
    path("admin-panel/reports/sale/<int:sale_id>/delete/", views.report_sale_delete_view, name="report_sale_delete"),
    path("admin-panel/reports/export/", views.reports_export_view, name="reports_export"),

    # Partial payments history
    path("admin-panel/history/", views.partial_history_view, name="partial_history"),

    # User management
    path("admin-panel/users/", views.users_view, name="users"),
    path("admin-panel/users/create/", views.user_create_view, name="user_create"),
    path("admin-panel/users/<int:user_id>/edit/", views.user_edit_view, name="user_edit"),
    path("admin-panel/users/<int:user_id>/toggle/", views.user_toggle_active_view, name="user_toggle"),

    # Account
    path("account/change-password/", views.change_password_view, name="change_password"),
    path("account/info/", views.account_info_view, name="account_info"),
    path("account/update/", views.account_update_view, name="update_account"),

    # About
    path("about/", views.about_view, name="about"),
]
