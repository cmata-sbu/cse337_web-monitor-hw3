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
    
    :param title: Title of the website which will appear in the .md filename
    :type title: str
    :return: Returns a .md filename to use when saving the file.
    :rtype: str
    """

    # Keep only alphanumerics and spaces
    safe_txt = re.sub(r"[^A-Za-z0-9 ]+", " ", title)

    # Collapse multiple spaces -> 1 underscore, strip, and cast to lowercase
    safe_txt = re.sub(r"\s+", "_", safe_txt.strip().lower())

    # Append date-time stamp in the same format used for the archive
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    return f"{safe_txt}_{timestamp}.md"

def should_download(download_date: str, today:datetime.date) -> bool:
    """
    Rwturn True if `download_date` is on or before `today`.
    Dates are in ISO format YYYY-MM-DD
    
    :param download_date: Date of the HTML file download
    :type download_date: str
    :param today: Today's Date
    :type today: datetime.date
    :rtype: bool
    """

    try:
        target = datetime.datetime.strptime(download_date, "%Y-%m-%d").date()
    except ValueError:
        logging.error(f"Invalid date format: {download_date}")
        return False
    return target <= today

def download_page(url: str) -> str:
    """
    Fetch the HTML content of a URL, which will be returned in a raw HTML string.
    Will handle HTTP errors by printing an error message to stderr with the HTTP status code
    
    :param url: Desired webpage URL for download
    :type url: str
    :return: raw HTML string
    :rtype: str
    """
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.text
    except requests.HTTPError as http_err:
        # Page is unreachable - log status and keep going
        print(f"Error fetching {url}: HTTP {http_err.response.status_code}", file=sys.stderr)
        return None
    except requests.RequestException as req_err:
        # Network problems (DNS, timeout, etc.)
        print(f"Error fetching {url}: {req_err}", file=sys.stderr)
        return None

    

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

    # Process each row
    for title, url, dl_date in rows:
        if not should_download(dl_date, date):
            logging.info(f"Skipping {url} - scheduled for future...")
            continue

        html = download_page(url)
        if html is None:
            continue

        md_text = html_to_markdown(html)
        md_file = md_dir / title_to_md_filename(title)
        write_markdown(md_file, md_text)

    # Finally, create the archive


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
