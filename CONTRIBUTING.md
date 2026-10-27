# Contributing

Thanks for taking the time to improve NASS.

## Before you start

- Read [docs/architecture.md](docs/architecture.md) and
  [docs/offline-sync.md](docs/offline-sync.md) so your change fits the
  offline-first model.
- Open an issue for non-trivial features or refactors so the design can be
  discussed first.
- Never commit real shop data, `.env` files, API tokens, or connection hashes.

## Development setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item database\seed.sqlite3 database\nass.sqlite3
python backend\manage.py migrate
python backend\manage.py runserver
```

Run the desktop app from a second terminal:

```powershell
.\venv\Scripts\python.exe desktop_app\main.py
```

## Tests

Every change must keep the suite green:

```powershell
.\venv\Scripts\python.exe backend\manage.py check
.\venv\Scripts\python.exe backend\manage.py test sales website
```

When fixing a sync or stock issue, add a regression test in
`backend/sales/tests_*.py`.

## Code style

- Follow standard Python style (PEP 8, 4-space indentation).
- Keep functions small and names explicit.
- Comment only where the reason is not obvious from the code.
- Match the existing structure of the Django app and the PyQt windows.
- Do not introduce new dependencies without discussing them first.

## Commits

Use short, descriptive commit messages in the imperative mood, for example:

```
fix: keep report export in sync with the selected date range
feat: add service income to the profit/loss report
docs: document the connection-hash pairing flow
```

Group related changes into a single commit. Avoid mixing formatting-only
changes with behaviour changes.

## Pull requests

Before opening a pull request:

- [ ] The change is focused and described clearly.
- [ ] `manage.py check` and the full test suite pass.
- [ ] New behaviour is covered by tests where practical.
- [ ] Documentation is updated when behaviour or commands change.
- [ ] No secrets, databases, build output, or unrelated files are included.

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE).
