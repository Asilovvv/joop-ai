"""eval/prompt_hashes.py: comparing two sets of prompt hashes."""

from eval.prompt_hashes import _TOKEN, compare


def test_compare_names_the_packs_whose_prompts_changed():
    a = {"dental": ["a", "b"], "beauty": ["c"]}
    assert compare(a, dict(a)) == []
    assert compare(a, {"dental": ["a", "x"], "beauty": ["c"]}) == ["dental: 1 of 2 prompts changed"]
    assert compare(a, {"dental": ["a"], "beauty": ["c"]}) == ["dental: 2 prompts → 1"]


def test_random_test_links_are_not_a_change():
    assert _TOKEN.sub("/t/TOKEN", "ссылка https://x/t/30af0431eff668b4") == "ссылка https://x/t/TOKEN"
