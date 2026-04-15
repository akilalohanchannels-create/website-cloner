import os
import re
import time
import json
import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag
from typing import Optional

import requests
from bs4 import BeautifulSoup
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-opus-4-6"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ─────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────

def fetch_page(url: str, timeout: int = 15) -> dict:
    """Download a single HTML page and return its content + final URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return {
            "ok": True,
            "url": resp.url,
            "status": resp.status_code,
            "html": resp.text,
            "content_type": resp.headers.get("Content-Type", ""),
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def discover_assets(html: str, base_url: str) -> dict:
    """Parse HTML and return all linked pages + assets found."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    pages = set()
    assets = set()

    # Internal links → pages to crawl
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        full = urljoin(base_url, urldefrag(href)[0])
        p = urlparse(full)
        if p.netloc == base_domain and p.scheme in ("http", "https"):
            pages.add(full)

    # CSS / JS
    for tag in soup.find_all("link", href=True):
        assets.add(urljoin(base_url, tag["href"]))
    for tag in soup.find_all("script", src=True):
        assets.add(urljoin(base_url, tag["src"]))

    # Images
    for tag in soup.find_all("img", src=True):
        assets.add(urljoin(base_url, tag["src"]))
    for tag in soup.find_all("img", attrs={"data-src": True}):
        assets.add(urljoin(base_url, tag["data-src"]))

    # Inline CSS background images
    for tag in soup.find_all(style=True):
        urls = re.findall(r'url\(["\']?(.*?)["\']?\)', tag["style"])
        for u in urls:
            assets.add(urljoin(base_url, u))

    # Favicon
    for tag in soup.find_all("link", rel=lambda r: r and "icon" in r):
        if tag.get("href"):
            assets.add(urljoin(base_url, tag["href"]))

    return {
        "pages": sorted(pages),
        "assets": sorted(assets),
    }


def download_asset(url: str, output_dir: str, timeout: int = 15) -> dict:
    """Download a binary/text asset and save it to output_dir, preserving URL path."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()

        parsed = urlparse(url)
        rel_path = parsed.netloc + parsed.path
        # Strip query strings from filename but hash them into the name if needed
        if parsed.query:
            ext = Path(parsed.path).suffix or ""
            stem = Path(parsed.path).stem
            qhash = hashlib.md5(parsed.query.encode()).hexdigest()[:6]
            rel_path = parsed.netloc + str(Path(parsed.path).parent / f"{stem}_{qhash}{ext}")

        local_path = Path(output_dir) / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        content_type = resp.headers.get("Content-Type", "")
        is_text = "text" in content_type or "javascript" in content_type or "json" in content_type

        if is_text:
            local_path.write_text(resp.text, encoding="utf-8", errors="replace")
        else:
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

        return {"ok": True, "url": url, "saved_to": str(local_path)}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def save_html_page(html: str, page_url: str, base_url: str, output_dir: str) -> dict:
    """
    Rewrite all asset references in the HTML to relative local paths,
    then save the page to output_dir.
    """
    soup = BeautifulSoup(html, "html.parser")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc

    def url_to_local(url: str) -> Optional[str]:
        """Convert an absolute URL to a local relative path string."""
        full = urljoin(page_url, url)
        p = urlparse(full)
        if p.scheme not in ("http", "https"):
            return None
        rel = p.netloc + p.path
        if p.query:
            stem = Path(p.path).stem
            ext = Path(p.path).suffix or ""
            qhash = hashlib.md5(p.query.encode()).hexdigest()[:6]
            rel = p.netloc + str(Path(p.path).parent / f"{stem}_{qhash}{ext}")
        # Make it relative from the page's own location
        parsed_page = urlparse(page_url)
        page_path = Path(parsed_page.netloc + parsed_page.path)
        page_dir = page_path.parent if page_path.suffix else page_path
        try:
            asset_path = Path(output_dir) / rel
            page_dir_full = Path(output_dir) / page_dir
            return os.path.relpath(asset_path, page_dir_full)
        except ValueError:
            return None

    # Rewrite links
    for tag in soup.find_all("link", href=True):
        local = url_to_local(tag["href"])
        if local:
            tag["href"] = local

    for tag in soup.find_all("script", src=True):
        local = url_to_local(tag["src"])
        if local:
            tag["src"] = local

    for tag in soup.find_all("img", src=True):
        local = url_to_local(tag["src"])
        if local:
            tag["src"] = local

    for tag in soup.find_all("a", href=True):
        full = urljoin(page_url, tag["href"])
        p = urlparse(full)
        if p.netloc == base_domain:
            local = url_to_local(tag["href"])
            if local:
                tag["href"] = local

    # Determine output path
    parsed_page = urlparse(page_url)
    rel_path = parsed_page.netloc + parsed_page.path
    if not Path(rel_path).suffix:
        rel_path = rel_path.rstrip("/") + "/index.html"

    local_path = Path(output_dir) / rel_path
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(str(soup), encoding="utf-8")

    return {"ok": True, "url": page_url, "saved_to": str(local_path)}


def clone_summary(output_dir: str) -> dict:
    """Count all cloned files and return a summary."""
    out = Path(output_dir)
    if not out.exists():
        return {"ok": False, "error": "Output directory does not exist"}
    files = list(out.rglob("*"))
    file_list = [str(f.relative_to(out)) for f in files if f.is_file()]
    total_size = sum(f.stat().st_size for f in files if f.is_file())
    return {
        "ok": True,
        "total_files": len(file_list),
        "total_size_kb": round(total_size / 1024, 1),
        "output_dir": str(out.resolve()),
        "files": file_list[:50],  # cap to avoid overflow
    }


# ─────────────────────────────────────────────
# Tool schema for Claude
# ─────────────────────────────────────────────

TOOLS = [
    {
        "name": "fetch_page",
        "description": "Download an HTML page from a URL. Returns the HTML content and final redirected URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL of the page to fetch"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "discover_assets",
        "description": "Parse HTML to find all internal page links and external asset URLs (CSS, JS, images, fonts, favicon).",
        "input_schema": {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "Raw HTML of the page"},
                "base_url": {"type": "string", "description": "The page's URL (used to resolve relative links)"},
            },
            "required": ["html", "base_url"],
        },
    },
    {
        "name": "download_asset",
        "description": "Download a single asset (CSS, JS, image, font, etc.) and save it to the output directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL of the asset to download"},
                "output_dir": {"type": "string", "description": "Local directory to save the asset into"},
            },
            "required": ["url", "output_dir"],
        },
    },
    {
        "name": "save_html_page",
        "description": "Rewrite asset references in HTML to relative local paths, then save the page to output_dir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "Raw HTML of the page"},
                "page_url": {"type": "string", "description": "URL of the page (used to compute relative paths)"},
                "base_url": {"type": "string", "description": "The root URL of the site being cloned"},
                "output_dir": {"type": "string", "description": "Local directory to save pages into"},
            },
            "required": ["html", "page_url", "base_url", "output_dir"],
        },
    },
    {
        "name": "clone_summary",
        "description": "Return a summary of everything cloned so far: file count, total size, and file list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_dir": {"type": "string", "description": "The output directory used for the clone"},
            },
            "required": ["output_dir"],
        },
    },
]


# ─────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────

TOOL_FN = {
    "fetch_page": lambda i: fetch_page(i["url"]),
    "discover_assets": lambda i: discover_assets(i["html"], i["base_url"]),
    "download_asset": lambda i: download_asset(i["url"], i["output_dir"]),
    "save_html_page": lambda i: save_html_page(i["html"], i["page_url"], i["base_url"], i["output_dir"]),
    "clone_summary": lambda i: clone_summary(i["output_dir"]),
}


def run_tool(name: str, inputs: dict) -> str:
    fn = TOOL_FN.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    result = fn(inputs)
    return json.dumps(result)


# ─────────────────────────────────────────────
# Agent loop
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are a website cloner agent. Your job is to clone a website by:

1. Fetching the root page with `fetch_page`
2. Using `discover_assets` to find all linked pages and assets
3. Downloading every asset with `download_asset` (CSS, JS, images, fonts, favicon)
4. Saving each HTML page with `save_html_page` (which rewrites asset links to local paths)
5. Repeating steps 2–4 for each discovered internal page (crawl up to the depth/page limit)
6. Finishing with `clone_summary` to report what was cloned

Rules:
- Only crawl internal links (same domain as the starting URL)
- Skip URLs you have already visited
- Download all unique assets once
- If an asset or page fails to download, log it and continue
- Default page limit: 20 pages unless the user specifies otherwise
- Work methodically and completely — do not stop until all discovered pages and assets are cloned
- When done, report the output directory, total files, and total size

The user will give you a URL and an output directory. Begin immediately."""


def run_agent(user_message: str) -> None:
    messages = [{"role": "user", "content": user_message}]

    print(f"\n[Agent] Starting — {user_message}\n")

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text output
        for block in response.content:
            if hasattr(block, "text") and block.text:
                print(f"[Agent] {block.text}")

        # Check stop reason
        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            print(f"[Agent] Unexpected stop reason: {response.stop_reason}")
            break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            tool_name = block.name
            tool_input = block.input
            print(f"[Tool] {tool_name}({json.dumps({k: v[:80] + '...' if isinstance(v, str) and len(v) > 80 else v for k, v in tool_input.items()})})")

            result_str = run_tool(tool_name, tool_input)
            result_data = json.loads(result_str)

            # Print concise result
            if result_data.get("ok") is False:
                print(f"  ✗ {result_data.get('error', 'failed')}")
            elif "saved_to" in result_data:
                print(f"  ✓ Saved → {result_data['saved_to']}")
            elif "total_files" in result_data:
                print(f"  ✓ {result_data['total_files']} files, {result_data['total_size_kb']} KB → {result_data['output_dir']}")
            elif "pages" in result_data:
                print(f"  ✓ Found {len(result_data['pages'])} pages, {len(result_data['assets'])} assets")

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
            })

        # Append assistant turn + tool results
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        time.sleep(0.2)  # polite rate limiting
