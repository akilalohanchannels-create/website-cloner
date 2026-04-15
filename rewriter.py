"""
rewriter.py — AI copy rewriter using Claude Code CLI (claude -p).
Takes a cloned website and rewrites all visible text for a new brand.
Preserves all HTML structure, image src, href, class names, and CSS.
No API key required — uses your existing Claude Code subscription.
"""

import re
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup


def _call_claude(prompt: str, timeout: int = 300) -> str:
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
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    return text.strip()


def _extract_text_nodes(soup: BeautifulSoup) -> list[dict]:
    """
    Extract all visible text nodes (not inside script/style tags).
    Returns list of {id, original_text} for Claude to rewrite.
    """
    skip_tags = {"script", "style", "meta", "link", "head"}
    text_nodes = []
    node_id = 0

    for tag in soup.find_all(True):
        if tag.name in skip_tags:
            continue
        for child in tag.children:
            if hasattr(child, "string") and child.string:
                text = child.string.strip()
                if text and len(text) > 2:  # skip whitespace-only and single chars
                    text_nodes.append({"id": node_id, "text": text})
                    node_id += 1

    return text_nodes


def _rewrite_page(html: str, new_brand: str, page_filename: str) -> str:
    """Rewrite visible text in one HTML page for a new brand."""
    soup = BeautifulSoup(html, "lxml")

    # Extract all visible text nodes with IDs
    text_nodes = _extract_text_nodes(soup)
    if not text_nodes:
        return html

    # Build the text map for Claude
    text_map = "\n".join(f'[{n["id"]}] {n["text"]}' for n in text_nodes)

    prompt = f"""You are a copywriter. Rewrite the following text content for a new brand.

New brand description: {new_brand}
Page: {page_filename}

Rules:
- Rewrite EVERY item — match the tone and purpose of the original
- Keep the same approximate length — don't expand or shrink dramatically
- Preserve formatting cues (ALL CAPS stays ALL CAPS, title case stays title case)
- Keep numbers, phone formats, and email formats realistic
- Do NOT change navigation labels unless they make no sense for the new brand
- Output ONLY the rewritten items in the exact same format: [id] new text
- Output every ID — do not skip any

Text to rewrite:
{text_map}"""

    raw = _call_claude(prompt, timeout=300)

    # Parse Claude's output back into a map
    rewrite_map = {}
    for line in raw.strip().splitlines():
        match = re.match(r'\[(\d+)\]\s+(.*)', line.strip())
        if match:
            rewrite_map[int(match.group(1))] = match.group(2).strip()

    # Apply rewrites back to the soup
    node_id = 0
    skip_tags = {"script", "style", "meta", "link", "head"}

    for tag in soup.find_all(True):
        if tag.name in skip_tags:
            continue
        for child in tag.children:
            if hasattr(child, "string") and child.string:
                text = child.string.strip()
                if text and len(text) > 2:
                    if node_id in rewrite_map:
                        child.string.replace_with(rewrite_map[node_id])
                    node_id += 1

    return str(soup)


def rewrite_site(site_dir: str, new_brand: str) -> dict:
    """
    Rewrite all HTML pages in a cloned site for a new brand.

    Args:
        site_dir:  Path to the cloned site folder
        new_brand: Description of the new brand/business

    Returns:
        dict with count of rewritten pages
    """
    site_path = Path(site_dir)
    html_files = list(site_path.rglob("*.html"))

    if not html_files:
        print(f"[Rewriter] No HTML files found in {site_dir}")
        return {"rewritten": 0}

    print(f"[Rewriter] Rewriting {len(html_files)} pages for: {new_brand}")

    rewritten = 0
    for html_file in html_files:
        print(f"  Rewriting {html_file.relative_to(site_path)}...")
        try:
            original = html_file.read_text(encoding="utf-8", errors="replace")
            rewritten_html = _rewrite_page(original, new_brand, html_file.name)
            html_file.write_text(rewritten_html, encoding="utf-8")
            rewritten += 1
            print(f"  ✓ Done")
        except Exception as e:
            print(f"  ✗ Failed — {e}")

    print(f"\n[Rewriter] Done — {rewritten}/{len(html_files)} pages rewritten")
    return {"rewritten": rewritten, "total": len(html_files)}
