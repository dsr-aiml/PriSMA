# Local deployment

Use the commands in README. First build requires Internet access to fetch container images, npm packages, and Python wheels. Allow several minutes. Migrate runs once, then API and worker start after the database is healthy. Frontend waits for API readiness. Inspect migrate separately: successful one-shot migration exits with code 0, rather than staying up.

```bash
sudo docker compose ps -a
sudo docker compose logs --tail=100 migrate api worker frontend
```

Port 3000 is bound to localhost. If occupied, change the published port and PUBLIC_ORIGIN together, rebuild/recreate, and use the new address. Do not expose this build to the internet. A production Compose override, reverse proxy, TLS setup, and VPS verification arrive in the deployment update.

## Backup and restore basics

```bash
# From the project root; private backups are ignored by .gitignore.
mkdir -p backups
sudo docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/prisma.sql
```

For a deliberate restore into a compatible database, stop API/worker first and review the SQL. A full database restore procedure with validation belongs to the reliability update; do not experiment against valuable data without a backup.

## Develop in VS Code

```bash
cd ~/Desktop/Codes/PriSMA
code .
```

The frontend supports `npm ci`, `npm run dev`, `npm run typecheck`, and `npm run build` with Node 22+. Local backend development needs Python 3.12+, a virtual environment, requirements + requirements-dev, PostgreSQL, Redis, DATABASE_URL, and REDIS_URL. The backend image installs libpq5 for Psycopg's Python implementation and checks that the driver loads during its build. For native Debian/Ubuntu development, install libpq5 on the host too. Compose is the simplest first run.
