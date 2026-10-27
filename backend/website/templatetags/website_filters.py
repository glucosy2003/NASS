from django import template

register = template.Library()


@register.filter
def currency(value):
    """Format a number as MK currency with commas and 2 decimal places."""
    try:
        num = float(value)
        return f"MK {num:,.2f}"
    except (ValueError, TypeError):
        return "MK 0.00"


@register.filter
def currency_raw(value):
    """Format a number with commas and 2 decimal places (no MK prefix)."""
    try:
        num = float(value)
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return "0.00"
