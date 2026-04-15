import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from agent import run_agent


def main():
    parser = argparse.ArgumentParser(
        description="Website Cloner Agent — clone any website to a local folder"
    )
    parser.add_argument("url", nargs="?", help="URL of the website to clone")
    parser.add_argument(
        "-o", "--output",
        help="Output directory (default: ./cloned/<domain>)",
        default=None,
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=20,
        help="Maximum number of pages to crawl (default: 20)",
    )

    args = parser.parse_args()

    # Verify API key is set
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY is not set. Add it to your .env file.")
        sys.exit(1)

    # Interactive mode if no URL given
    if not args.url:
        print("Website Cloner Agent")
        print("=" * 40)
        url = input("Enter the URL to clone: ").strip()
        if not url:
            print("No URL provided. Exiting.")
            sys.exit(1)
    else:
        url = args.url

    # Normalize URL
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Determine output directory
    if args.output:
        output_dir = args.output
    else:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace(":", "_")
        output_dir = str(Path("cloned") / domain)

    output_dir = str(Path(output_dir).resolve())
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    user_message = (
        f"Clone the website at {url}. "
        f"Save everything to the output directory: {output_dir}. "
        f"Crawl up to {args.pages} pages."
    )

    run_agent(user_message)


if __name__ == "__main__":
    main()
