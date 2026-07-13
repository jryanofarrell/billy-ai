---
name: recipe
description: How to author a .ai/recipes/<area>/<task>.md recipe in this repo.
---

# Authoring a recipe

A recipe teaches an agent — including a small local model — how to write or
modify one recurring file type in this codebase. Subtasks point at recipes,
not at example files.

## Naming

Name the recipe after what the file IS in the codebase's own vocabulary:
pluralized directory → singular recipe (`services/` → `service.md`); a
single-purpose file in a generic directory is named by its role; the
framework's own term wins when no directory signals it. Never rename based
on contents (routers contain endpoints; the recipe is still `router.md`).

## Required shape

Frontmatter with `name` and `description`, then:

1. **Where** — path conventions for files of this type.
2. **Shape** — imports, base classes, decorators, structural rules.
3. **Conventions** — the non-obvious rules: naming, required fields,
   ordering. Every line actionable; no platitudes.
4. **Reference** — one worked pointer to a real file in the repo so the
   pattern can be seen in context.

## Rules

- Describe the **pattern**, never a single instance. "Copy X and change Y"
  is not a recipe.
- Write for mechanical execution: a small model following the recipe plus a
  subtask's specifics (exact names, signatures, pseudocode) should need zero
  design decisions.
- 30–80 lines. If a section would be empty, omit it. If the type has no
  real pattern yet, don't write the recipe.
- When a ticket changes the pattern, updating the recipe is part of that
  ticket, same PR.
