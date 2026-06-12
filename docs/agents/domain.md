# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This is a single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-shopify-graphql-admin-api.md
│   ├── 0002-python-fastapi-connector.md
│   └── 0003-fingerprint-as-content-hash.md
└── ...
```

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the project glossary.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If referenced files don't exist yet for a given term/decision, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (Shopify GraphQL Admin API) — but worth reopening because…_
