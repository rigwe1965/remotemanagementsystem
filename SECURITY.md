# Security policy

## Reporting a problem

Please do not open a public issue for a security problem. Email **info@facyke.com** with what you found and where (endpoint, page or file), how to reproduce it, and what an attacker could do with it. You will get a first reply within 5 working days.

## What is in scope

The code in this repository: the Flask API, the Streamlit dashboard, the React frontend and the device agent. Past reviews are in `audits/`.

## Running it safely

- Never commit `.env`. Use long random values for every secret, and a strong database password. The values in `.env.example` and `docker-compose.yml` are for local development only; change them everywhere else.
- Run behind HTTPS. Enrol agents only over HTTPS and keep agent enrolment keys private.
- Set `ANTHROPIC_API_KEY` only on the server, or set `AI_ASSISTANT_ENABLED=false`.
- Keep `BACKUP_DIR` outside the project folder, and never commit backups, `dump.rdb` or logs.

## Supported versions

Only `main` receives fixes.
