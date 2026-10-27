# Documentation

Start here depending on what you are doing.

| I want to... | Read |
|---|---|
| Understand how the system works | [Architecture](architecture.md) |
| Run the project locally | [Development setup](setup.md) |
| Deploy the central server | [Deployment](deployment.md) |
| Build the desktop app and installer | [Build and release](build-and-release.md) |
| Understand roles, pairing, and tokens | [Authentication](authentication.md) |
| Understand sync and repair stock | [Offline sync](offline-sync.md) |
| Use or customise the web panel | [Staff web panel](website.md) |
| Upgrade a live shop | [Upgrading](upgrading.md) |
| Fix a problem | [Troubleshooting](troubleshooting.md) |

## Conventions used in the docs

- Commands are shown for **PowerShell** on Windows unless a Bash block is
  marked otherwise.
- `YOURUSERNAME`, `YOURSERVER`, and `<...>` are placeholders. Replace them with
  your own values.
- `.\venv\Scripts\python.exe` is the project interpreter. Activate the venv if
  you prefer plain `python`.
- Paths beginning with `backend/`, `website/`, `desktop_app/`, or `scripts/` are
  relative to the repository root.

## Repository map

| Path | Contents |
|---|---|
| `backend/nass_backend/` | Django settings and URL routing |
| `backend/sales/` | Models, API, sync engine, permissions, commands |
| `website/` | Staff web panel |
| `desktop_app/` | PyQt5 desktop application |
| `desktop_app/sync/` | Sync client and configuration |
| `database/seed.sqlite3` | Clean database template |
| `packaging/` | PyInstaller and Inno Setup definitions |
| `scripts/` | Build helpers |

## Getting help

- Bugs and feature requests: open an issue on GitHub.
- Security problems: follow [SECURITY.md](../SECURITY.md), not a public issue.
- Contribution guidelines: [CONTRIBUTING.md](../CONTRIBUTING.md).
