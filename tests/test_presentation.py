from pathlib import Path

from tools.prompt_slides import build, deck_page, prompts_page, render

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_presentation_has_no_company_name():
    for path in DOCS.glob("*.html"):
        assert "caldova" not in path.read_text(encoding="utf-8").casefold(), path.name


def test_generated_deck_matches_the_sources_and_business_first_order():
    slides = build()
    deck = deck_page(slides)
    assert (DOCS / "index.html").read_text(encoding="utf-8") == deck
    assert (DOCS / "prompts.html").read_text(encoding="utf-8") == prompts_page(slides)
    assert 'const deckSeq = [{ frame: "intro" }, { frame: "agents" }, { mode: "tech" }];' in deck


def test_display_aliases_preserve_policy_and_agent_instructions():
    source = "Caldova's agent applies Caldova Repair Policy: does NOT comply with Caldova RP-02."
    assert render(source) == "the insurer&#x27;s agent applies Repair Policy: does NOT comply with RP-02."
