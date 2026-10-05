from __future__ import annotations

import re

from markdown_it import MarkdownIt

from tools.cloud import ROOT


def render_media_story(source: str) -> str:
    markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
    used_ids: set[str] = set()

    def heading(tokens, index, options, env):
        title = tokens[index + 1].content
        base = re.sub(r"[^\w -]", "", title.lower()).replace(" ", "-")
        anchor = base
        suffix = 1
        while anchor in used_ids:
            anchor = f"{base}-{suffix}"
            suffix += 1
        used_ids.add(anchor)
        tokens[index].attrSet("id", anchor)
        return markdown.renderer.renderToken(tokens, index, options, env)

    def link(tokens, index, options, env):
        token = tokens[index]
        target = token.attrGet("href")
        if target in {"storyline.md", "implementation.md"}:
            token.attrSet("href", "https://github.com/crgarcia12/azure-autito-demo/blob/HEAD/docs/" + target)
        return markdown.renderer.renderToken(tokens, index, options, env)

    markdown.renderer.rules["heading_open"] = heading
    markdown.renderer.rules["link_open"] = link
    body = markdown.render(source)
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Microsoft IQ for insurance - Sales media story</title>
<style>
  :root { color-scheme: light; --ink:#172033; --muted:#5d6a82; --line:#dde3ee; --accent:#117865; }
  * { box-sizing: border-box; }
  body { margin:0; background:#f7f8fb; color:var(--ink); font:17px/1.7 "Segoe UI",system-ui,sans-serif; }
  nav { position:sticky; top:0; z-index:1; padding:14px 24px; background:#ffffffed; border-bottom:1px solid var(--line); display:flex; gap:24px; flex-wrap:wrap; }
  nav a { color:var(--accent); font-weight:600; text-decoration:none; }
  main { max-width:1060px; margin:40px auto 80px; padding:0 28px; }
  h1 { font-size:clamp(30px,4vw,46px); line-height:1.15; letter-spacing:-.03em; }
  h2 { font-size:29px; line-height:1.25; margin-top:64px; padding-top:24px; border-top:1px solid var(--line); scroll-margin-top:90px; }
  h3 { scroll-margin-top:90px; }
  p,li { overflow-wrap:anywhere; }
  a { color:var(--accent); text-underline-offset:3px; overflow-wrap:anywhere; }
  blockquote { margin:24px 0; padding:8px 24px; background:white; border-left:4px solid var(--accent); font-size:20px; }
  img { display:block; max-width:100%; height:auto; margin:24px auto; border:1px solid var(--line); border-radius:10px; }
  table { display:block; width:100%; overflow-x:auto; border-collapse:collapse; margin:24px 0; font-size:15px; }
  th,td { padding:12px; border:1px solid var(--line); vertical-align:top; text-align:left; }
  th { background:#eaf2ed; }
  code { font-size:.9em; background:#e9edf3; border-radius:3px; padding:2px 4px; overflow-wrap:anywhere; }
  hr { border:0; border-top:1px solid var(--line); margin:40px 0; }
  @media(max-width:600px) { main { padding:0 18px; } blockquote { padding:6px 16px; font-size:18px; } nav { font-size:14px; gap:16px; } }
  @media print { nav { display:none; } body { background:white; } main { max-width:none; margin:0; padding:0; } img,blockquote { break-inside:avoid; } h2 { break-after:avoid; } }
</style>
</head>
<body>
<nav aria-label="Presentation navigation"><a href="./#1">Open presentation</a><a href="#capture-register">Screenshot sources</a><a href="mediastory.md" download>Download Markdown</a></nav>
<main>
""" + body + """
</main>
</body>
</html>
"""


def main() -> None:
    source = ROOT / "docs" / "mediastory.md"
    destination = source.with_suffix(".html")
    destination.write_text(render_media_story(source.read_text(encoding="utf-8")), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
