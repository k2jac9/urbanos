"""Digest label cleaning — strip the stray DineSafe 'None' street-direction token.

The raw DineSafe label embeds a literal "None" (e.g. "142 Parliament St None
M5A 2Z1"); the postal code IS present after it. Left in, the briefing LLM
misreads the token as a missing postal code. The cleaner removes the standalone
token while keeping the street number and postal code intact.

Offline-safe — uses stub LLMs, never a real network call.
"""
import urbanos.risk.agents.digest as digest
from urbanos.risk.agents.digest import _addr, _clean_label, city_digest


def test_cleaner_removes_standalone_none_token():
    cleaned = _clean_label("142 Parliament St None M5A 2Z1")
    assert "None" not in cleaned
    # Postal code and street number survive.
    assert "M5A 2Z1" in cleaned
    assert "142" in cleaned
    assert "Parliament St" in cleaned
    assert cleaned == "142 Parliament St M5A 2Z1"


def test_cleaner_is_case_insensitive():
    assert "NONE" not in _clean_label("500 Bloor St W NONE M6G 1K5")
    assert _clean_label("500 Bloor St W NONE M6G 1K5") == "500 Bloor St W M6G 1K5"


def test_cleaner_only_strips_whole_word_not_substrings():
    # "Noneworth" / "Nonesuch" must survive — only the standalone word goes.
    assert _clean_label("12 Nonesuch Ave M4M 1A1") == "12 Nonesuch Ave M4M 1A1"
    assert _clean_label("88 Anonemous Rd") == "88 Anonemous Rd"


def test_cleaner_leaves_clean_labels_unchanged():
    assert _clean_label("100 Queen St W") == "100 Queen St W"
    assert _clean_label("500 Bloor St W M6G 1K5") == "500 Bloor St W M6G 1K5"


def test_cleaner_handles_empty_and_collapses_whitespace():
    assert _clean_label("") == ""
    assert _clean_label("None None") == ""
    assert _clean_label("142  Parliament St   None  M5A 2Z1") == "142 Parliament St M5A 2Z1"


def test_addr_applies_cleaner():
    assert _addr({"label": "142 Parliament St None M5A 2Z1"}) == "142 Parliament St M5A 2Z1"
    assert _addr({"address": "142 Parliament St None M5A 2Z1"}) == "142 Parliament St M5A 2Z1"
    assert _addr({}) == "?"


class _CapturingLLM:
    """Records the user prompt passed to the batch LLM."""

    def __init__(self, reply: str = "BRIEFING") -> None:
        self.user = None
        self.reply = reply

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        self.user = user
        return self.reply


class _BoomLLM:
    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        raise RuntimeError("no model")


def _reset_cache() -> None:
    with digest._lock:
        digest._cache.clear()


def test_prompt_lines_never_show_the_stray_none_token():
    _reset_cache()
    ranked = [{"label": "142 Parliament St None M5A 2Z1",
               "risk_safety": 0.7, "risk_activity": 0.2}]
    llm = _CapturingLLM()
    city_digest(ranked, llm=llm)
    assert "None" not in llm.user
    assert "142 Parliament St M5A 2Z1" in llm.user


def test_fallback_line_never_shows_the_stray_none_token():
    _reset_cache()
    ranked = [{"label": "142 Parliament St None M5A 2Z1",
               "risk_safety": 0.7, "risk_activity": 0.2}]
    out = city_digest(ranked, llm=_BoomLLM())
    assert "None M5A" not in out
    assert "142 Parliament St M5A 2Z1" in out
