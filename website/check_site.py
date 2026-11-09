#!/usr/bin/env python3
"""Validate static HTML files, internal links, and section anchors."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import sys

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.targets = []
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        value = fields.get("id")
        if value:
            if value in self.ids:
                self.duplicates.append(value)
            self.ids.add(value)
        if tag in ("a", "link") and fields.get("href"):
            self.targets.append(fields["href"])
        if tag == "script" and fields.get("src"):
            self.targets.append(fields["src"])

def load(path):
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    return page

def main():
    root = Path(__file__).resolve().parent
    pages = sorted(root.rglob("*.html"))
    if not pages:
        print("No HTML pages")
        return 1
    cache = {p.resolve(): load(p) for p in pages}
    errors = []
    for page, doc in cache.items():
        for duplicate in doc.duplicates:
            errors.append(f"{page.name}: duplicate anchor {duplicate}")
        for raw in doc.targets:
            url = urlsplit(raw)
            if url.scheme or url.netloc or raw.startswith("//"):
                continue
            path = (page.parent / unquote(url.path)).resolve() if url.path else page
            try:
                path.relative_to(root)
            except ValueError:
                errors.append(f"{page.name}: path escapes site {raw}")
                continue
            if path.is_dir():
                path = path / "index.html"
            if not path.is_file():
                errors.append(f"{page.name}: missing file {raw}")
                continue
            if url.fragment and path.suffix == ".html":
                target = cache.get(path) or load(path)
                if unquote(url.fragment) not in target.ids:
                    errors.append(f"{page.name}: missing anchor {raw}")
    for issue in errors:
        print("FAIL:", issue)
    print(f"Validated {len(pages)} pages, {len(errors)} errors")
    return int(bool(errors))

if __name__ == "__main__":
    sys.exit(main())
