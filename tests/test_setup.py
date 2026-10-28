from joop.setup import (
    check_env,
    main,
    read_env,
    render_env,
    valid_anthropic_key,
    valid_chat_id,
    valid_telegram_token,
    write_env,
)

GOOD_TOKEN = "123456789:AAH_abcdefghijklmnopqrstuvwxyz012345"
GOOD_KEY = "sk-ant-api03-" + "x" * 90


def test_token_validation():
    assert valid_telegram_token(GOOD_TOKEN)
    assert not valid_telegram_token("not-a-token")
    assert not valid_telegram_token("123:short")


def test_key_validation():
    assert valid_anthropic_key(GOOD_KEY)
    assert valid_anthropic_key("sk-ant-usr01-" + "x" * 90)  # personal key from the new Console
    assert not valid_anthropic_key("abc")
    assert not valid_anthropic_key("sk-proj-" + "x" * 90)  # another provider's key
    assert not valid_anthropic_key("sk-ant-" + "x" * 50 + " y")  # whitespace from a bad paste


def test_chat_id_validation():
    assert valid_chat_id("1411520326")
    assert valid_chat_id("")
    assert not valid_chat_id("abc")


def test_render_and_read_env_roundtrip(tmp_path):
    p = tmp_path / ".env"
    p.write_text(render_env(GOOD_TOKEN, GOOD_KEY, "42"))
    values = read_env(p)
    assert values["TELEGRAM_BOT_TOKEN"] == GOOD_TOKEN
    assert values["OWNER_CHAT_ID"] == "42"
    assert check_env(values) == []


def test_check_env_reports_bad_key():
    problems = check_env({"TELEGRAM_BOT_TOKEN": GOOD_TOKEN, "ANTHROPIC_API_KEY": "sk-proj-" + "x" * 90})
    assert len(problems) == 1 and "ANTHROPIC_API_KEY" in problems[0]


def test_check_flag_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["--check"]) == 1  # no .env
    (tmp_path / ".env").write_text(render_env(GOOD_TOKEN, GOOD_KEY))
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert GOOD_KEY not in out and GOOD_TOKEN not in out  # secrets never printed


def test_write_env_backs_up_existing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OLD=1\n")
    write_env(p, "NEW=1\n")
    assert p.read_text() == "NEW=1\n"
    assert (tmp_path / ".env.bak").read_text() == "OLD=1\n"
