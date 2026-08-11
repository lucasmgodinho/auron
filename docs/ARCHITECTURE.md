# Architecture

The platform starts as a modular monolith: one deployable backend is the simplest way to develop and operate the product while its real boundaries are still emerging. Future business modules will be kept isolated within the backend so they can evolve without introducing distributed-system complexity prematurely.

The FastAPI backend owns application logic and persistence. The React frontend is a separate TypeScript application that communicates with the backend over HTTP. PostgreSQL is the primary database and SQLAlchemy plus Alembic manage access and schema evolution.

## SaaS Core and business modules

Required platform capabilities live under `app/core`, including organizations, users, organization memberships and, when implemented, authentication, tenancy, and module management. Organization is the tenant root, while User is a global platform identity. OrganizationMembership links Users to Organizations and stores the organization-specific role.

Future authentication identities remain separate from User (`User -> AuthIdentity`). Tenant membership follows `User -> OrganizationMembership -> Organization`; User does not contain `organization_id`.

Optional business capabilities such as fleet, clinic, documents, workflows, and analytics live under `app/modules`. Tenant-owned entities remain inside their business module, reference `organization_id`, and scope data access to that organization.

For local development, only PostgreSQL runs in Docker Compose. Python and Node.js run directly on the host for fast feedback and straightforward debugging.

Microservices, messaging, background-job infrastructure, and other scaling mechanisms are intentionally deferred until concrete product or operational needs justify them.
