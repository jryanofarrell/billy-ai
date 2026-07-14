from parts_parser.config import Settings, load_settings, save_settings


def test_settings_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(openai_api_key="saved-test-key", model="test-model")

    save_settings(settings)

    assert load_settings() == settings


def test_load_settings_returns_defaults_when_file_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert load_settings() == Settings()


def test_environment_api_key_overrides_file_value(monkeypatch, tmp_path):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    save_settings(Settings(openai_api_key="file-test-key", model="test-model"))
    monkeypatch.setenv("OPENAI_API_KEY", "environment-test-key")

    settings = load_settings()

    assert settings.openai_api_key == "environment-test-key"
    assert settings.model == "test-model"


def test_file_api_key_is_used_when_environment_value_is_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    save_settings(Settings(openai_api_key="file-test-key"))

    assert load_settings().openai_api_key == "file-test-key"
