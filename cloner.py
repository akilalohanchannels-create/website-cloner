"""
cloner.py — Pure Python website cloner. No AI, no API key required.
Downloads HTML, CSS, JS, images, videos, fonts and rewrites all links to local relative paths.
"""

import re
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin, urldefrag

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

ASSET_EXTENSIONS = {
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".avif", ".bmp", ".tiff",
    # Video
    ".mp4", ".webm", ".ogg", ".mov", ".avi",
    # Audio
    ".mp3", ".wav", ".flac",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Documents
    ".pdf",
    # Data
    ".json", ".xml",
}


class SiteCloner:
    def __init__(self, base_url: str, output_dir: str, max_pages: int = 20, verbose: bool = True):
        # Normalize base URL
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url

        self.base_url = base_url.rstrip("/")
        self.base_domain = urlparse(base_url).netloc
        self.output_dir = Path(output_dir)
        self.max_pages = max_pages
        self.verbose = verbose

        self.visited_pages: set = set()
        self.downloaded_assets: set = set()
        self.failed: list = []

        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ──────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────

    def clone(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._log(f"Cloning {self.base_url} → {self.output_dir}")

        queue = [self.base_url]

        while queue and len(self.visited_pages) < self.max_pages:
            url = queue.pop(0)
            clean_url, _ = urldefrag(url)

            if clean_url in self.visited_pages:
                continue

            self._log(f"[Page {len(self.visited_pages)+1}/{self.max_pages}] {clean_url}")
            result = self._clone_page(clean_url)

            if result:
                self.visited_pages.add(clean_url)
                # Add new internal pages to queue
                for link in result.get("linked_pages", []):
                    if link not in self.visited_pages and link not in queue:
                        queue.append(link)

            time.sleep(0.3)  # polite crawl

        return {
            "pages": len(self.visited_pages),
            "assets": len(self.downloaded_assets),
            "failed": len(self.failed),
            "output_dir": str(self.output_dir.resolve()),
        }

    # ──────────────────────────────────────────
    # Page cloning
    # ──────────────────────────────────────────

    def _clone_page(self, url: str) -> dict | None:
        resp = self._fetch(url)
        if not resp:
            return None

        final_url = resp.url
        content_type = resp.headers.get("Content-Type", "")

        if "text/html" not in content_type:
            self._download_asset(url)
            return None

        soup = BeautifulSoup(resp.text, "lxml")

        # Discover and download all assets first
        assets = self._collect_assets(soup, final_url)
        linked_pages = self._collect_pages(soup, final_url)

        for asset_url in assets:
            if asset_url not in self.downloaded_assets:
                self._download_asset(asset_url)
                self.downloaded_assets.add(asset_url)

        # Rewrite links in HTML to local paths
        self._rewrite_html(soup, final_url)

        # Save the HTML file
        self._save_html(str(soup), final_url)

        return {"linked_pages": linked_pages}

    # ──────────────────────────────────────────
    # Asset discovery
    # ──────────────────────────────────────────

    def _collect_assets(self, soup: BeautifulSoup, page_url: str) -> list:
        assets = set()

        # CSS
        for tag in soup.find_all("link", rel=lambda r: r and ("stylesheet" in r or "preload" in r)):
            if tag.get("href"):
                assets.add(urljoin(page_url, tag["href"]))

        # JS
        for tag in soup.find_all("script", src=True):
            assets.add(urljoin(page_url, tag["src"]))

        # Images
        for tag in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                if tag.get(attr):
                    assets.add(urljoin(page_url, tag[attr]))
            # srcset
            if tag.get("srcset"):
                for part in tag["srcset"].split(","):
                    src = part.strip().split()[0]
                    if src:
                        assets.add(urljoin(page_url, src))

        # Video / audio
        for tag in soup.find_all(["video", "audio", "source"]):
            if tag.get("src"):
                assets.add(urljoin(page_url, tag["src"]))

        # Favicon + icons
        for tag in soup.find_all("link", rel=lambda r: r and any(x in r for x in ("icon", "apple-touch-icon", "manifest"))):
            if tag.get("href"):
                assets.add(urljoin(page_url, tag["href"]))

        # OG / meta images
        for tag in soup.find_all("meta", property=lambda p: p and "image" in p):
            if tag.get("content"):
                assets.add(urljoin(page_url, tag["content"]))

        # Inline style background images
        for tag in soup.find_all(style=True):
            for u in re.findall(r'url\(["\']?(.*?)["\']?\)', tag["style"]):
                if u and not u.startswith("data:"):
                    assets.add(urljoin(page_url, u))

        # Filter to valid URLs only
        return [a for a in assets if a.startswith(("http://", "https://"))]

    def _collect_pages(self, soup: BeautifulSoup, page_url: str) -> list:
        pages = []
        for tag in soup.find_all("a", href=True):
            full, _ = urldefrag(urljoin(page_url, tag["href"]))
            p = urlparse(full)
            if p.netloc == self.base_domain and p.scheme in ("http", "https"):
                pages.append(full)
        return pages

    # ──────────────────────────────────────────
    # Asset downloading
    # ──────────────────────────────────────────

    def _download_asset(self, url: str) -> Path | None:
        local_path = self._url_to_local_path(url)
        if local_path.exists():
            return local_path

        resp = self._fetch(url, stream=True)
        if not resp:
            return None

        local_path.parent.mkdir(parents=True, exist_ok=True)
        content_type = resp.headers.get("Content-Type", "")
        is_text = any(t in content_type for t in ("text/", "javascript", "json", "xml", "font"))

        try:
            if is_text:
                content = resp.text
                # If it's CSS, parse and download assets referenced inside it
                if "css" in content_type:
                    content = self._process_css(content, url)
                local_path.write_text(content, encoding="utf-8", errors="replace")
            else:
                with open(local_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

            self._log(f"  ✓ {url.split('/')[-1] or 'index'}", level=2)
            return local_path
        except Exception as e:
            self.failed.append({"url": url, "error": str(e)})
            return None

    def _process_css(self, css_content: str, css_url: str) -> str:
        """Download assets referenced inside a CSS file and rewrite their URLs."""
        def replace_url(match):
            raw = match.group(1).strip("\"'")
            if raw.startswith("data:") or raw.startswith("#"):
                return match.group(0)
            full_asset_url = urljoin(css_url, raw)
            local_path = self._url_to_local_path(full_asset_url)
            if full_asset_url not in self.downloaded_assets:
                self._download_asset(full_asset_url)
                self.downloaded_assets.add(full_asset_url)
            # Make relative to the CSS file location
            css_local = self._url_to_local_path(css_url)
            try:
                rel = Path(local_path).relative_to(self.output_dir)
                css_rel = Path(css_local).relative_to(self.output_dir)
                rel_path = "../" * (len(css_rel.parts) - 1) + str(rel).replace("\\", "/")
                return f"url('{rel_path}')"
            except ValueError:
                return match.group(0)

        return re.sub(r'url\((["\']?[^)]+["\']?)\)', replace_url, css_content)

    # ──────────────────────────────────────────
    # HTML rewriting
    # ──────────────────────────────────────────

    def _rewrite_html(self, soup: BeautifulSoup, page_url: str):
        """Rewrite all asset/link references in HTML to local relative paths."""
        page_local = self._url_to_local_path(page_url)
        page_dir = page_local.parent

        def to_rel(url: str) -> str | None:
            if not url or url.startswith(("data:", "#", "mailto:", "tel:", "javascript:")):
                return None
            full = urljoin(page_url, url)
            p = urlparse(full)
            if p.scheme not in ("http", "https"):
                return None
            asset_local = self._url_to_local_path(full)
            try:
                return str(Path(asset_local).relative_to(page_dir)).replace("\\", "/")
            except ValueError:
                return None

        # Rewrite tag attributes
        rewrites = [
            ("link", "href"),
            ("script", "src"),
            ("img", "src"),
            ("source", "src"),
            ("video", "src"),
            ("audio", "src"),
        ]
        for tag_name, attr in rewrites:
            for tag in soup.find_all(tag_name, **{attr: True}):
                rel = to_rel(tag[attr])
                if rel:
                    tag[attr] = rel

        # img srcset
        for tag in soup.find_all("img", srcset=True):
            parts = []
            for part in tag["srcset"].split(","):
                bits = part.strip().split()
                if bits:
                    rel = to_rel(bits[0])
                    if rel:
                        bits[0] = rel
                    parts.append(" ".join(bits))
            tag["srcset"] = ", ".join(parts)

        # Internal page links
        for tag in soup.find_all("a", href=True):
            full, fragment = urldefrag(urljoin(page_url, tag["href"]))
            p = urlparse(full)
            if p.netloc == self.base_domain:
                rel = to_rel(full)
                if rel:
                    tag["href"] = rel + (f"#{fragment}" if fragment else "")

        # Inline style background images
        for tag in soup.find_all(style=True):
            def rewrite_style_url(m):
                raw = m.group(1).strip("\"'")
                rel = to_rel(raw)
                return f"url('{rel}')" if rel else m.group(0)
            tag["style"] = re.sub(r'url\(["\']?(.*?)["\']?\)', rewrite_style_url, tag["style"])

    # ──────────────────────────────────────────
    # Save HTML
    # ──────────────────────────────────────────

    def _save_html(self, html: str, page_url: str):
        local_path = self._url_to_local_path(page_url)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(html, encoding="utf-8")
        self._log(f"  ✓ Saved page → {local_path.relative_to(self.output_dir)}", level=2)

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _url_to_local_path(self, url: str) -> Path:
        p = urlparse(url)
        path = p.path.rstrip("/") or "/index"
        # Add .html if no extension
        if not Path(path).suffix:
            path = path + "/index.html"
        # Hash query string into filename if present
        if p.query:
            stem = Path(path).stem
            ext = Path(path).suffix
            qhash = hashlib.md5(p.query.encode()).hexdigest()[:6]
            path = str(Path(path).parent / f"{stem}_{qhash}{ext}")

        return self.output_dir / p.netloc / path.lstrip("/")

    def _fetch(self, url: str, stream: bool = False, timeout: int = 15):
        try:
            resp = self.session.get(url, timeout=timeout, allow_redirects=True, stream=stream)
            resp.raise_for_status()
            return resp
        except Exception as e:
            self.failed.append({"url": url, "error": str(e)})
            self._log(f"  ✗ Failed {url} — {e}", level=2)
            return None

    def _log(self, msg: str, level: int = 1):
        if self.verbose and level == 1:
            print(msg)
        elif self.verbose and level == 2:
            print(msg)


# ──────────────────────────────────────────
# Standalone usage
# ──────────────────────────────────────────

def clone_site(url: str, output_dir: str, max_pages: int = 20) -> dict:
    cloner = SiteCloner(url, output_dir, max_pages)
    result = cloner.clone()
    print(f"\nDone — {result['pages']} pages, {result['assets']} assets → {result['output_dir']}")
    if result["failed"]:
        print(f"  {result['failed']} assets failed (check network or bot protection)")
    return result
