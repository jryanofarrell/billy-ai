import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from parts_parser.config import app_data_dir

_HASH_CHUNK_SIZE = 1024 * 1024


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        while chunk := source_file.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _domain_key(domain: str) -> str:
    normalized = domain.lower()
    if normalized.startswith("www."):
        normalized = normalized[4:]
    return re.sub(r"[^a-z0-9.-]", "_", normalized)


class RunStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else app_data_dir()
        self.site_configs_dir = self.root / "site_configs"
        self.pdf_cache_dir = self.root / "pdf_cache"
        self.site_configs_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_cache_dir.mkdir(parents=True, exist_ok=True)
        self.runs_path = self.root / "runs.jsonl"

    def get_site_config(self, domain: str) -> dict | None:
        path = self.site_configs_dir / f"{_domain_key(domain)}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as config_file:
            return json.load(config_file)

    def save_site_config(self, domain: str, config: dict) -> None:
        path = self.site_configs_dir / f"{_domain_key(domain)}.json"
        with path.open("w", encoding="utf-8") as config_file:
            json.dump(config, config_file, indent=2)

    def get_pdf_cache(self, file_hash: str) -> dict | list | None:
        path = self.pdf_cache_dir / f"{file_hash}.json"
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as cache_file:
            return json.load(cache_file)

    def save_pdf_cache(self, file_hash: str, parts: dict | list) -> None:
        path = self.pdf_cache_dir / f"{file_hash}.json"
        with path.open("w", encoding="utf-8") as cache_file:
            json.dump(parts, cache_file, indent=2)

    def record_run(self, record: dict) -> str:
        run_id = uuid4().hex
        stored_record = {
            **record,
            "id": run_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        with self.runs_path.open("a", encoding="utf-8") as runs_file:
            json.dump(stored_record, runs_file)
            runs_file.write("\n")
        return run_id

    def list_runs(self) -> list[dict]:
        if not self.runs_path.exists():
            return []
        with self.runs_path.open(encoding="utf-8") as runs_file:
            return [json.loads(line) for line in runs_file if line.strip()]
