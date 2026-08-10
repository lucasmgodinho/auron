# Architecture

The platform starts as a modular monolith: one deployable backend is the simplest way to develop and operate the product while its real boundaries are still emerging. Future business modules will be kept isolated within the backend so they can evolve without introducing distributed-system complexity prematurely.

The FastAPI backend owns application logic and persistence. The React frontend is a separate TypeScript application that communicates with the backend over HTTP. PostgreSQL is the primary database and SQLAlchemy plus Alembic manage access and schema evolution.

For local development, only PostgreSQL runs in Docker Compose. Python and Node.js run directly on the host for fast feedback and straightforward debugging.

Microservices, messaging, background-job infrastructure, and other scaling mechanisms are intentionally deferred until concrete product or operational needs justify them.

