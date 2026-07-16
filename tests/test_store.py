import hashlib
from datetime import datetime

from parts_parser.store import RunStore, hash_file


def test_site_config_round_trip_normalizes_domain_key(tmp_path):
    store = RunStore(root=tmp_path)
    config = {"product_selector": ".product", "part_number_field": "sku"}

    store.save_site_config("example.com", config)

    assert store.get_site_config("WWW.Example.COM") == config
    assert store.get_site_config("missing.example.com") is None


def test_pdf_cache_round_trip_and_miss(tmp_path):
    store = RunStore(root=tmp_path)
    file_hash = "abc123"
    parts = [{"part_number": "AB- 123", "description": "Synthetic fitting"}]

    store.save_pdf_cache(file_hash, parts)

    assert store.get_pdf_cache(file_hash) == parts
    assert store.get_pdf_cache("missing") is None


def test_web_cache_round_trip_normalizes_domain_and_preserves_complete(tmp_path):
    store = RunStore(root=tmp_path)
    payload = {
        "fetched_at": "2026-07-15T12:00:00+00:00",
        "crawl_seconds": 42.5,
        "complete": False,
        "parts": [{"part_no": "AB- 123", "attributes": {}}],
    }

    store.save_web_cache("WWW.Example.COM", payload)

    assert store.get_web_cache("example.com") == payload
    assert store.get_web_cache("missing.example.com") is None


def test_record_run_appends_records_with_distinct_ids_and_timestamps(tmp_path):
    store = RunStore(root=tmp_path)

    store.record_run({"source": "x"})
    store.record_run({"source": "x"})

    records = store.list_runs()
    assert len(records) == 2
    assert records[0]["source"] == "x"
    assert records[1]["source"] == "x"
    assert records[0]["id"] != records[1]["id"]
    assert all(record["id"] for record in records)
    assert all(datetime.fromisoformat(record["timestamp"]) for record in records)


def test_hash_file_returns_sha256_digest(tmp_path):
    contents = b"known synthetic fixture bytes\n"
    fixture_path = tmp_path / "fixture.bin"
    fixture_path.write_bytes(contents)

    assert hash_file(fixture_path) == hashlib.sha256(contents).hexdigest()
