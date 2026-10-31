# Neelonaut Studio Backend

FastAPI modular monolith for `studio.neelonaut.com`. The application uses PostgreSQL through SQLAlchemy in deployed environments and supports SQLite for local development and tests.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

OpenAPI is available at `/docs`. All product endpoints are under `/api/v1`.

## Architecture

`app/models.py` contains separate bounded-domain tables for identity, workspaces/documents, publishing, community, AI, and media. `app/services.py` contains authentication/session, access-control, slug, versioning, and provider abstractions. Route handlers only coordinate validation, dependencies, and service operations.

The current AI provider is a deterministic local provider so the API is usable without transmitting document content to a third party. A production provider should implement `AIProvider`, keep system instructions separate from user content, enforce timeouts/retries/rate limits, and store metadata rather than sensitive prompts.

Cookie authentication uses an HttpOnly, signed, expiring session cookie plus a separate CSRF cookie/token for state-changing requests. Public publication reads do not require authentication. Signup currently marks email as verified for development; production must replace this with a single-use, expiring email-verification flow before enabling publishing/community access.

## Configuration

See `.env.example`. `DATABASE_URL` should be PostgreSQL in production. Restrict `ALLOWED_ORIGINS`, use a random `SECRET_KEY`, set `COOKIE_SECURE=true`, and place object storage credentials in the deployment secret manager. Large media must be stored in object storage; the media table is intentionally metadata-only.

## Validation

```bash
pytest
```

The MVP includes authentication, workspace membership, document CRUD with JSON block validation and optimistic versions, immutable publication content snapshots, discovery search, AI response contract, comments, reactions, follows, and reports. Remaining production work includes email delivery, object-storage signed URLs, admin role enforcement and review routes, background jobs/rate-limit persistence, full-text indexes, and complete migration DDL review against PostgreSQL.
