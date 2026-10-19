"""Send the reference Jev request from docs/jev_example.md and print the raw reply.

The URL and JSON body are read from the curl command in docs/jev_example.md and
the body is sent byte for byte, so the request cannot drift from the doc. The
key comes from BEATAPI_API_KEY in .env and is never printed.

Usage: uv run python scripts/check_jev.py [--save PATH]
"""

import argparse
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "jev_example.md"


def read_example():
    text = EXAMPLE.read_text(encoding="utf-8")
    url = re.search(r"curl\s+(https://\S+)", text)
    body = re.search(r"-d\s+'(.*?)'", text, re.DOTALL)
    if not url or not body:
        sys.exit("could not find the curl URL and -d body in %s" % EXAMPLE)
    return url.group(1), body.group(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", type=Path, help="also write the raw response body to this file")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get("BEATAPI_API_KEY")
    if not key:
        sys.exit("missing in .env: BEATAPI_API_KEY")

    url, body = read_example()
    resp = requests.post(
        url,
        data=body.encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        timeout=60,
    )
    print("HTTP", resp.status_code)
    print(resp.text)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_bytes(resp.content)


if __name__ == "__main__":
    main()
