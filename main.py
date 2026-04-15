"""
main.py — Website Cloner unified CLI

Modes:
  clone        Clone any website to a local folder
  build        Generate a new website from a text prompt
  deploy       Push a local folder to GitHub Pages (free live URL)
  clone-deploy Clone a website, rewrite copy for a new brand, deploy live

Usage:
  python main.py clone https://example.com
  python main.py build "limo company, luxury dark theme"
  python main.py deploy ./cloned/example.com --repo my-site
  python main.py clone-deploy https://example.com "my new brand description"

Options:
  --output, -o    Output directory
  --pages, -p     Max pages to crawl (default: 20)
  --repo          GitHub repo name for deploy
  --domain        Custom domain for deploy (e.g. mysite.com)
  --images        Folder of images to use when building
  --colors        Brand colors for build (e.g. "#1a1a2e, #e94560")
  --name          Project name (used as folder name and repo name)
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser(
        description="Website Cloner — clone, build, and deploy websites",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # ── clone ──────────────────────────────────────────
    p_clone = subparsers.add_parser("clone", help="Clone any website to a local folder")
    p_clone.add_argument("url", help="URL to clone")
    p_clone.add_argument("-o", "--output", help="Output directory (default: ./cloned/<domain>)")
    p_clone.add_argument("-p", "--pages", type=int, default=20, help="Max pages to crawl (default: 20)")

    # ── build ──────────────────────────────────────────
    p_build = subparsers.add_parser("build", help="Generate a new website from a text prompt")
    p_build.add_argument("description", help="Description of the website to build")
    p_build.add_argument("-o", "--output", help="Output directory")
    p_build.add_argument("--name", help="Project name (used as folder name)")
    p_build.add_argument("--images", help="Folder containing images/videos to use")
    p_build.add_argument("--colors", help='Brand colors e.g. "#1a1a2e, #e94560"')

    # ── deploy ─────────────────────────────────────────
    p_deploy = subparsers.add_parser("deploy", help="Deploy a local folder to GitHub Pages")
    p_deploy.add_argument("folder", help="Local folder to deploy")
    p_deploy.add_argument("--repo", help="GitHub repo name (default: folder name)")
    p_deploy.add_argument("--domain", help="Custom domain (e.g. mysite.com)")

    # ── clone-deploy ───────────────────────────────────
    p_cd = subparsers.add_parser(
        "clone-deploy",
        help="Clone a website, rewrite copy for a new brand, deploy to GitHub Pages",
    )
    p_cd.add_argument("url", help="URL to clone")
    p_cd.add_argument("brand", help="New brand description for copy rewrite")
    p_cd.add_argument("--repo", help="GitHub repo name")
    p_cd.add_argument("--domain", help="Custom domain")
    p_cd.add_argument("-p", "--pages", type=int, default=20, help="Max pages to crawl (default: 20)")

    args = parser.parse_args()

    # ── Execute modes ──────────────────────────────────

    if args.mode == "clone":
        from cloner import clone_site
        url = _normalize_url(args.url)
        output = args.output or _default_clone_dir(url)
        clone_site(url, output, args.pages)

    elif args.mode == "build":
        from builder import build_site
        name = args.name or _slug(args.description[:40])
        output = args.output or f"./built/{name}"
        build_site(
            description=args.description,
            output_dir=output,
            image_source_dir=args.images,
            brand_colors=args.colors or "",
        )
        print(f"\nTo deploy: python main.py deploy {output} --repo {name}")

    elif args.mode == "deploy":
        from deployer import deploy_site
        deploy_site(
            site_dir=args.folder,
            repo_name=args.repo,
            custom_domain=args.domain,
        )

    elif args.mode == "clone-deploy":
        from cloner import clone_site
        from rewriter import rewrite_site
        from deployer import deploy_site

        url = _normalize_url(args.url)
        domain = urlparse(url).netloc
        clone_dir = f"./cloned/{domain}"

        print(f"\n{'='*50}")
        print("STEP 1/3 — Cloning website")
        print('='*50)
        result = clone_site(url, clone_dir, args.pages)

        # Find the actual cloned subfolder (cloner saves under domain subfolder)
        cloned_site_dir = str(Path(clone_dir) / domain)
        if not Path(cloned_site_dir).exists():
            # Fallback to clone_dir if no subfolder
            cloned_site_dir = clone_dir

        print(f"\n{'='*50}")
        print("STEP 2/3 — Rewriting copy for new brand")
        print('='*50)
        rewrite_site(cloned_site_dir, args.brand)

        print(f"\n{'='*50}")
        print("STEP 3/3 — Deploying to GitHub Pages")
        print('='*50)
        repo_name = args.repo or _slug(args.brand[:40])
        deploy_result = deploy_site(
            site_dir=cloned_site_dir,
            repo_name=repo_name,
            custom_domain=args.domain,
            commit_message=f"Clone-deploy: {args.brand[:60]}",
        )

        print(f"\n{'='*50}")
        print("ALL DONE")
        print('='*50)
        print(f"  Live URL: {deploy_result['live_url']}")
        print(f"  Repo:     {deploy_result['repo_url']}")


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def _default_clone_dir(url: str) -> str:
    domain = urlparse(url).netloc
    return f"./cloned/{domain}"


def _slug(text: str) -> str:
    import re
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', text.lower())
    slug = re.sub(r'\s+', '-', slug.strip())
    return slug[:50]


if __name__ == "__main__":
    main()
