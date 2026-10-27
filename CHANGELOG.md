# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- The staff web panel now lives in a top-level `website/` app, separate from
  the Django backend, so frontend contributors can focus on it directly.

### Fixed

- Excel sales exports no longer include deleted sales or deleted sale lines.

## [1.0.1] - 2026-10-27

### Added

- Offline-first desktop application with a local SQLite copy of all shop data.
- Django REST API and staff web panel for sales, stock, services, expenses,
  users, and reports.
- Pull/push synchronisation with per-device API tokens and reusable
  connection hashes.
- Partial payments with payment history.
- Service charges and expense tracking with profit/loss reporting.
- CSV exports in the web panel and Excel exports in the desktop app.
- Windows installer built with PyInstaller and Inno Setup.
- Safe database upgrades: pending migrations snapshot the shop database,
  verify the snapshot, and stop the app if the migration fails.

### Changed

- Stock is now changed only through ledger deltas. The invariant
  `quantity_in_stock == sum(deltas)` is verifiable with
  `manage.py rebuild_stock`.
- Report and service CSV exports respect the date range selected in the UI.
- Shop name and production server URL are configurable instead of hard-coded.

### Fixed

- Stock quantities drifting away from the adjustment ledger after sync.
- Report export returning today's data after a different period was selected.
- Development and production desktop builds sharing credentials or sync
  cursors.
- Stale account data preventing desktop-created users from signing in on the
  web panel.

## [1.0.0] - 2026-09-19

### Added

- Initial shop-management release.
- Desktop sales, stock, and admin windows.
- Central Django server and single-shop pairing.
