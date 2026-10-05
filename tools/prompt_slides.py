"""Build the presentation from source instructions, omitting company names in display copies."""
import ast
import html
import json
import re
from pathlib import Path

from tools.render_media_story import render_media_story

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
    for original, display in (
        ("You are Caldova Drive, the operations copilot", "You are the operations copilot"),
        ("Caldova's", "the insurer's"),
        ("Caldova Repair Policy", "Repair Policy"),
        ("Caldova RP-02", "RP-02"),
    ):
        text = text.replace(original, display)
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
  <footer><span><mark>highlighted</mark> = guardrail</span><span><mark class="diff">blue</mark> = what makes this agent different</span><span>Source instructions; company names omitted.</span></footer>
</section>"""


def build() -> str:
    foundry = constant("fleet/foundry.py", "AGENT_INSTRUCTIONS")
    photo, privacy, report = evidence_tasks()
    fleet = constant("tools/intelligence.py", "INSTRUCTIONS")
    garages = {
        "alder": ("Alder Bodyworks", "alder.repairs@", "Fastest + cheapest, but aftermarket parts: excluded", [r"NEW AFTERMARKET", r"does NOT comply with RP-02", r"12-month warranty"]),
        "metro": ("Metro Rapid Repair", "metro.repairs@", "Priority slot, back on the road sooner", [r"Explain that the price includes priority access to an earlier workshop slot\.", r"18-month warranty"]),
        "riverside": ("Riverside Auto Care", "riverside.repairs@", "Balanced price and availability", [r"Present the balanced cost and workshop-availability option\.", r"12-month warranty"]),
    }
    slides = [slide(
        1, "foundry", "Microsoft Foundry Agent Service", "Evidence agent", "Incident evidence · GPT-4.1 vision",
        [("Wakes", "Customer submits photos + explanation"),
         ("Does", "A local detector places face masks; Foundry inspects the photo, checks remaining privacy risks and writes the brief"),
         ("Two prompt layers", "Agent instructions live in Foundry; each call adds a task prompt with the exact JSON shape"),
         ("Output checked", "Strict schema validation; unclear privacy or non-cosmetic damage → human review"),
         ("Never", "Liability, coverage, roadworthiness, email, bookings")],
        [("Agent instructions · stored in Foundry", render(foundry)),
         ("Task 1 · inspect photo", render(photo)), ("Task 2 · verify redaction", render(privacy)), ("Task 3 · repair brief", render(report))],
        small=True,
    ), slide(
        2, "studio", "Copilot Studio", "Claims coordinator", "Repair coordinator · claims mailbox",
        [("Wakes", "Brief ready → quotation request<br>Three quotes → recommendation"),
         ("Reads", "Versioned repair policy and evidence supplied by the application"),
         ("Does", "Drafts the RFQ and recommends the best compliant quotation"),
         ("Email", "The application sends reviewed messages through scoped Exchange access"),
         ("Human gate", "Only recorded operator approval permits booking; the app rechecks policy and quote terms")],
        [("Agent instructions · Copilot Studio", render(studio("coordinator")))],
        small=True,
    )]
    for i, (key, (name, mailbox, pitch, diffs)) in enumerate(garages.items(), start=3):
        slides.append(slide(
            i, "studio", "Copilot Studio · repair centre", name, f"{key} · {mailbox}",
            [("Wakes", "An email lands in its own shared mailbox"),
             ("Position", pitch),
             ("Quote", "Uses the supplied policy, rate card and capacity; preserves its own trusted offer exactly"),
             ("Booking", "Only compliant parts + recorded operator approval; exact quotation fingerprint confirmed"),
             ("Delivery", "The application validates and sends the reply from the approved shared mailbox")],
            [("Agent instructions · Copilot Studio", render(studio(key), diffs))],
            small=True,
        ))
    slides.append(slide(
        6, "fabric", "Fabric data agent · Fabric IQ", "Fleet data agent", "Lakehouse FleetIntelligence · in Microsoft 365 Copilot",
        [("Wakes", "Someone asks a question in Fabric or Microsoft 365 Copilot"),
         ("Reads", "Vehicles, Branches, Rentals, VehicleState, DailyMileage, Incidents, RepairQuotes"),
         ("Knows", "Units, the Madrid reporting calendar, and approved ≠ booked"),
         ("New", "Parts eligibility, policy clauses, recommended vs approved garage and valid overrides"),
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
    {"name": "Fleet data agent", "color": "fabric", "steps": ["s9"]},
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
  .pslide .prompts { display: flex; flex-direction: column; gap: 10px; min-height: 0; overflow: auto; }
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
  .deck-nav a { color:#52677d; text-decoration:none; margin-right:8px; }
  .deck-nav a:hover { color:#117865; text-decoration:underline; }
  .hint { display: none; }
  .pslide footer { padding-right: 150px; }
  @media print { .pslide, .xframe, .deck-nav { display: none; } }
"""

DECK_JS = """
<script>
  const deckAgents = __AGENTS__;
  const deckPrompts = [...document.querySelectorAll(".pslide")];
  const deckFrames = Object.fromEntries([...document.querySelectorAll(".xframe")].map(f => [f.dataset.id, f]));
  const deckSeq = [{ frame: "intro" }, { mode: "biz" }, { mode: "tech" }, { frame: "agents" }];
  deckAgents.forEach((a, k) => deckSeq.push({ mode: "tech", agent: k }, { mode: "tech", agent: k, prompt: true }));
  deckSeq.push({ mode: "tech" }, { frame: "iq" }, { frame: "kinds" });
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
    const fwd = ["ArrowRight", "ArrowDown"].includes(e.key), back = ["ArrowLeft", "ArrowUp"].includes(e.key);
    if (!fwd && !back) return;
    e.preventDefault(); e.stopImmediatePropagation();
    deckShow(deckAt + (fwd ? 1 : -1));
  }, true);
  addEventListener("resize", deckFit); deckFit();
  deckShow((parseInt(location.hash.slice(1)) || 1) - 1);
</script>
"""

LASER_CSS = """
  html.laser-active, html.laser-active * { cursor: none !important; }
  .laser-pointer { position: fixed; left: 0; top: 0; width: 10px; height: 10px; margin: -5px;
    border-radius: 50%; background: #fff0f0; border: 2px solid #ff2438;
    box-shadow: 0 0 6px 3px #ff2438cc, 0 0 20px 8px #ff243855;
    pointer-events: none; z-index: 2147483647; display: none; }
  html.laser-active .laser-pointer { display: block; }
  @media print { .laser-pointer { display: none !important; } }
"""

LASER_JS = """
<script>
  (() => {
    const pointer = document.createElement("div");
    pointer.className = "laser-pointer";
    pointer.setAttribute("aria-hidden", "true");
    document.body.append(pointer);
    const mouse = matchMedia("(hover: hover) and (pointer: fine)");
    const hide = () => document.documentElement.classList.remove("laser-active");
    document.addEventListener("pointermove", e => {
      if (e.pointerType !== "mouse" || !mouse.matches) { hide(); return; }
      pointer.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
      document.documentElement.classList.add("laser-active");
    });
    document.documentElement.addEventListener("pointerleave", hide);
    document.addEventListener("pointerdown", e => { if (e.pointerType !== "mouse") hide(); });
    addEventListener("blur", hide);
    document.addEventListener("visibilitychange", () => { if (document.hidden) hide(); });
    mouse.addEventListener("change", hide);
  })();
</script>
"""

FRAMES = """
<iframe class="xframe" data-id="iq" src="iq.html" tabindex="-1" title="Microsoft IQ"></iframe>
<iframe class="xframe" data-id="kinds" src="agent-kinds.html" tabindex="-1" title="Personal agents vs Always-on agents"></iframe>
<iframe class="xframe" data-id="intro" src="intro.html" tabindex="-1" title="From incident to repair"></iframe>
<iframe class="xframe" data-id="agents" src="agents.html" tabindex="-1" title="Agents and triggers"></iframe>
<div class="deck-nav"><a href="mediastory.html">Media story</a><span id="deckPos"></span></div>
"""

def prompts_page(slides: str) -> str:
    return TEMPLATE.replace("{{CSS}}", PROMPT_CSS + LASER_CSS).replace("{{SLIDES}}", slides).replace("</body>", LASER_JS + "</body>")


def deck_page(slides: str) -> str:
    flow = (ROOT / "docs" / "flow-animated.html").read_text(encoding="utf-8")
    hint = '<div class="hint">← / → = switch view · F = full screen · P = print</div>'
    for needle in ("</style>", hint, "</body>", "<title>"):
        if needle not in flow:
            raise ValueError(f"flow-animated.html changed; missing {needle!r}")
    flow = re.sub(r"<title>.*?</title>", "<title>From incident to repair</title>", flow)
    flow = flow.replace("</style>", PROMPT_CSS + DECK_CSS + LASER_CSS + "</style>", 1)
    flow = flow.replace(hint, slides + FRAMES, 1)
    js = DECK_JS.replace("__AGENTS__", json.dumps(AGENTS))
    return flow.replace("</body>", js + LASER_JS + "</body>", 1)


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The agents and their prompts</title>
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
<div class="hint">← → = previous / next agent · F = full screen · P = print all</div>
<script>
  const slides = [...document.querySelectorAll(".pslide")];
  let i = Math.min(Math.max((parseInt(location.hash.slice(1)) || 1) - 1, 0), slides.length - 1);
  const fit = () => slides.forEach(s => s.style.transform = `scale(${Math.min(innerWidth / 1600, innerHeight / 900)})`);
  const show = n => { i = (n + slides.length) % slides.length; slides.forEach((s, k) => s.classList.toggle("on", k === i)); history.replaceState(null, "", `#${i + 1}`); };
  addEventListener("resize", fit); fit(); show(i);
  addEventListener("keydown", e => {
    if (["ArrowRight", "ArrowDown"].includes(e.key)) { e.preventDefault(); show(i + 1); }
    if (["ArrowLeft", "ArrowUp"].includes(e.key)) { e.preventDefault(); show(i - 1); }
    if (e.key === "f" || e.key === "F") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
    if (e.key === "p" || e.key === "P") print();
  });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    slides = build()
    media_story = (ROOT / "docs" / "mediastory.md").read_text(encoding="utf-8")
    for name, page in (
        ("prompts.html", prompts_page(slides)),
        ("index.html", deck_page(slides)),
        ("mediastory.html", render_media_story(media_story)),
    ):
        target = ROOT / "docs" / name
        target.write_text(page, encoding="utf-8")
        print(target)
