# billy-ai

AI tooling for Central Components, a plumbing-parts distributor running Epicor
P21 (Prophet 21). This repo is the umbrella for all AI products in that offering.

**Product #1 (current, contracted): the parts-catalog parser** — a local
desktop app for non-technical users that parses plumbing-parts websites and
catalog PDFs into Excel workbooks. The design doc lands at
`docs/PARSER_PLAN.md`; read it before any parser work. A second product (an
email-native order agent) is deferred indefinitely — do not build toward it.

## Status

The initial Python package scaffold is in place. Set up and check the project
from the repository root:

```sh
uv sync
uv run pytest
uv run ruff check .
```

Directory map:

- `src/parts_parser/` — package code: settings, LLM client, and run store
- `tests/` — pytest coverage for the scaffold
- `docs/` — product and architecture planning
- `.ai/rules/` — always-applicable project constraints
- `.ai/context/` — snapshots of the implementation for cold sessions
- `.ai/recipes/` — repeatable development procedures

This remains a greenfield product; future tickets that materially change an
area must update its context file in the same PR.

## Read first

- `.ai/rules/core.md` — always-applicable constraints; read before writing any code
- `.ai/recipes/ai-structure.md` — map of the `.ai/` system
