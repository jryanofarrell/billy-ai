# billy-ai

AI tooling for Central Components, a plumbing-parts distributor running Epicor
P21 (Prophet 21). This repo is the umbrella for all AI products in that offering.

**Product #1 (current, contracted): the parts-catalog parser** — a local
desktop app for non-technical users that parses plumbing-parts websites and
catalog PDFs into Excel workbooks. The design doc lands at
`docs/PARSER_PLAN.md`; read it before any parser work. A second product (an
email-native order agent) is deferred indefinitely — do not build toward it.

## Status

Greenfield. No code yet — the planning doc and the first scaffold ticket
define the stack and layout. Whoever lands the scaffold ticket must update
this file (build/run commands, directory map) and create
`.ai/context/core.md` in the same PR.

## Read first

- `.ai/rules/core.md` — always-applicable constraints; read before writing any code
- `.ai/recipes/ai-structure.md` — map of the `.ai/` system
