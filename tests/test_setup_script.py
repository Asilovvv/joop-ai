"""deploy/setup.sh writes a .env that passes the launch check (DRY_RUN: no root, no Docker, no network)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from joop.config import settings_from_env
from joop.ops import launch_checks

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("openssl")), reason="needs bash and openssl")


def run_setup(tmp_path, **answers):
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    env = {"PATH": os.environ["PATH"], "DRY_RUN": "1", "JOOP_DIR": str(tmp_path), **answers}
    return subprocess.run(["bash", str(ROOT / "deploy" / "setup.sh")], env=env, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


def read_env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key] = value
    return values


def test_setup_writes_a_ready_env(tmp_path, monkeypatch, engine):
    r = run_setup(tmp_path, JOOP_DOMAIN="https://Joop.KG/", JOOP_ANTHROPIC_KEY="sk-ant-test-key", JOOP_PRICE_SOM="2900",
                  JOOP_FOUNDER_BOT_TOKEN="123456:ABC", JOOP_FOUNDER_CHAT_ID="42")
    assert r.returncode == 0, r.stderr
    env_file = tmp_path / ".env"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"  # secrets: only the owner of the file reads it
    values = read_env(env_file)
    assert values["DOMAIN"] == "joop.kg" and values["PUBLIC_BASE_URL"] == "https://joop.kg" and values["SECURE_COOKIES"] == "true"
    assert values["PRICE_SOM"] == "2900" and values["FOUNDER_CHAT_ID"] == "42" and len(values["OWNER_PASSWORD"]) >= 12
    assert len([line for line in env_file.read_text().splitlines() if line.startswith("SESSION_SECRET=")]) == 1

    for key in list(os.environ):
        if key in values:
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    checks = launch_checks(settings_from_env(), env=values)
    config = [c for c in checks if c.required and "база" not in c.name.lower() and "миграц" not in c.name.lower()]
    assert config and all(c.ok for c in config), [(c.name, c.detail) for c in config if not c.ok]
    assert next(c for c in checks if "OWNER_PASSWORD" in c.name).ok

    again = run_setup(tmp_path, JOOP_DOMAIN="other.kg", JOOP_ANTHROPIC_KEY="sk-ant-other")
    assert again.returncode == 0 and "оставляю" in again.stdout
    assert read_env(env_file)["SESSION_SECRET"] == values["SESSION_SECRET"]  # a second run keeps the secrets


def test_setup_refuses_wrong_answers(tmp_path):
    r = run_setup(tmp_path, JOOP_DOMAIN="not a domain", JOOP_ANTHROPIC_KEY="sk-ant-x")
    assert r.returncode != 0 and "не похоже на домен" in r.stderr
    r = run_setup(tmp_path, JOOP_DOMAIN="joop.kg", JOOP_ANTHROPIC_KEY="wrong")
    assert r.returncode != 0 and "sk-ant-" in r.stderr and "AIza" in r.stderr
    assert not (tmp_path / ".env").exists()


def test_setup_can_use_gemini_instead_of_anthropic(tmp_path, monkeypatch, engine):
    """The owner may start on Google Gemini (OpenAI-compatible endpoint) instead of Anthropic."""
    r = run_setup(tmp_path, JOOP_DOMAIN="joop.kg", JOOP_MODEL_KEY="AIzaSy-test-key", JOOP_GEMINI_MODEL="gemini-3.8-flash",
                  JOOP_PRICE_SOM="0", JOOP_FOUNDER_BOT_TOKEN="123456:ABC", JOOP_FOUNDER_CHAT_ID="42")
    assert r.returncode == 0, r.stderr
    assert "платный тариф" in r.stdout  # free tiers may use the conversations: said at setup, not only in the docs
    values = read_env(tmp_path / ".env")
    assert values["LLM_PROVIDER"] == "openai" and values["LLM_API_KEY"] == "AIzaSy-test-key"
    assert values["LLM_BASE_URL"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert values["JOOP_MODEL"] == "gemini-3.8-flash" and values["ANTHROPIC_API_KEY"] == ""
    for key in list(os.environ):
        if key in values:
            monkeypatch.delenv(key)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = settings_from_env()
    assert settings.llm_provider == "openai" and settings.model_key == "AIzaSy-test-key"
    checks = launch_checks(settings, env=values)
    assert next(c for c in checks if "LLM_API_KEY" in c.name).ok
