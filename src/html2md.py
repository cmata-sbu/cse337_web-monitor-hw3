#!/usr/bin/env python3
"""
html2md: Download a list of URLs, convert the HTML to Markdown,
and pack all Markdown files into a .tar.gz archive

Usage: 
    ./src/html2md.py source_file output_dir
"""

import os, re, sys, logging
import argparse, csv, tarfile, shutil
import datetime as DateTime
from pathlib import Path
from urllib.parse import urlparse, unquote

import requests
from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from typing import cast
import hashlib

# Helps with casting
InlineNode = Tag | NavigableString

# global variable for date/time when program executes
now = DateTime.datetime.now()

# Title Helpers

def title_convertor(title: str) -> str:
    safe_txt = re.sub(r"[^A-Za-z0-9 ]+", " ", title)
    safe_txt = re.sub(r"\s+", "_", safe_txt.strip().lower())
    return safe_txt

def md_filename_with_md5_hash(title: str, url: str) -> str:
    """
    Transform a page title into a safe Markdown filename.
    Lower-case, replace non-alphanumerics with underscores,
    strip leading/trailing
    
    :param title: Title of the website which will appear in the .md filename
    :type title: str
    :param url: url of website for md5 hash to be retrived for
    :return: Returns a .md filename to use when saving the file.
    :rtype: str
    """
    safe_name = title_convertor(title)
    md5_txt = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{safe_name}_{md5_txt}.md"

# Title Helpers END

def should_download(download_date: str) -> bool:
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
        target = DateTime.datetime.strptime(download_date, "%Y-%m-%d").date()
    except ValueError:
        logging.error(f"Invalid date format: {download_date}")
        return False
    return target.toordinal() <= now.today().toordinal()

def download_page(url: str) -> str | None:
    """
    Fetch the HTML content of a URL, which will be returned in a raw HTML string.
    Will handle HTTP errors by printing an error message to stderr with the HTTP status code
    
    :param url: Desired webpage URL for download
    :type url: str
    :return: raw HTML string
    :rtype: str
    """

    parsed = urlparse(url)
    if parsed.scheme == "file":
        # This is a local file
        try:
            local_path = unquote(parsed.path)
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            print(f"Error reading local file {url}: {e}", file=sys.stderr)
            return None

    headers = {
        "User-Agent": (
            "html2mdCrawler/1.0 "
            "(christopher.mata@stonybrook.edu)"
        )
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
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

# Markdown Helpers Start
def _escape_markdown(text: str) -> str:
    """
    This method converts HTML text that may have a special meaning in Markdown when used literally
    inside inline code or plain text. This keeps the output readable.
    
    :param text: input text to be converted
    :type text: str
    :return: cnverted -> markdown string
    :rtype: str
    """
    return text.replace('\\', '\\\\')

def _format_inline(node: Tag | NavigableString, list_indent: int = 0) -> str:
    """
    Recursively convert a node (OR its children) into Markdown.
    This method handles the following elements:
        * bold (strong, b)
        * italics (em, i)
        * bold+italics (strong/em or em/strong)
        * code (code)
        * link (a)
    
    :param node: HTML block
    :type node: Tag | NavigableString
    :param list_indent: list indentation depth
    :type list_indent: int
    :return: Markdown text
    :rtype: str
    """

    if isinstance(node, NavigableString):
        return _escape_markdown(str(node))
    
    # Build the markdown representation of the current tag
    md = ""

    match node.name:
        case "strong" | "b":
            inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
            md += f"**{inner}**"
        case "em" | "i":
            inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
            md += f"*{inner}*"
        case "code":
            # Inline code - surround it with single backticks
            inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
            md += f"`{inner}`"
        case "a":
            # Link = [text](href)
            href = node.get("href")
            if not href:
                # Display as plaintext
                inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
                md += inner
            else:
                inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
                md += f"[{inner}]({href})"
        case _:
            md += "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
    
    return md

def _format_heading(tag: Tag, depth: int) -> str:
        """
        Convert <h1>-<h6> into Markdown headings.
        For h1 this method will use the heading that comes from the <title> (or <h1>) as the top-level title.
        
        :param tag: HTML block w/ tag (<h1>-<h6>)
        :type tag: Tag
        :param depth: Header depth (size)
        :type depth: int
        :return: formatted header in markdown
        :rtype: str
        """

        level = depth
        if level > 6:
            level = 6
        prefix = "#" * level
        inner = "".join(_format_inline(cast(InlineNode, c)) for c in tag.contents).strip()
        return f"{prefix} {inner}\n\n"

def _format_paragraph(p: Tag, list_indent: int = 0) -> str:
    """
    Convert a <p> element (and its children) to Markdown paragraph text.
    This method adds a blank line before/after the paragraph.
    
    :param p: HTML block w/ tag (<p>)
    :type p: Tag
    :param list_indent: Depth of list containment (0 if no list)
    :type list_indent: int
    :return: Markdown formatted paragraph text
    :rtype: str
    """

    text = _format_inline(p, list_indent).strip()
    if not text:
        return ""
    return f"{text}\n\n"

def _format_list_item(li: Tag, depth: int, list_type: str, list_indent: int, index: int | None) -> str:
    """
    Convert a <li> into Markdown list syntax.
    This method supports nesting up to 3 levels...
    
    :param li: HTML block w/ list-type tag
    :type li: Tag
    :param depth: Level of nesting for 
    :type depth: int
    :param list_type: Description
    :type list_type: str
    :param list_indent: Description
    :type list_indent: int
    :return: Description
    :rtype: str
    """

    if depth <= 0: depth = 1

    inline_parts: list[str] = []
    nested_parts: list[str] = []

    for child in li.contents:
        # Nested lists inside this <li>
        if isinstance(child, Tag) and child.name in ("ul", "ol"):
            nested_parts.append(
                _format_block(child, depth + 1, list_indent=list_indent + 2)
            )
        else:
            # Regular inline content of the final item
            inline_parts.append(
                _format_inline(cast(InlineNode, child), list_indent)
            )

    text = "".join(inline_parts).strip()

    # Base indentation for this level
    indent_spaces = " " * list_indent

    if list_type == "ul":
        marker = "- "
    else:
        marker = f"{index}. " if index is not None else "1. "

    if not text and not nested_parts:
        return ""

    lines = [f"{indent_spaces}{marker}{text}\n"]
    lines.extend(nested_parts)
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"

def _format_blockquote(bq: Tag, depth: int = 0, list_indent: int = 0) -> str:
    """
    Conver a <blockquote> into Markdown.
    Prefix every line with "> ".

    :param bq: HTML block with <blockquote> tag
    :type bq: Tag
    :param list_indent: Passed around list_indent val
    :type list_indent: int
    :return: Markdown formatted blockquote.
    :rtype: str
    """

    inner_lines = []
    for child in bq.contents:
        # re-use block format to make nested blockquotes
        inner = _format_block(cast(InlineNode, child), depth + 1, list_indent)
        if inner: inner_lines.append(inner.rstrip("\n"))

    if not inner_lines: return ""

    # Flatten and prefix each line with "> "
    text = "\n".join(inner_lines)
    quote_added_text = "\n".join("> " + line for line in text.splitlines())

    return quote_added_text + "\n\n"

def _format_codeblock(code_block: Tag, list_indent: int = 0) -> str:
    """
    Convert a <pre><code> or <code> (multiline) block nto a fenced code block.
    
    :param code_block: Description
    :type code_block: Tag
    :param list_indent: Description
    :type list_indent: int
    :return: Description
    :rtype: str
    """

    raw_text = code_block.get_text("\n", strip=False)
    raw_text = raw_text.rstrip("\n")

    indent = " " * list_indent

    # Build a fenced code block, then indent each line
    lines = raw_text.splitlines()
    fenced = ["```"] + lines + ["```"]

    indented_block = "\n".join(
        indent + line if line else indent for line in fenced
    )

    return f"\n{indented_block}\n\n"

def _format_block(node: Tag | NavigableString, depth: int = 0, list_indent: int = 0) -> str:
    """
    This method recursively walks block-level elements (headings, paragraphs, lists,
    blockquotes, code blocks, etc.) and then converts them to markdown.
    
    :param node: node of HTML to be formatted
    :type node: Tag | NavigableString
    :param depth: depth in nested list (0 = top-level container)
    :type depth: int
    :param list_indent: how many spaces to indent the bullet/number at this level
    :type list_indent: int
    :return: Markdown converted text
    :rtype: str
    """

    if isinstance(node, NavigableString):
        text = str(node).strip()
        return text + "\n\n" if text else ""
    
    md = ""

    match node.name:
        case "h1" | "h2" | "h3" | "h4" | "h5" | "h6":
            level = int(node.name[1])
            md += _format_heading(node, level)
        case "p":
            md += _format_paragraph(node, list_indent)
        case "ul" | "ol":
            list_type = "ol" if node.name == "ol" else "ul"
            indent = 2 * depth
            # Process list items recursively
            for idx, li in enumerate(node.find_all("li", recursive=False), start=1):
                md += _format_list_item(li, depth=depth + 1, list_type=list_type, list_indent=indent, index=idx if list_type == "ol" else None)
            md += "\n"
        case "blockquote":
            md += _format_blockquote(node, depth, list_indent)
        case "pre" | "code":
            md += _format_codeblock(node, list_indent)
        case "a":
            # Deal with links if they are not part of an inline element
            href = node.get("href")
            inner = "".join(_format_inline(cast(InlineNode, c), list_indent) for c in node.contents)
            md += f"[{inner}]({href})" if href else inner
        case _:
            # Just recurse for any undefined type of tag
            for child in node.contents:
                md += _format_block(cast(InlineNode, child), depth, list_indent)

    return md
# 

def html_to_markdown(html: str) -> str | None:
    """
    Simple conversion:

    
    :param html: raw HTML string
    :type html: str
    :return: Markdown text
    :rtype: str
    :return: Return None if error (caller is expected to handle this)
    :rtype: None
    """

    # Parse HTML with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Grab the main content div
    main = soup.find("div", class_="mw-parser-output")
    if not main:
        print(f"Error finding main content div in article!", file=sys.stderr)
        return None
    
    # Markdown Page TITLE
    page_title_tag = soup.find("h1", id="firstHeading")

    # Remove everything that should be ignored #
    # Remove Hatnotes/References
    for sup in main.find_all("sup", class_="reference"):
        sup.decompose()
    for hat in main.find_all("div", class_="hatnote"):
        hat.decompose()

    # Remove edit links
    for edit in main.find_all("span", class_="mw-editsection"):
        edit.decompose()

    # Remove Nav/Maintenance Boxes
    for nav in main.find_all("div", class_="navbox"):
        nav.decompose()
    for nav in main.find_all("div", class_="navbox-inner"):
        nav.decompose()
    for nav in main.find_all("div", class_="navbox-data"):
        nav.decompose()

    # Remove Tables & infoboxes & ToC
    for tbl in main.find_all("table"):
        tbl.decompose()

    toc = main.find("div", id="toc")
    if toc: toc.decompose()

    # Remove Images & figures
    for img in main.find_all(["img", "figure"]):
        img.decompose()

    # Remove Math
    for math in main.find_all(["math", "mml", "mathml"]):
        math.decompose()

    # Remove references at end
    for refL in main.find_all("div", class_="reflist"):
        refL.decompose()
    for refB in main.find_all("div", class_="refbegin"):
        refB.decompose()

    # Remove any extern links
    for h2 in main.find_all("h2"):
        span = h2.find("span", id="External_links")
        if span or (h2.get_text(strip=True).lower() == "external links"):
            # remove h2 and all siblings until next h2
            next = h2.next_sibling
            h2.decompose()

            while next:
                current = next
                next = next.next_sibling
                if isinstance(current, Tag) and current.name == "h2":
                    break
                if isinstance(current, Tag):
                    current.decompose()
            break


    markdown_parts = []

    if page_title_tag:
        title_txt = page_title_tag.get_text(strip=True)
        markdown_parts.append(f"# {title_txt}\n\n")

    for child in main.contents:
        part = _format_block(cast(InlineNode, child))
        if part:
            markdown_parts.append(part)

    # Join the parts & return it
    markdown = "".join(markdown_parts).strip()
    return markdown

# main driver function
def main(csv_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    # Make a temp dir for the created Markdown files
    md_dir = Path(output_dir / "tmp_md")
    md_dir.mkdir(parents=True, exist_ok=True)

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

    # Process each row
    for title, url, dl_date in rows:
        if not should_download(dl_date):
            logging.info(f"Skipping {url} - scheduled for future...")
            continue

        html = download_page(url)
        if html is None:
            continue

        md_text = html_to_markdown(html)
        md_file = md_dir / md_filename_with_md5_hash(title, url)

        if md_text is None: continue

        header = f"<!-- title: {title} -->\n<-- url: {url} -->\n\n"
        with md_file.open("w", encoding="utf-8") as f:
            f.write(header + md_text)

    # If no markdown folders were made, bail out
    md_files = list(md_dir.glob("*.md"))
    if not md_files:
        print("No markdown files created; no archive generated.", file=sys.stderr)
        return
    
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    archive_path = output_dir / f"{timestamp}.tar.gz"

    with tarfile.open(archive_path, "w:gz") as tar:
        for mf in md_files:
            tar.add(mf, arcname=mf.name)

    # Clean up tempdir
    shutil.rmtree(md_dir)


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
