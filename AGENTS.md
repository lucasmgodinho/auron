# Project guidelines

- Prefer simple solutions over premature abstractions.
- The backend follows a modular monolith direction; keep business modules isolated when introduced.
- Business logic must not live inside FastAPI routers.
- Add dependencies only for a concrete current need.
- Do not add infrastructure for hypothetical scalability problems.
- Create abstractions only after a real use case exists.
- Every feature needs appropriate tests.
- Apply all database schema changes through Alembic migrations.
- Use `Decimal`, never `float`, for future monetary values.
- Future tenant-owned data must be scoped to an organization; multi-tenancy is not part of the current foundation.
- Do not modify unrelated parts of the project.
- Run relevant validation commands before declaring work complete.

