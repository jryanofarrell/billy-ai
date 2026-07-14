---
name: testing
description: How to write pytest tests for the parts-parser package.
---

# Writing tests

## Where

- Place tests under `tests/`.
- Name each test file `tests/test_<module>.py`, where `<module>` matches the
  source module name being tested.
- Put recorded or synthetic external-service data under `tests/fixtures/`.
- Keep fixture names descriptive of the scenario they represent; never place
  secrets, customer data, pricing, or real parsed output in fixtures.

## Shape

- Write tests with `pytest` and plain `assert` statements.
- Import the public functions and types under test from `parts_parser` package
  modules rather than reaching through private implementation details.
- Name tests `test_<behavior>` so the expected observable behavior is clear
  from the test name.
- Use pytest fixtures for reusable setup and keep scenario-specific setup in
  the test that consumes it.
- Use the built-in `tmp_path` fixture for every test that reads or writes the
  filesystem, and pass paths derived from it into application APIs.
- Implement fake LLM clients with the same `complete_json` signature as the
  provider-agnostic client and return canned dictionaries appropriate to the
  scenario.

## Conventions

- Never read from or write to the real application-data directory in tests.
- Never make network requests in tests; replace external services with fakes
  backed by recorded or synthetic fixtures from `tests/fixtures/`.
- Prefer synthetic fixture content. If recorded content is necessary, remove
  credentials, customer identifiers, part lists, pricing, and other private
  data before committing it.
- Exercise behavior through public interfaces and assert on returned values,
  persisted data, raised exception types, and user-facing error messages.
- Assert preserved source part numbers character-for-character whenever a
  test covers parsing, storage, or workbook output.
- Do not assert on log output; logs are diagnostic implementation details, not
  the behavior contract.
- Keep canned LLM responses deterministic and local; do not require an API
  key, provider SDK response object, or provider-specific client in a test.
- Cover success and expected failure paths without depending on test order or
  files created by another test.

## Reference

See `tests/test_store.py` for filesystem isolation with `tmp_path`, public-API
behavior assertions, and round-trip persistence tests.
