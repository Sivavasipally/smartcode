You are rebuilding the complete Story Pointer application in this empty repository.

Primary specification:
- Read ./reacreate.md completely before creating or changing files.
- Treat it as the authoritative reconstruction and production contract.
- Implement both compatibility behavior and the production hardening explicitly
  described there.
- Do not silently simplify, omit, substitute, or reinterpret requirements.

Reference repository:
D:\vasipallys-github\strorypoitnerdifyagentswitheditor

The reference repository is READ-ONLY.
Never create, edit, delete, format, install packages into, or otherwise modify
anything in that directory. All writes must remain inside the current repository.

Core requirements:
1. Recreate every file listed in the repository tree in reacreate.md.
2. Preserve all wire contracts, SSE event ordering, provider integrations,
   Jira/spreadsheet normalization, telemetry, DSL editing, and responsive UI.
3. Enforce the invariant on backend, frontend, summary, Markdown export, and
   Excel export:
   never expose points without ok=true, an allowed point value,
   plain_language_why, and tldr.
4. Enforce the 13-point split rule exactly.
5. Recreate Summary and Details result views.
6. Recreate Markdown export and genuine four-sheet XLSX export.
7. Recreate the React Flow editor, including the dimensions-event blank-canvas
   fix, /editor/ Vite base path, responsive inspector, nested defaults,
   lossless metadata round trips, atomic DSL saves, and revision conflicts.
8. Keep graph execution behavior truthful. Do not claim the estimate endpoints
   invoke YAML graphs unless that execution path is actually implemented and tested.
9. Include production configuration validation, secret redaction, size limits,
   safe CORS, Excel formula-injection protection, Docker packaging, and tests.
10. Never place real provider, Jira, Phoenix, or DSL credentials in source files.

Working process:
- First audit reacreate.md and the read-only reference repository.
- Produce REBUILD_PLAN.md containing phases, files, dependencies, risks,
  acceptance criteria, and test commands.
- Produce REBUILD_STATUS.md and update it after every phase.
- Implement one phase at a time.
- Run focused tests after every phase.
- Do not continue past failing tests until they are fixed.
- Preserve exact API/event/model compatibility unless reacreate.md explicitly
  requires a production correction.
- Do not use placeholder implementations, TODOs, fake success responses,
  renamed CSV files pretending to be XLSX, or tests that only assert strings
  without exercising behavior.
- Mock paid LLM/Jira calls in automated tests.
- Do not make live provider calls during reconstruction.

Implementation phases:
1. Packaging, configuration, schemas, anchors, and domain invariant.
2. Provider adapters, normalization, retries, engine, SSE, and batch processing.
3. Manual, Jira, and spreadsheet ingestion.
4. Telemetry and Phoenix integration.
5. Excel export models, workbook generation, and export endpoint.
6. FastAPI routes, safe errors, limits, CORS, DSL persistence, and static mounts.
7. Estimator HTML/CSS/JavaScript, Summary/Details, Markdown and Excel exports.
8. React/Vite DSL editor and editor tests.
9. DSL reference graphs.
10. Docker, README, environment template, and production documentation.
11. Complete test, build, audit, and specification gap analysis.

After implementation:
- Run the complete Python suite.
- Run editor unit tests.
- Run the editor production build.
- Run npm audit.
- Run JavaScript syntax validation.
- Run git diff checks.
- Compare every heading and acceptance item in reacreate.md against the result.
- Write REBUILD_REPORT.md listing implemented requirements, test results,
  intentional differences, and any remaining production blockers.

Start by reading the complete specification and reference repository.
Then create REBUILD_PLAN.md. Do not write implementation code until the plan
covers every specification section.