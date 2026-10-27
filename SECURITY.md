# Security Policy

## Supported versions

Security fixes are applied to the latest released version. Older versions
should be upgraded before reporting a vulnerability.

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| < 1.0 | No |

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private vulnerability reporting:

1. Open the repository on GitHub.
2. Go to **Security** &rarr; **Advisories**.
3. Click **Report a vulnerability**.

Include:

- the affected version and component (server, desktop, or sync API);
- steps to reproduce;
- the impact you believe the issue has;
- any suggested fix, if you have one.

You can expect an acknowledgement within a few days. Please allow time for a
fix to be prepared and released before disclosing the issue publicly.

## Sensitive data

Never commit or attach:

- `.env` files or real environment values;
- `DJANGO_SECRET_KEY`, API tokens, or connection hashes;
- `database/nass.sqlite3` or any real shop database;
- exported sales, customer, or payment data.

If a secret is exposed, rotate it immediately:

- change the affected admin password;
- revoke the connection hash with
  `python manage.py generate_connection_hash --revoke <id>`;
- revoke active API tokens in the admin panel;
- replace `DJANGO_SECRET_KEY` and restart the server.

## Deployment checklist

- Serve the server over HTTPS only.
- Set a long, random `DJANGO_SECRET_KEY` and `DJANGO_DEBUG=False`.
- Restrict `DJANGO_ALLOWED_HOSTS` to the real hostname.
- Use a dedicated database user with the minimum required permissions.
- Keep the operating system, Python, and dependencies up to date.
