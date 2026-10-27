from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter username",
                "class": "form-input",
                "autofocus": True,
                "autocomplete": "off",
            }
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={
                "placeholder": "Enter password",
                "class": "form-input",
                "autocomplete": "new-password",
            }
        ),
    )


class SaleItemForm(forms.Form):
    """Form for adding an item to the sale cart."""
    item_id = forms.IntegerField(widget=forms.HiddenInput())
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        initial=1,
        min_value=0.001,
        widget=forms.NumberInput(
            attrs={"class": "form-input qty-input", "min": "0.001", "step": "0.001"}
        ),
    )
    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-input price-input", "step": "0.01"}
        ),
    )


class ExpenseForm(forms.Form):
    date = forms.DateField(
        widget=forms.DateInput(
            attrs={"class": "form-input", "type": "date"}
        )
    )
    description = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "e.g. Transport"}
        ),
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "0.00"}
        ),
    )


class CategoryForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Category name"}
        ),
    )
    size_required = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )


class ServiceForm(forms.Form):
    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "e.g. fitting big tyre"}
        ),
    )
    price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "0.00"}
        ),
    )


class ServiceEntryForm(forms.Form):
    service_id = forms.IntegerField(widget=forms.HiddenInput())
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        initial=1,
        min_value=0.001,
        widget=forms.NumberInput(
            attrs={"class": "form-input qty-input", "min": "0.001", "step": "0.001"}
        ),
    )
    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-input price-input", "step": "0.01"}
        ),
    )
    customer_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Customer name (optional)"}
        ),
    )
    notes = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Notes (optional)"}
        ),
    )


class DateRangeForm(forms.Form):
    date_from = forms.DateField(
        widget=forms.DateInput(
            attrs={"class": "form-input", "type": "date"}
        )
    )
    date_to = forms.DateField(
        widget=forms.DateInput(
            attrs={"class": "form-input", "type": "date"}
        )
    )


class StockUpdateForm(forms.Form):
    """Form for adding stock to an item."""
    item_id = forms.IntegerField(widget=forms.HiddenInput())
    delta = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.001", "placeholder": "Quantity to add"}
        ),
    )
    details = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Reason (optional)"}
        ),
    )


class PartialPaymentCreateForm(forms.Form):
    item_id = forms.IntegerField(widget=forms.HiddenInput())
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        initial=1,
        min_value=0.001,
        widget=forms.NumberInput(
            attrs={"class": "form-input qty-input", "min": "0.001", "step": "0.001"}
        ),
    )
    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-input price-input", "step": "0.01"}
        ),
    )
    total_amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01"}
        ),
    )
    amount_paid = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        initial=0,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "0.00"}
        ),
    )
    collected = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-checkbox"}),
    )
    customer_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Customer name (required)"}
        ),
    )
    phone = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Phone (optional)"}
        ),
    )


class PartialPaymentRecordForm(forms.Form):
    """Form for recording a payment against a partial payment."""
    partial_payment_id = forms.IntegerField(widget=forms.HiddenInput())
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "Amount to pay"}
        ),
    )


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "Current password"}
        ),
    )
    new_password = forms.CharField(
        min_length=4,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "New password"}
        ),
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "Confirm new password"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("new_password") != cleaned.get("confirm_password"):
            raise forms.ValidationError("New passwords do not match.")
        return cleaned


class ItemForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Item name"}
        ),
    )
    category_id = forms.IntegerField(widget=forms.HiddenInput())
    unit_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "Selling price"}
        ),
    )
    cost_price = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.01", "placeholder": "Cost price"}
        ),
    )
    quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        initial=0,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-input", "step": "0.001", "placeholder": "Initial stock"}
        ),
    )
    brand = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Brand (optional)"}
        ),
    )
    size = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Size (optional)"}
        ),
    )


class UserCreateForm(forms.Form):
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Username"}
        ),
    )
    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Full name"}
        ),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={"class": "form-input", "placeholder": "Email (optional)"}
        ),
    )
    password = forms.CharField(
        min_length=4,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "Password"}
        ),
    )
    role = forms.ChoiceField(
        choices=[("admin", "Admin"), ("cashier", "Cashier")],
        widget=forms.Select(attrs={"class": "form-input"}),
    )


class UserEditForm(forms.Form):
    full_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"class": "form-input", "placeholder": "Full name"}
        ),
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(
            attrs={"class": "form-input", "placeholder": "Email (optional)"}
        ),
    )
    role = forms.ChoiceField(
        choices=[("admin", "Admin"), ("cashier", "Cashier")],
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    new_password = forms.CharField(
        required=False,
        min_length=4,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "placeholder": "New password (leave blank to keep current)"}
        ),
    )
