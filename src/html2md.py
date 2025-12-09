#!/usr/bin/env python3
"""
html2md: Download a list of URLs, convert the HTML to Markdown,
and pack all Markdown files into a .tar.gz archive
"""

import os, re, sys, logging
import argparse, csv, tarfile
import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

def title_to_md_filename(title: str) -> str:
    """
    Transform a page title into a safe Markdown filename.
    Lower-case, replace non-alphanumerics with underscores,
    strip leading/trailing
    
    :param title: Description
    :type title: str
    :return: Description
    :rtype: str
    """

# main driver function
def main(csv_path, output_dir):
    date = datetime.date.today()

    # Read the CSV file
    rows = []
    try:
        with csv_path.open(newline="", encoding="utf-8") as fp:
            reader = csv.reader(fp, delimiter="|")
            for row in reader:
                if len(row) != 3:
                    logging.warning(f"Skipped incorrectly formatted line: {row}")
                    continue
                title, url, download_date = row
                rows.append((title.strip(), url.strip(), download_date.strip()))
    except Exception as e:
        print(f"Error parsing CSV file {csv_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Make a temp dir for the created Markdown files
    md_dir = Path(output_dir / "tmp_md")
    md_dir.mkdir(parents=True, exist_ok=True)

    print(md_dir)

# main entry point
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download, convert, and archive web pages as Markdown."
    )
    parser.add_argument("csv_file", type=Path, help="Path to the pipe‑separated CSV")
    parser.add_argument("output_dir", type=Path, help="Directory to store the .tar.gz archive")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    try:
        main(args.csv_file, args.output_dir)
    except Exception as e:
        logging.exception(f"Unhandled Exception: {e}")
        sys.exit(1)
