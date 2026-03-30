## 1. Fix schema reference (playbook -> galileo)

- [ ] 1.1 Update `backend/app/db/client_lookup.py`: change SQL query `FROM playbook.fuzzy_client` to `FROM galileo.fuzzy_client`, update module docstring and function docstring
- [ ] 1.2 Update `backend/app/db/_schema.py`: change index creation from `ON playbook.fuzzy_client` to `ON galileo.fuzzy_client`, update health check to validate `galileo.fuzzy_client` instead of `playbook.fuzzy_client`
- [ ] 1.3 Update `backend/app/agent/client_resolver.py`: change LLM prompt context string from `playbook.fuzzy_client` to `galileo.fuzzy_client`
- [ ] 1.4 Update `backend/tests/test_client_lookup_integration.py`: change seed INSERT and cleanup DELETE to target `galileo.fuzzy_client`

## 2. Fix companies field type (str -> list[str])

- [ ] 2.1 Update `backend/app/models/client_lookup.py`: change `CandidateResult.companies` from `str | None` to `list[str] | None`
- [ ] 2.2 Update `backend/app/db/client_lookup.py`: ensure `search_fuzzy_client()` passes `row["companies"]` correctly (asyncpg returns `text[]` as `list[str]` natively; remove the `or None` coercion that treats empty list as None)
- [ ] 2.3 Update `backend/app/agent/client_resolver.py` `_build_user_prompt()`: join companies list with `", "` for display (e.g., `", ".join(c.companies) if c.companies else "none listed"`)
- [ ] 2.4 Update `backend/app/agent/tools.py` `lookup_client()`: if candidate companies are displayed in output, join list for display

## 3. Add lookup_client to agent system prompt

- [ ] 3.1 Add `lookup_client` to the "You have access to" tool list in `backend/app/agent/agent.py` SYSTEM_PROMPT with description: "resolve a person's name to a GWM client ID via fuzzy matching"
- [ ] 3.2 Add `query_knowledge_graph` to the tool list if also missing (it was omitted alongside lookup_client)
- [ ] 3.3 Add a "Client Lookup Queries" section to the system prompt explaining: (a) `lookup_client` is single-name per call, (b) for multi-person queries call it once per person, (c) batch calls in parallel like other tools, (d) research the list of people first then call lookup_client for each

## 4. Tests and validation

- [ ] 4.1 Run existing unit tests for client_lookup to ensure schema change doesn't break mocked tests
- [ ] 4.2 Run existing unit tests for client_resolver to ensure companies type change doesn't break
- [ ] 4.3 Verify ruff linting passes on all modified files
- [ ] 4.4 Review that no other files reference `playbook.fuzzy_client` in live code (grep verification)
