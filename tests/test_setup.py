from joop.setup import render_env, valid_anthropic_key, valid_telegram_token, write_env


def test_token_validation():
    assert valid_telegram_token("123456789:AAH_abcdefghijklmnopqrstuvwxyz012345")
    assert not valid_telegram_token("not-a-token")
    assert not valid_telegram_token("123:short")


def test_key_validation():
    assert valid_anthropic_key("sk-ant-api03-" + "x" * 30)
    assert not valid_anthropic_key("abc")


def test_render_env_has_all_settings():
    env = render_env(" 1:tok ", "sk-key", "42")
    assert "TELEGRAM_BOT_TOKEN=1:tok\n" in env
    assert "ANTHROPIC_API_KEY=sk-key\n" in env
    assert "OWNER_CHAT_ID=42\n" in env
    assert "BUSINESS_FILE=business.yaml" in env


def test_write_env_backs_up_existing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OLD=1\n")
    write_env(p, "NEW=1\n")
    assert p.read_text() == "NEW=1\n"
    assert (tmp_path / ".env.bak").read_text() == "OLD=1\n"
