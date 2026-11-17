## What and why

<!-- One or two sentences: what changes, and the problem it solves. -->

## Checklist

- [ ] Branch is `feat/…`, `fix/…`, `docs/…` or `chore/…`; nothing committed straight to `main`
- [ ] Tests pass locally: `cd api; python -m pytest tests -q`, plus dashboard, agent and `npm test` in `frontend/` for what you touched
- [ ] No secrets, keys, personal data, backups or `.env` content in the diff
- [ ] `CHANGELOG.md` updated under `[Unreleased]` if users will notice the change
- [ ] Database change? A new migration is included (`flask db upgrade` works on an empty database)
- [ ] Deploy needed? Say what to run, because merging deploys nothing
