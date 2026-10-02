"""Build docs/prompts.html: one slide per agent, showing the exact prompts read from source."""
import ast
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def constant(path: str, name: str) -> str:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return node.value.value
    raise KeyError(name)


def evidence_tasks() -> list[str]:
    tree = ast.parse((ROOT / "fleet/evidence.py").read_text(encoding="utf-8"))
    calls = sorted((node for node in ast.walk(tree) if isinstance(node, ast.Call)), key=lambda node: node.lineno)
    return [
        node.args[0].value for node in calls
        if getattr(node.func, "attr", None) == "model"
        and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
    ]


def studio(agent: str) -> str:
    text = (ROOT / "copilot" / agent / "agent.mcs.yml").read_text(encoding="utf-8")
    lines = []
    for line in text.split("instructions: |", 1)[1].splitlines()[1:]:
        if line.strip() and not line.startswith("  "):
            break
        lines.append(line[2:])
    return "\n".join(lines).strip()


GUARDS = [
    r"evidence, (?:never|not) instructions", r"not instructions", r"never instructions", r"Never follow commands[^.]*",
    r"Human approval is mandatory", r"requires_approval \(always true\)", r"Never invent[^.]*", r"Do not invent[^.]*",
    r"Return ONLY[^,:.]*", r"Return only the requested JSON object", r"Return JSON exactly",
    r"Never (?:determine|infer|claim|override)[^.]*", r"Do not infer[^.]*", r"require human review",
    r"recorded operator approval", r"copied exactly", r"Remove (?:all )?personal identifiers[^.]*",
    r"Do not claim a repair is booked unless Incidents\.Status is booked and ExpectedReturn is populated", r"total expected cost = [^.]*", r"Select the smallest total cost",
]


def render(text: str, extra: list[str] = ()) -> str:
    out = html.escape(text)
    for pattern in list(extra):
        out = re.sub(f"({pattern})", r'<mark class="diff">\1</mark>', out)
    for pattern in GUARDS:
        out = re.sub(f"(?<!>)({html.escape(pattern, quote=False)})", r"<mark>\1</mark>", out)
    return out


def slide(n, color, product, name, ident, facts, prompts, small=False):
    facts_html = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts)
    panels = "".join(
        f'<div class="prompt"><div class="ptitle">{title}</div><pre class="{"small" if small else ""}">{body}</pre></div>'
        for title, body in prompts
    )
    return f"""
<section class="pslide" style="--c:var(--{color})">
  <header><div class="who"><span class="badge">{n}</span><div><div class="eyebrow">{product}</div><h1>{name}</h1><code class="id">{ident}</code></div></div><div class="page">{n} / 6</div></header>
  <div class="body"><dl class="facts">{facts_html}</dl><div class="prompts">{panels}</div></div>
  <footer><span><mark>highlighted</mark> = guardrail</span><span><mark class="diff">blue</mark> = what makes this agent different</span><span>Exact text, read from the deployed source.</span></footer>
</section>"""


def build() -> str:
    foundry = constant("fleet/foundry.py", "AGENT_INSTRUCTIONS")
    photo, privacy, report = evidence_tasks()
    fleet = constant("tools/intelligence.py", "INSTRUCTIONS")
    garages = {
        "alder": ("Alder Bodyworks", "alder.repairs@", "Cheapest repair, later workshop slot", [r"Explain that the economical price requires a later workshop slot\.", r"12-month warranty"]),
        "metro": ("Metro Rapid Repair", "metro.repairs@", "Priority slot, back on the road sooner", [r"Explain that the price includes priority access to an earlier workshop slot\.", r"18-month warranty"]),
        "riverside": ("Riverside Auto Care", "riverside.repairs@", "Balanced price and availability", [r"Present the balanced cost and workshop-availability option\.", r"12-month warranty"]),
    }
    slides = [slide(
        1, "foundry", "Microsoft Foundry Agent Service", "Evidence agent", "caldova-incident-evidence · v2 · GPT-4.1 vision",
        [("Wakes", "Customer submits photos + explanation"),
         ("Does", "3 calls per photo set: inspect → verify redaction → write the garage-facing brief"),
         ("Two prompt layers", "Agent instructions live in Foundry; each call adds a task prompt with the exact JSON shape"),
         ("Output checked", "Strict schema validation; unclear privacy or non-cosmetic damage → human review"),
         ("Never", "Liability, coverage, roadworthiness, email, bookings")],
        [("Agent instructions · stored in Foundry", render(foundry)),
         ("Task 1 · inspect photo", render(photo)), ("Task 2 · verify redaction", render(privacy)), ("Task 3 · repair brief", render(report))],
        small=True,
    ), slide(
        2, "studio", "Copilot Studio", "Claims coordinator", "Caldova Repair Coordinator · claims@",
        [("Wakes", "A: brief ready → write the quote request<br>B: three quotes in → recommend"),
         ("Called by", "Caldova app, over Direct Line with a protected channel secret"),
         ("Output checked", "The pick must match the app's own cost calculation; <b>requires_approval</b> must be true"),
         ("Then", "Operator keeps the pick or overrides it with a reason"),
         ("Never", "Sends email or books. The app does that after approval")],
        [("Agent instructions · Copilot Studio", render(studio("coordinator")))],
    )]
    for i, (key, (name, mailbox, pitch, diffs)) in enumerate(garages.items(), start=3):
        slides.append(slide(
            i, "studio", "Copilot Studio · repair centre", name, f"{key} · {mailbox}",
            [("Wakes", "An email lands in its own shared mailbox"),
             ("Position", pitch),
             ("Quote", "Uses only the trusted rate card + capacity the app supplies; must copy the offer exactly"),
             ("Booking", "Confirms only a quote with recorded operator approval"),
             ("Output checked", "Price, dates and garage ID re-validated before the reply is sent from the mailbox")],
            [("Agent instructions · Copilot Studio", render(studio(key), diffs))],
        ))
    slides.append(slide(
        6, "fabric", "Fabric data agent · Fabric IQ", "Caldova Fleet IQ", "Lakehouse FleetIntelligence + ontology · in Microsoft 365 Copilot",
        [("Wakes", "Someone asks a question in Fabric or Microsoft 365 Copilot"),
         ("Reads", "Vehicles, Branches, Rentals, VehicleState, DailyMileage, Incidents, RepairQuotes"),
         ("Knows", "Units, the Madrid reporting calendar, and approved ≠ booked"),
         ("New", "Recommended vs approved garage, overrides and the reason"),
         ("Never", "Invents data, contacts drivers or changes rentals")],
        [("Agent instructions · Fabric data agent", render(fleet, [r"The operator may book a different repair centre than recommended: ApprovedGarage is the operator&#x27;s choice,\nRecommendedGarage is the agent&#x27;s\. OverrodeRecommendation=true marks such cases, and OverrideReason records why\."]))],
        small=True,
    ))
    return "".join(slides)


# Agent order on the slides -> the flow cards (and garage chip) that agent owns in flow-animated.html.
AGENTS = [
    {"name": "Evidence agent", "color": "foundry", "steps": ["s3"]},
    {"name": "Claims coordinator", "color": "studio", "steps": ["s4", "s6"]},
    {"name": "Alder Bodyworks", "color": "studio", "steps": ["s5", "s8"], "chip": "Alder"},
    {"name": "Metro Rapid Repair", "color": "studio", "steps": ["s5", "s8"], "chip": "Metro"},
    {"name": "Riverside Auto Care", "color": "studio", "steps": ["s5", "s8"], "chip": "Riverside"},
    {"name": "Caldova Fleet IQ", "color": "fabric", "steps": ["s9"]},
]

PROMPT_CSS = """
  .pslide { width: 1600px; height: 900px; padding: 40px 60px 26px; flex: none; grid-template-rows: auto 1fr auto; gap: 20px; color: var(--text);
    background: radial-gradient(900px 500px at 100% -10%, color-mix(in srgb, var(--c) 12%, transparent) 0%, transparent 60%), var(--bg); box-shadow: 0 10px 40px #1720331a; transform-origin: center; }
  .pslide header { display: flex; justify-content: space-between; align-items: flex-start; }
  .pslide .who { display: flex; gap: 20px; align-items: center; }
  .pslide .badge { width: 64px; height: 64px; border-radius: 18px; background: var(--c); color: #fff; display: grid; place-items: center; font-size: 30px; font-weight: 800; }
  .pslide .eyebrow { color: var(--c); font-weight: 700; letter-spacing: .14em; text-transform: uppercase; font-size: 14px; margin: 0; }
  .pslide h1 { font-size: 40px; font-weight: 700; letter-spacing: -.02em; line-height: 1.1; }
  .pslide .id { font-family: "Cascadia Code", Consolas, monospace; font-size: 14px; color: var(--muted); }
  .pslide .page { color: var(--muted); font-size: 15px; font-weight: 600; }
  .pslide .body { display: grid; grid-template-columns: 380px 1fr; gap: 28px; min-height: 0; }
  .pslide .facts { display: flex; flex-direction: column; gap: 4px; }
  .pslide .facts dt { font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--c); margin-top: 12px; }
  .pslide .facts dt:first-child { margin-top: 0; }
  .pslide .facts dd { font-size: 17px; line-height: 1.38; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
  .pslide .prompts { display: flex; flex-direction: column; gap: 10px; min-height: 0; overflow: hidden; }
  .pslide .prompt { background: var(--card); border: 1px solid var(--line); border-left: 5px solid var(--c); border-radius: 12px; padding: 12px 16px; box-shadow: 0 2px 10px #17203310; min-height: 0; }
  .pslide .prompt:only-child { flex: 1; }
  .pslide .ptitle { font-size: 12px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin-bottom: 8px; }
  .pslide pre { font-family: "Cascadia Code", Consolas, monospace; font-size: 15px; line-height: 1.55; white-space: pre-wrap; color: #2a3550; }
  .pslide pre.small { font-size: 12.3px; line-height: 1.42; }
  .pslide mark { background: #fff1c7; color: #7a4b00; border-radius: 3px; padding: 0 2px; }
  .pslide mark.diff { background: #dcebff; color: #0f4fa8; font-weight: 600; }
  .pslide footer { display: flex; gap: 30px; font-size: 13px; color: var(--muted); border-top: 1px solid var(--line); padding-top: 10px; }
  .pslide footer span:last-child { margin-left: auto; }
"""

DECK_CSS = """
  .pslide { position: fixed; left: 50%; top: 50%; margin: -450px 0 0 -800px; display: grid; opacity: 0; pointer-events: none;
    transform: scale(calc(var(--s, 1) * .94)); transition: opacity .45s ease, transform .55s cubic-bezier(.2,.7,.2,1); z-index: 5; }
  .pslide.on { opacity: 1; transform: scale(var(--s, 1)); pointer-events: auto; }
  .slide .step { transition-property: left, top, border-color, box-shadow, filter; }
  .slide.focus .step:not(.hl) { filter: opacity(.22) grayscale(.7); }
  .slide.focus svg.wires { opacity: .25; } svg.wires { transition: opacity .5s; }
  .slide.focus .step.hl { box-shadow: 0 0 0 4px color-mix(in srgb, var(--hc) 30%, transparent), 0 14px 34px color-mix(in srgb, var(--hc) 35%, transparent); }
  .slide.focus .x3 span:not(.hl) { opacity: .3; } .x3 span { transition: opacity .5s, background .5s, color .5s; }
  .slide.focus .x3 span.hl { background: var(--studio); color: #fff; }
  .xframe { position: fixed; inset: 0; width: 100vw; height: 100vh; border: 0; opacity: 0; pointer-events: none; z-index: 6; background: #e9edf4; transition: opacity .45s ease; }
  .xframe.on { opacity: 1; }
  .deck-nav { position: fixed; bottom: 12px; right: 16px; z-index: 10; display: flex; align-items: center; gap: 10px; color: #7d8cab; font-size: 13px; font-weight: 600; }
  .deck-nav button { width: 34px; height: 34px; border-radius: 50%; border: 1px solid #cfd7e6; background: #fff; color: #3b4762; font-size: 18px; line-height: 1; cursor: pointer; box-shadow: 0 2px 8px #17203314; }
  .deck-nav button:hover { border-color: #2470d6; color: #2470d6; }
  .hint { display: none; }
  .pslide footer { padding-right: 150px; }
  @media print { .pslide, .xframe, .deck-nav { display: none; } }
"""

DECK_JS = """
<script>
  const deckAgents = __AGENTS__;
  const deckPrompts = [...document.querySelectorAll(".pslide")];
  const deckFrames = Object.fromEntries([...document.querySelectorAll(".xframe")].map(f => [f.dataset.id, f]));
  const deckSeq = [{ frame: "iq" }, { frame: "kinds" }, { frame: "intro" }, { mode: "biz" }, { mode: "tech" }];
  deckAgents.forEach((a, k) => deckSeq.push({ mode: "tech", agent: k }, { mode: "tech", agent: k, prompt: true }));
  deckSeq.push({ mode: "tech" }, { frame: "agents" });
  let deckAt = -1, flowSeen = false;
  const deckFit = () => document.documentElement.style.setProperty("--s", Math.min(innerWidth / 1600, innerHeight / 900));
  const replayFlow = () => {
    steps.forEach((el, i) => { el.style.animation = "none"; void el.offsetWidth; el.style.animation = ""; el.style.animationDelay = `${.08 * i}s`; });
    animateWires(1500);
  };
  const deckShow = n => {
    const prev = deckSeq[deckAt];
    deckAt = Math.min(Math.max(n, 0), deckSeq.length - 1);
    const st = deckSeq[deckAt], a = deckAgents[st.agent];
    Object.entries(deckFrames).forEach(([id, f]) => {
      const on = st.frame === id;
      if (on && !f.classList.contains("on")) f.src = f.getAttribute("src");
      f.classList.toggle("on", on);
    });
    deckPrompts.forEach((p, k) => p.classList.toggle("on", !!st.prompt && k === st.agent));
    document.getElementById("deckPos").textContent = `${deckAt + 1} / ${deckSeq.length}`;
    history.replaceState(null, "", `#${deckAt + 1}`);
    if (st.frame) return;
    if (!flowSeen || (prev && prev.frame)) { flowSeen = true; replayFlow(); }
    steps.forEach(el => { el.classList.remove("hl"); el.style.removeProperty("--hc"); });
    track.querySelectorAll(".x3 span").forEach(el => el.classList.remove("hl"));
    if (st.mode !== mode) setMode(st.mode); else steps.forEach(el => el.style.transitionDelay = "0s");
    slide.classList.toggle("focus", !!a);
    if (a) {
      a.steps.forEach(id => { const el = s(id); el.classList.add("hl"); el.style.setProperty("--hc", `var(--${a.color})`); });
      if (a.chip) [...track.querySelectorAll(".x3 span")].find(el => el.textContent === a.chip).classList.add("hl");
    }
  };
  addEventListener("keydown", e => {
    const fwd = [" ", "ArrowRight", "ArrowDown", "Enter", "PageDown"].includes(e.key), back = ["ArrowLeft", "ArrowUp", "Backspace", "PageUp"].includes(e.key);
    if (e.key === "Home" || e.key === "End") { e.preventDefault(); e.stopImmediatePropagation(); deckShow(e.key === "Home" ? 0 : deckSeq.length - 1); return; }
    if (!fwd && !back) return;
    e.preventDefault(); e.stopImmediatePropagation();
    deckShow(deckAt + (fwd ? 1 : -1));
  }, true);
  addEventListener("click", e => {
    e.stopPropagation();
    const nav = e.target.closest("[data-nav]");
    deckShow(deckAt + (nav ? +nav.dataset.nav : 1));
  }, true);
  addEventListener("resize", deckFit); deckFit();
  deckShow((parseInt(location.hash.slice(1)) || 1) - 1);
</script>
"""

FRAMES = """
<iframe class="xframe" data-id="iq" src="iq.html" tabindex="-1" title="Microsoft IQ"></iframe>
<iframe class="xframe" data-id="kinds" src="agent-kinds.html" tabindex="-1" title="Personal agents vs Always-on agents"></iframe>
<iframe class="xframe" data-id="intro" src="intro.html" tabindex="-1" title="The story"></iframe>
<iframe class="xframe" data-id="agents" src="agents.html" tabindex="-1" title="Agents and triggers"></iframe>
<div class="deck-nav"><button data-nav="-1" aria-label="Previous">‹</button><span id="deckPos"></span><button data-nav="1" aria-label="Next">›</button></div>
"""

def prompts_page(slides: str) -> str:
    return TEMPLATE.replace("{{CSS}}", PROMPT_CSS).replace("{{SLIDES}}", slides)


def deck_page(slides: str) -> str:
    flow = (ROOT / "docs" / "flow-animated.html").read_text(encoding="utf-8")
    hint = '<div class="hint">Space / click = show who does it · ← back · F = full screen · P = print</div>'
    for needle in ("</style>", hint, "</body>", "<title>"):
        if needle not in flow:
            raise ValueError(f"flow-animated.html changed; missing {needle!r}")
    flow = re.sub(r"<title>.*?</title>", "<title>Caldova Drive — From a bump to a booked repair</title>", flow)
    flow = flow.replace("</style>", PROMPT_CSS + DECK_CSS + "</style>", 1)
    flow = flow.replace(hint, slides + FRAMES, 1)
    js = DECK_JS.replace("__AGENTS__", json.dumps(AGENTS))
    return flow.replace("</body>", js + "</body>", 1)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Caldova Drive — The agents and their prompts</title>
<style>
  :root { --bg:#f7f8fb; --card:#fff; --line:#dde3ee; --text:#172033; --muted:#5d6a82; --fabric:#0f9d7a; --foundry:#8a4fd1; --studio:#2470d6; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: #e9edf4; font-family: "Segoe UI Variable", "Segoe UI", system-ui, sans-serif; color: var(--text); }
  body { display: grid; place-items: center; overflow: hidden; }
{{CSS}}
  .pslide { position: absolute; left: 50%; top: 50%; margin: -450px 0 0 -800px; display: none; }
  .pslide.on { display: grid; }
  .hint { position: fixed; bottom: 10px; right: 14px; color: #9aa6bb; font-size: 12px; }
  @media print {
    @page { size: 1600px 900px; margin: 0; }
    html, body { overflow: visible; background: var(--bg); display: block; } .hint { display: none; }
    .pslide { display: grid !important; position: relative; transform: none !important; box-shadow: none; page-break-after: always; }
  }
</style>
</head>
<body>
{{SLIDES}}
<div class="hint">← → / Space = next agent · F = full screen · P = print all</div>
<script>
  const slides = [...document.querySelectorAll(".pslide")];
  let i = Math.min(Math.max((parseInt(location.hash.slice(1)) || 1) - 1, 0), slides.length - 1);
  const fit = () => slides.forEach(s => s.style.transform = `scale(${Math.min(innerWidth / 1600, innerHeight / 900)})`);
  const show = n => { i = (n + slides.length) % slides.length; slides.forEach((s, k) => s.classList.toggle("on", k === i)); history.replaceState(null, "", `#${i + 1}`); };
  addEventListener("resize", fit); fit(); show(i);
  addEventListener("keydown", e => {
    if ([" ", "ArrowRight", "PageDown", "Enter"].includes(e.key)) { e.preventDefault(); show(i + 1); }
    if (["ArrowLeft", "PageUp", "Backspace"].includes(e.key)) { e.preventDefault(); show(i - 1); }
    if (e.key === "f" || e.key === "F") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
    if (e.key === "p" || e.key === "P") print();
  });
  addEventListener("click", () => show(i + 1));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    slides = build()
    for name, page in (("prompts.html", prompts_page(slides)), ("index.html", deck_page(slides))):
        target = ROOT / "docs" / name
        target.write_text(page, encoding="utf-8")
        print(target)
