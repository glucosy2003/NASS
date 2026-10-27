# Staff web panel

The web panel is a server-rendered Django site for staff who prefer a browser
over the desktop app. It is **online only**: every action reads and writes the
server database immediately.

## Pages

| Path | Purpose | Role |
|---|---|---|
| `/setup/` | First-run owner account creation | Public (only while no account exists) |
| `/login/` | Sign in as admin or cashier | Public |
| `/logout/` | End the session | Signed in |
| `/dashboard/` | Landing page | Signed in |
| `/sales/` | Record a sale | Signed in |
| `/sales/partial/` | Credit sales and payment collection | Signed in |
| `/admin-panel/` | Admin overview | Admin |
| `/admin-panel/stock/` | Items, prices, and stock adjustments | Admin |
| `/admin-panel/categories/` | Categories | Admin |
| `/admin-panel/services/` | Service catalogue and service income | Admin |
| `/admin-panel/expenses/` | Operating expenses | Admin |
| `/admin-panel/reports/` | Sales, profit, and performance reports | Admin |
| `/admin-panel/history/` | Partial-payment history | Admin |
| `/admin-panel/users/` | Staff accounts | Admin |
| `/account/info/` | Own account details | Signed in |
| `/account/change-password/` | Change own password | Signed in |
| `/about/` | Version, licence, and credits | Signed in |

## Sales

The sales page lists active items with price and available stock. Staff build a
cart, optionally set the sale date, and submit. The server:

- creates the sale and its lines with UUIDs;
- appends the stock deltas in the same transaction;
- rejects a sale if an item is missing or the payload is invalid.

Cashiers and admins can both record sales. Cost and profit are hidden from
cashiers.

## Stock and categories

Admins can create and edit items, set prices, and adjust stock. A stock
adjustment records a delta; it does not overwrite the quantity. The item's
cached quantity updates in the same transaction.

Deleting an item or category is a soft delete, so the change also propagates to
desktop clients through sync.

## Services and expenses

- **Services** define a name and default charge. A **service entry** records
  income for a date, like a sale.
- **Expenses** record operating costs by date and category.

Both feed the profit/loss report.

## Reports and exports

The reports page shows revenue, cost, profit, and item performance for a
selected date range.

The **Export CSV** buttons export the range currently selected in the From and
To fields. The same applies to the services and expenses pages. Changing the
dates and clicking Export does not require a page reload.

Exports are served as CSV with a filename that includes the date range.

## Partial payments

Credit sales have a header (`PartialPayment`) and append-only payment records.
The page supports:

- creating a credit sale;
- recording a payment;
- collecting the remaining balance;
- settling the sale.

Totals are derived from non-deleted payment records, so multiple devices can
record payments without overwriting each other.

## Layout and customisation

| Item | Location |
|---|---|
| Templates | `website/templates/website/` |
| Static assets | `website/static/` |
| Shop name | `NASS_SHOP_NAME` environment variable |
| Context processor | `website/context_processors.py` |
| Routes | `website/urls.py` |
| Views | `website/views.py` |

The shop name appears in the page header and the admin dashboard. It defaults
to `My Shop`, so set `NASS_SHOP_NAME` before deploying.

The About page is generated from `about.html` and shows the version from
Django settings, the MIT licence, and the contributor credit.

## Static files in production

Django does not serve static files when `DEBUG=False`. On PythonAnywhere, add a
static mapping:

| URL | Directory |
|---|---|
| `/static/` | `/home/YOURUSERNAME/Nasimango_Auto-Stocking_System/website/static` |

For other hosts, run `collectstatic` and let the web server or a CDN serve the
files.

## Security

- Every page except `/setup/`, `/login/`, and the health endpoint requires a
  session.
- Admin-only pages check the role and redirect or reject cashiers.
- Forms use Django's CSRF protection.
- Sessions expire according to Django's defaults; configure
  `SESSION_COOKIE_AGE` if the shop needs a different policy.
- The site must be served over HTTPS in production.
