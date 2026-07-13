---
name: ai-structure
description: Map of the .ai/ system in billy-ai — what lives where and when to update it.
---

# The .ai/ system

- `rules/core.md` — constraints that always apply. Read before writing code.
- `context/<area>.md` — snapshot of what exists per area, for cold agent
  sessions. None exist yet (greenfield); the scaffold ticket creates
  `context/core.md`, and every ticket that materially changes an area updates
  its context file in the same PR.
- `recipes/<area>/<task>.md` — procedural how-to guides, one per recurring
  file type in the codebase. None exist yet; a recipe is created the first
  time a ticket adds a file of a new type, following `recipes/recipe.md`.
- `recipes/recipe.md` — how to author a recipe. Recipe-creation subtasks
  point here.

`CLAUDE.md` and `AGENTS.md` at the repo root carry identical bodies and both
point into this tree, so Claude Code and Codex CLI see the same world.
