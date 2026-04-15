"""
builder.py — AI website generator using Claude Code CLI (claude -p).
Generates complete HTML/CSS/JS sites from a text prompt, one page at a time.
No API key required — uses your existing Claude Code subscription.
"""

import re
import json
import subprocess
from pathlib import Path


def _call_claude(prompt: str, timeout: int = 300) -> str:
    """Call claude CLI in print mode and return stdout."""
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI error: {result.stderr.strip()}")
    return result.stdout.strip()


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if Claude wraps output in them."""
    text = text.strip()
    # Remove ```html ... ``` or ``` ... ```
    text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


def _plan_pages(description: str) -> list[dict]:
    """
    Ask Claude what pages the site needs.
    Returns a list of {filename, title, purpose}.
    """
    prompt = f"""You are a web architect. A client wants a website described as:

"{description}"

List the pages this site needs as a JSON array. Each item must have:
- filename: the HTML filename (e.g. "index.html", "about.html")
- title: the page title
- purpose: one sentence describing the page's content

Output ONLY the raw JSON array. No explanation, no markdown, no code fences.

Example output:
[
  {{"filename": "index.html", "title": "Home", "purpose": "Hero section, services overview, CTA"}},
  {{"filename": "about.html", "title": "About", "purpose": "Company story and team"}}
]"""

    raw = _call_claude(prompt)
    raw = _strip_fences(raw)
    # Extract JSON array if there's extra text
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _generate_page(
    description: str,
    page: dict,
    all_pages: list[dict],
    image_refs: list[str],
    brand_colors: str = "",
) -> str:
    """Generate a single HTML page via Claude CLI."""

    nav_links = "\n".join(
        f'- {p["filename"]} ({p["title"]})'
        for p in all_pages
        if p["filename"] != page["filename"]
    )

    image_section = ""
    if image_refs:
        image_section = f"""
Available local images/videos (use these exact paths in src attributes):
{chr(10).join(f'- {img}' for img in image_refs)}
"""
    else:
        image_section = "No images provided — use CSS gradients, SVG shapes, or Unicode icons for visuals. Do NOT use placeholder image services."

    color_section = f"\nBrand colors: {brand_colors}" if brand_colors else ""

    prompt = f"""You are an expert web developer. Generate a complete, production-ready HTML page.

Site description: {description}
Page: {page["title"]} ({page["filename"]})
Page purpose: {page["purpose"]}
{color_section}

Other pages to link to in navigation:
{nav_links if nav_links else "None — this is the only page"}

{image_section}

Requirements:
- Complete single HTML file with all CSS in a <style> tag in <head>
- All JavaScript in a <script> tag before </body>
- Responsive mobile-first design using CSS Grid and Flexbox
- Modern, professional design — no Bootstrap, no CDN links
- Navigation links to all other pages listed above
- Semantic HTML5 elements (header, main, section, footer, nav, article)
- Clean typography using a Google Fonts @import in the <style> tag only
- Smooth hover effects on buttons and links
- Output ONLY the raw HTML starting with <!DOCTYPE html>. No explanation, no markdown, no code fences."""

    html = _call_claude(prompt, timeout=300)
    return _strip_fences(html)


def build_site(
    description: str,
    output_dir: str,
    image_source_dir: str = None,
    brand_colors: str = "",
) -> dict:
    """
    Build a complete website from a text description.

    Args:
        description:      Natural language description of the site
        output_dir:       Where to save the generated files
        image_source_dir: Optional path to a folder with images/videos to use
        brand_colors:     Optional hex colors e.g. "#1a1a2e, #e94560"

    Returns:
        dict with output_dir and list of generated files
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Collect local image references if provided
    image_refs = []
    if image_source_dir:
        img_dir = Path(image_source_dir)
        if img_dir.exists():
            for f in img_dir.rglob("*"):
                if f.suffix.lower() in {
                    ".jpg", ".jpeg", ".png", ".gif", ".svg",
                    ".webp", ".avif", ".mp4", ".webm"
                }:
                    # Copy images to output dir and record relative path
                    dest = out / "assets" / f.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(f.read_bytes())
                    image_refs.append(f"assets/{f.name}")

    print(f"[Builder] Planning pages for: {description}")
    pages = _plan_pages(description)
    print(f"[Builder] {len(pages)} pages planned: {[p['filename'] for p in pages]}")

    generated = []
    for page in pages:
        print(f"[Builder] Generating {page['filename']} — {page['title']}...")
        html = _generate_page(description, page, pages, image_refs, brand_colors)

        file_path = out / page["filename"]
        file_path.write_text(html, encoding="utf-8")
        generated.append(page["filename"])
        print(f"  ✓ {page['filename']} saved")

    print(f"\n[Builder] Done — {len(generated)} pages → {out.resolve()}")
    return {"output_dir": str(out.resolve()), "files": generated}
