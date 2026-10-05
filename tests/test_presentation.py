from pathlib import Path
import re

from tools.prompt_slides import LASER_CSS, LASER_JS, build, deck_page, prompts_page, render
from tools.render_media_story import render_media_story

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_presentation_has_no_company_name():
    for path in DOCS.glob("*.html"):
        visible_text = re.sub(r"<[^>]+>", "", path.read_text(encoding="utf-8"))
        assert "caldova" not in visible_text.casefold(), path.name


def test_generated_deck_matches_the_sources_and_requested_opening_order():
    slides = build()
    deck = deck_page(slides)
    assert (DOCS / "index.html").read_text(encoding="utf-8") == deck
    assert (DOCS / "prompts.html").read_text(encoding="utf-8") == prompts_page(slides)
    assert 'const deckSeq = [{ frame: "intro" }, { mode: "biz" }, { mode: "tech" }, { frame: "agents" }];' in deck
    assert 'addEventListener("click"' not in deck
    assert 'addEventListener("click"' not in prompts_page(slides)
    intro = (DOCS / "intro.html").read_text(encoding="utf-8")
    assert "Repair policy:" not in intro
    assert "Business goal:" not in intro


def test_display_aliases_preserve_policy_and_agent_instructions():
    source = "Caldova's agent applies Caldova Repair Policy: does NOT comply with Caldova RP-02."
    assert render(source) == "the insurer&#x27;s agent applies Repair Policy: does NOT comply with RP-02."


def test_opening_slides_have_the_requested_copy():
    intro = (DOCS / "intro.html").read_text(encoding="utf-8")
    assert "Assess the repair needs and protect personal details. Prepare quotes request." in intro
    for removed in ("Three garages", 'class="step approval"', "The customer gets an update", "The insurance operation"):
        assert removed not in intro
    for name in ("flow.html", "flow-animated.html", "index.html"):
        page = (DOCS / name).read_text(encoding="utf-8")
        assert "repair centers" in page
        assert "Fastest + cheapest + compliant with policies" in page
        assert '<span><i style="background:var(--studio)"></i>Work IQ</span>' in page
        for removed in (
            "three repair centres", "Fastest + cheapest rejected",
            "Keeps Copilot's pick", "customer sees the next step",
            "Case events trigger the agents", "Nothing is booked without step 7",
            "bold border = AI agent",
        ):
            assert removed not in page


def test_laser_pointer_is_in_both_generated_presentations():
    slides = build()
    for page in (deck_page(slides), prompts_page(slides)):
        assert LASER_CSS in page
        assert LASER_JS in page
        assert page.count(LASER_JS) == 1


def test_media_story_renders_images_tables_anchors_and_public_navigation():
    source = (DOCS / "mediastory.md").read_text(encoding="utf-8")
    rendered = render_media_story(source)
    assert (DOCS / "mediastory.html").read_text(encoding="utf-8") == rendered
    assert rendered.count("<img ") == 10
    assert rendered.count("<table>") == 4
    assert 'id="capture-register"' in rendered
    assert 'href="mediastory.md" download' in rendered
    assert 'href="storyline.md"' not in rendered
    assert 'href="implementation.md"' not in rendered
    for image in re.findall(r'<img[^>]+src="([^"]+)"', rendered):
        assert (DOCS / image).is_file(), image
