---
name: module
description: How to write a Python module in the parts-parser package.
---

# Writing a Python module

## Where

- Place modules under `src/parts_parser/<area>/`, using the package area that
  owns the behavior.
- Keep one concern per file; split unrelated data shapes or behavior into
  separate modules in the same area.

## Shape

- Add type hints to every public function's parameters and return value.
- Represent public data shapes with `@dataclass`; do not expose dictionaries
  as public interfaces.
- Define `logger = logging.getLogger(__name__)` at module level in modules
  that log.
- Use absolute package imports, such as
  `from parts_parser.config import Settings`.
- Import provider SDKs such as `openai` or a future `anthropic` only in
  `src/parts_parser/llm.py`; other modules call the provider-agnostic LLM
  interface.
- Define an area-specific `Error` subclass of `Exception` for failures that
  callers need to handle.

## Conventions

- Give user-facing exceptions plain-language messages that tell a
  non-technical user what went wrong and what they can do next.
- Never include stack-trace terminology, implementation details, secret
  values, or credentials in user-facing exception messages.
- Read secrets from environment variables or gitignored local settings; never
  place keys or tokens in source code, defaults, fixtures, or log messages.
- Resolve application and user-data locations through configuration helpers;
  never hard-code developer-machine or other local filesystem paths.
- Preserve source part numbers character-for-character in output-facing data;
  keep any normalization confined to matching logic.
- Keep deterministic volume work outside the LLM boundary; do not add provider
  calls inside per-part processing loops.

## Reference

See `src/parts_parser/config.py` for the package's module structure, typed
public interfaces, data shapes, imports, and user-facing error conventions.
