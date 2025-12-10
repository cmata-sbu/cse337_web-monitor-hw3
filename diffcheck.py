#!/usr/bin/env python3
"""
diffcheck: Compare markdown archives from N days ago vs today

Usage:
    ./diffcheck.py N output_dir

- N: non-negative integer, which is the number of days to look back.
- output-dir: directory that contains the .tar.gz for comparison
"""

import re, sys, argparse, logging
import tarfile, tempfile
import difflib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

ARCHIVE_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.tar.gz$")

@dataclass
class PageInfo:
    path: Path
    title: str
    url:str

def find_latest_archive_for_date(outdir: Path, target_date: date) -> Path | None:
    """
    Among the archives in the outdir with the correct format,
    return the newest one whose date  is equal to the target date (or None)
    """
    possible_matches: list[tuple[datetime, Path]] = []

    for p in outdir.glob("*.tar.gz"):
        m = ARCHIVE_REGEX.match(p.name)
        if not m: continue

        date_str, time_str = m.groups()
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
            time = datetime.strptime(time_str, "%H-%M-%S").time()
        except ValueError: continue # Skip malformed names

        if date == target_date: possible_matches.append((datetime.combine(date, time), p))

    if not possible_matches: return None
    possible_matches.sort(key=lambda pair: pair[0])
    return possible_matches[-1][1]

def extract_archive(arch_path: Path, dst_dir: Path) -> None:
    with tarfile.open(arch_path, "r:gz") as tar:
        tar.extractall(path=dst_dir)

def parse_header_info(md_path: Path) -> tuple[str, str]:
    """
    Parse the first couple lines of a markdown file to find information about it
    Return (title, url). Falls back to default if the info is not present
    """
    title = ""
    url = ""

    try:
        with md_path.open("r", encoding="utf-8") as f:
            for _ in range(10):
                line = f.readline()
                if not line: break

                stripped = line.strip()
                md_title = re.match(r"<!--\s*title:\s*(.*?)\s*-->", stripped)
                if md_title:
                    title = md_title.group(1)
                    continue

                md_url = re.match(r"<!--\s*url:\s*(.*?)\s*-->", stripped)
                if md_url:
                    url = md_url.group(1)
                    continue

                if not stripped.startswith("<!--"): break
    except OSError:
        # If file is unreadable, fall below
        pass

    if not title: title = md_path.stem
    if not url: url = "unknown-url"

    return title, url

def collect_pages(root_dir: Path) -> Dict[str, PageInfo]:
    """
    Scan the root_dir for .md files and build a mapping: 
    
        filename -> PageInfo(path, title, url)
    """
    pages: Dict[str, PageInfo] = {}

    for md_path in root_dir.glob("*.md"):
        title, url = parse_header_info(md_path)
        pages[md_path.name] = PageInfo(path=md_path, title=title, url=url)

    return pages

def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError: return ""

def content_differs(path_A: Path, path_B: Path) -> bool:
    """
    Return true if the two files differ in their markdown content, false otherwise.
    This method ignores whitespace differences.
    """

    raw_A = read_file(path_A)
    raw_B = read_file(path_B)
    norm_A = re.sub(r"\s+", " ", raw_A).strip()
    norm_B = re.sub(r"\s+", " ", raw_B).strip()

    # Use difflib to compare normalized strings
    matcher = difflib.SequenceMatcher(None, norm_A, norm_B)
    return matcher.ratio() < 1.0

def main(n: int, outdir) -> None:
    today = date.today()
    past_date = today - timedelta(days=n)

    # find archive from N days ago
    parchive = find_latest_archive_for_date(outdir, past_date)
    if parchive is None:
        print("Error: no archive from N days ago was found", file=sys.stderr)
        sys.exit(1)
    
    # Find archive for today
    tarchive = find_latest_archive_for_date(outdir, today)
    if tarchive is None:
        print("Error: no archives were created today (run html2md.py to create one)", file=sys.stderr)
        sys.exit(1)

    # extract both archives to temp dirs
    with tempfile.TemporaryDirectory(prefix="dc_past_") as pdir_str, tempfile.TemporaryDirectory(prefix="dc_today_") as tdir_str:
        pdir = Path(pdir_str)
        tdir = Path(tdir_str)

        extract_archive(parchive, pdir)
        extract_archive(tarchive, tdir)

        # Build page mappings, which are keyed by filename
        past_pages = collect_pages(pdir)
        today_pages = collect_pages(tdir)

        # Only pages that exist in both archives are comparable
        similar_filenames = sorted(set(past_pages.keys()) & set(today_pages.keys()))
        
        changed_pages: list[PageInfo] = []
        for fname in similar_filenames:
            pinfo = past_pages[fname]
            tinfo = past_pages[fname]

            if content_differs(pinfo.path, tinfo.path): changed_pages.append(tinfo)

        if not changed_pages:
            print(f"No changes in any web page content in the last {n} days were detected.")
            return
        
        print(f"The following web pages have been modified in the last {n} days:")
        for info in changed_pages: print(f"- {info.title} ({info.url})")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A script to compare markdown archive from N days ago vs today.")
    parser.add_argument("N", type=int,help="Number of days to look back.")
    parser.add_argument("output_dir", type=Path, help="Directory to compare archives from and save to.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    try:
        main(args.N, args.output_dir)
    except Exception as e:
        logging.exception(f"Unhandled Exception: {e}")
        sys.exit(1)