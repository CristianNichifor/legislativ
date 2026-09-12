# End-to-End User Flows

Run:

```bash
uv run python -m scripts.e2e_user_flows --json
uv run pytest -q tests/test_e2e_user_flows.py
```

The contract tracks whether the app exposes the flows a real user needs:

- public app to local private workspace
- public dataset update, activation and rollback
- dossier to manual note to structured proposal
- CELEX import/search to EU risk context
- rule candidate to reviewed draft to deterministic rule check
- acceptance dashboard to remaining gaps

`ready` means the app surface and backing route/module are wired. `partial` means the
surface exists but the current implementation still has a declared blocker, such as missing
official CELEX text in the pilot data or only one deterministic law-as-code check family.

This is a wiring and usability-flow contract. It does not claim legal accuracy, source
freshness or reviewer acceptance.
