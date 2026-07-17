---
name: platform-tier
description: How to write a platform-specific web parsing module under src/parts_parser/web/<platform>.py.
---

# Platform-tier module

## Where

One file per platform: `src/parts_parser/web/<platform>.py` (e.g. `insite.py`, `magento.py`).
No subpackages. The filename is the platform's common short name, lowercase.

## Shape

```python
from collections.abc import Iterator
from typing import Any

from parts_parser.models import PartRecord
from parts_parser.web.session import WebError
```

Five required public functions, in this order:

**`detect(session: Any, base: str) -> bool`**
Verifies real catalog data exists — not a bare ping. Makes one lightweight
API/GraphQL call that would only succeed on this platform with real products or
categories present. Catches `WebError` and returns `False`; no other exception
escapes to the caller.

**`get_category_tree(session: Any, base: str) -> list[dict]`**
Fetches the full nested category hierarchy in one call. Returns a list of
top-level category dicts; each node may contain a children/subcategory list
under a platform-specific key.

**`iter_leaf_categories(tree: list[dict]) -> Iterator[tuple[list[str], dict]]`**
Walks the tree recursively. Yields `(name_path, node)` for leaves only (nodes
with no children). `name_path` is a `list[str]` built from the root down,
using the node's display-name field at each level. Never yields interior nodes.

**`list_category_products(session: Any, base: str, category_id: str) -> Iterator[dict]`**
Paginates through all pages for the given category, yielding one raw product
dict per product. Uses the platform's native pagination fields (page number or
cursor). Stops when the last page is exhausted.

**`product_to_record(product: dict, name_path: list[str]) -> PartRecord`**
Maps the platform's native field names to `PartRecord`. Part-number field →
`part_no` verbatim (no normalization). Display-name field → `description`.
`name_path[0]` → `category`, `name_path[1]` → `subcategory`,
`" / ".join(name_path[2:])` → `series` (empty string when absent).
Attribute extraction: for platforms with uniform attribute schemas, extract
inline; for platforms with non-uniform schemas, pass pre-discovered selectors
to `generic.parse_product_page` — no new parsing logic here.

## Conventions

- `detect` must verify real catalog data, not just a reachable endpoint. A 200
  from `/graphql` means nothing; a well-formed `categoryList` array does.
- No per-product LLM calls, ever. If attribute schemas vary across sites,
  make exactly one LLM call per site via `discovery.py`'s existing prompt to
  get selectors, then reuse `generic.py`'s `parse_product_page` for every
  product — do not invent new attribute-parsing logic.
- `product_to_record` must preserve `part_no` character-for-character from the
  source field. No case folding, no dash normalization.
- Register the platform in `pipeline.py`'s `resolve_site_config`: check it
  after all higher-priority platforms and before AI-driven generic discovery.
  Order is fixed and must not be changed without updating this recipe.
- The crawl entry point is `collect_<platform>_crawl(session, base, ...) ->
  Iterator[tuple[str, list[PartRecord]]]` — one tuple per category, yielding
  as categories complete so `run_web`'s partial-results handling works without
  changes.

## Reference

`src/parts_parser/web/insite.py` — complete worked example: REST-based detect,
flat category tree with recursive leaf walk, paginated product listing, and
`product_to_record` with the `name_path` split. Magento variant follows the
same shape using GraphQL instead of REST; see `src/parts_parser/web/magento.py`.
