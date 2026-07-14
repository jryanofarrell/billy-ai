import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "PartsParser"


@dataclass
class Settings:
    openai_api_key: str | None = None
    model: str = "gpt-5-mini"


def app_data_dir() -> Path:
    override = os.environ.get("PARTS_PARSER_DATA_DIR")
    path = Path(override) if override else Path(user_data_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load_settings() -> Settings:
    path = settings_path()
    if path.exists():
        with path.open(encoding="utf-8") as settings_file:
            stored_values = json.load(settings_file)
        settings = Settings(**stored_values)
    else:
        settings = Settings()

    environment_key = os.environ.get("OPENAI_API_KEY")
    if environment_key:
        settings.openai_api_key = environment_key

    return settings


def save_settings(settings: Settings) -> None:
    with settings_path().open("w", encoding="utf-8") as settings_file:
        json.dump(asdict(settings), settings_file, indent=2)
