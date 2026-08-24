# Handoff outline

Use repository evidence and include source paths for important architectural claims.

1. Snapshot metadata: date, branch, HEAD, clean/dirty state.
2. Product purpose and current stack.
3. Architecture overview.
4. Authentication, Organization tenancy, PlatformAdmin, and invitation boundaries.
5. Module Platform, Access Groups, authorization, and Analytics Contract.
6. Frontend architecture and current routes.
7. PostgreSQL schema and Alembic head.
8. Important current APIs.
9. Production modules and Analytics providers.
10. Security invariants.
11. Current validation/test evidence.
12. Important code and documentation paths.
13. Implemented milestones.
14. Documented contracts that are not yet products.
15. Intentionally deferred features.
16. Next planned work only when current repository documentation supports it.

Within the document, label facts so a reader can distinguish:

- **Implemented and verified**: supported by current code/tests or newly run validation.
- **Documented contract**: specified for future implementations but not itself a user feature.
- **Planned/deferred**: absent today and explicitly deferred or supported as next work by current
  documentation.

Do not infer roadmap items from old conversations, filenames, examples, or fake test modules.
