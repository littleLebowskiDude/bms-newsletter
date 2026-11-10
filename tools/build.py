#!/usr/bin/env python3
"""Turn Beechworth Montessori School newsletter PDFs into data for the reader app.

    python tools/build.py                 # fetch the newest issues from the school website
    python tools/build.py --count 6       # keep the 6 newest issues
    python tools/build.py --pdf file.pdf  # build one local PDF (name it like the school does)

Output goes to public/data/: index.json plus one folder per issue holding
issue.json, extracted photos (img/) and a render of every original page (pages/).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import math
import re
import shutil
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image

LISTING_URL = "https://www.beechworthmontessori.vic.edu.au/newsletter/"
USER_AGENT = "Mozilla/5.0 (compatible; newsletter-reader)"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "public" / "data"
SCHEMA = 5  # bump to force every issue to be rebuilt

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
MONTH_RE = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DAY_RE = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day|sday|nesday|urday)?"
NAME_RE = re.compile(r"Week-(\d+)-Term-(\d+)-(\d{4})", re.I)


# ----------------------------------------------------------------- website

def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def describe(name: str, url: str = "") -> dict:
    """Work out which issue a PDF is from its file name."""
    m = NAME_RE.search(name)
    up = re.search(r"/uploads/(\d{4})/(\d{2})/", url)
    uploaded = [int(up[1]), int(up[2])] if up else [0, 0]
    if m:
        week, term, year = (int(x) for x in m.groups())
        return {"id": f"{year}-t{term}-w{week:02d}", "title": f"Term {term} Week {week}",
                "year": year, "term": term, "week": week, "sort": [year, term, week], "pdf": url}
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)
    return {"id": re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-"),
            "title": re.sub(r"[-_]+", " ", stem), "year": uploaded[0], "term": 0, "week": 0,
            "sort": [uploaded[0], 0, uploaded[1]], "pdf": url}


def list_issues() -> list[dict]:
    """Every newsletter PDF linked from the school's newsletter page, newest first."""
    page = fetch(LISTING_URL).decode("utf-8", "replace")
    found: dict[str, dict] = {}
    for url in re.findall(r'href="([^"]+\.pdf)"', page, re.I):
        url = html.unescape(url)
        name = url.rsplit("/", 1)[-1]
        if "newsletter" not in name.lower():
            continue
        issue = describe(name, url)
        if issue["id"] not in found or url > found[issue["id"]]["pdf"]:
            found[issue["id"]] = issue
    return sorted(found.values(), key=lambda i: i["sort"], reverse=True)


# ----------------------------------------------------------------- text model

def family(font: str) -> str:
    return re.split(r"[-,]", font)[0]


def read_lines(page) -> list[dict]:
    """Text lines of a page with per-span styling and link targets."""
    links = [(pymupdf.Rect(l["from"]), l["uri"]) for l in page.get_links() if l.get("uri")]
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_LIGATURES & ~pymupdf.TEXT_PRESERVE_IMAGES
    lines = []
    for block in page.get_text("dict", flags=flags)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            spans = []
            for s in line["spans"]:
                if not s["text"]:
                    continue
                rect = pymupdf.Rect(s["bbox"])
                uri = next((u for r, u in links if (r & rect).get_area() > 0.4 * rect.get_area() > 0), None)
                spans.append({
                    "text": s["text"], "size": round(s["size"], 1), "color": s["color"],
                    "family": family(s["font"]),
                    "bold": bool(s["flags"] & 16) or "bold" in s["font"].lower(),
                    "italic": bool(s["flags"] & 2) or "italic" in s["font"].lower(),
                    "sup": bool(s["flags"] & 1), "link": uri,
                })
            text = "".join(s["text"] for s in spans)
            if not text.strip():
                continue
            x0, y0, x1, y1 = line["bbox"]
            x1 = x0 + (x1 - x0) * len(text.rstrip()) / len(text)  # ignore trailing padding
            inked = [s for s in spans if s["text"].strip()]
            lines.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "spans": spans, "inked": inked,
                          "text": text, "block": block["number"],
                          "size": max(s["size"] for s in inked)})
    # pieces of one visual line sometimes arrive separately; stitch them back together
    lines.sort(key=lambda l: (l["block"], round(l["y0"] / 3), l["x0"]))
    merged: list[dict] = []
    for l in lines:
        p = merged[-1] if merged else None
        if p and p["block"] == l["block"] and abs(p["y0"] - l["y0"]) < 3 and l["x0"] >= p["x1"] - 2:
            p["spans"] += [{**l["spans"][0], "text": " "}] + l["spans"]
            p["inked"] += l["inked"]
            p["text"] += " " + l["text"]
            p["x1"], p["y1"] = l["x1"], max(p["y1"], l["y1"])
        else:
            merged.append(l)
    return merged


def is_greyish(color: int) -> bool:
    r, g, b = color >> 16 & 255, color >> 8 & 255, color & 255
    return max(r, g, b) - min(r, g, b) < 28


def tone(color: int, bold: bool = True) -> str | None:
    """Reduce an arbitrary text colour to plain / highlighted / warning."""
    r, g, b = color >> 16 & 255, color >> 8 & 255, color & 255
    if r > 170 and g < 90 and b < 90 and bold:
        return "alert"
    return None if is_greyish(color) else "tint"


def inline(lines: list[dict], breaks: set[int] = frozenset(), plain_color: bool = False,
           strip: str | None = None, paragraphs: bool = False) -> str:
    """Render lines as one run of inline HTML, merging spans that share a style."""
    runs: list[list] = []
    for i, line in enumerate(lines):
        for s in line["spans"]:
            style = (s["bold"], s["italic"], s["sup"], s["link"], None if plain_color else tone(s["color"], s["bold"]))
            if s["link"]:
                style = style[:4] + (None,)
            text = re.sub(r"\s+", " ", s["text"])
            if runs and (runs[-1][1] == style or not text.strip()):
                runs[-1][0] += text
            else:
                runs.append([text, style])
        if i < len(lines) - 1:
            sep = " "
            if i in breaks:
                ends = re.search(r"[.!?][”’)\"']*\s*$", line["text"])
                heading_next = all(s["bold"] for s in lines[i + 1]["inked"])
                sep = "\f" if paragraphs and (ends or heading_next) else "\n"
            runs.append([sep, None])
    if strip and runs:
        runs[0][0] = re.sub(strip, "", runs[0][0], count=1)
    out = []
    for text, style in runs:
        t = html.escape(text, quote=False)
        if style is None or not text.strip():
            out.append(t)
            continue
        bold, italic, sup, link, tn = style
        lead = t[: len(t) - len(t.lstrip())]
        tail = t[len(t.rstrip()):]
        t = t.strip()
        if sup:
            t = f"<sup>{t}</sup>"
        if italic:
            t = f"<em>{t}</em>"
        if bold:
            t = f"<strong>{t}</strong>"
        if tn:
            t = f'<span class="{tn}">{t}</span>'
        if link:
            t = f'<a href="{html.escape(link)}" target="_blank" rel="noopener">{t}</a>'
        out.append(lead + t + tail)
    text = re.sub(r"[ \t]+", " ", "".join(out))
    for _ in range(4):  # neighbouring pieces with the same styling become one
        text = re.sub(r"</(strong|em)>( ?)<\1>", r"\2", text)
        text = re.sub(r'(<span class="(\w+)">(?:(?!</span>).)*)</span>( ?)<span class="\2">', r"\1\3", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "<br>", text)
    text = re.sub(r" ?\f ?", "\f", text)
    text = re.sub(r"(https?://[^\s<]+[^\s<.,;:!?)])(?![^<]*</a>)",
                  r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
    return text.strip()


def plain(lines: list[dict]) -> str:
    return re.sub(r"\s+", " ", " ".join(l["text"] for l in lines)).strip()


# ----------------------------------------------------------------- images

def save_image(doc, info: dict, dest: Path, max_side: int = 1600) -> tuple[int, int] | None:
    try:
        pix = pymupdf.Pixmap(doc, info["xref"])
        smask = doc.extract_image(info["xref"]).get("smask")
        if smask and not pix.alpha:
            pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
        if pix.colorspace is None or pix.colorspace.n != 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
    except Exception as e:  # an odd image should never sink the whole issue
        print(f"    skipped image {info['xref']}: {e}")
        return None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", img.size, "white"), img)
    img = img.convert("RGB")
    a, b = info["transform"][0], info["transform"][1]
    quarter = round(math.degrees(math.atan2(b, a)) / 90) % 4  # photos Word has turned on their side
    if quarter:
        img = img.rotate(-90 * quarter, expand=True)
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    img.save(dest, "WEBP", quality=80, method=5)
    return img.size


VIDEO_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s\"<]*&)?v=|embed/|shorts/|live/)|youtu\.be/)([\w-]{11})|vimeo\.com/(?:video/)?(\d+)")


def videos_in(lines: list[dict]) -> list[dict]:
    found, seen = [], set()
    urls = [s["link"] for l in lines for s in l["spans"] if s["link"]] + [l["text"] for l in lines]
    for u in urls:
        for m in VIDEO_RE.finditer(u):
            key = m[1] or m[2]
            if key not in seen:
                seen.add(key)
                found.append({"t": "video", "provider": "youtube" if m[1] else "vimeo", "id": key})
    return found


# ----------------------------------------------------------------- events

def event_date(text: str, year: int, month_hint: int) -> str | None:
    """Best guess at the (first) day an entry in the 'What's on' list refers to."""
    mon = re.search(r"\b" + MONTH_RE + r"\b", text, re.I)
    if not mon:
        return None
    month = MONTHS[mon[1][:3].lower()]
    before = text[: mon.start()]
    day = re.search(r"\b" + DAY_RE + r"\.?,?\s+(\d{1,2})\b", before, re.I)
    if not day:
        day = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s*$", before)
    if not day:
        return None
    if month < month_hint - 6:  # a January date in a December newsletter
        year += 1
    try:
        return dt.date(year, month, int(day[1])).isoformat()
    except ValueError:
        return None


# ----------------------------------------------------------------- extraction

def extract(pdf_path: Path, meta: dict, out: Path) -> dict:
    doc = pymupdf.open(pdf_path)
    (out / "img").mkdir(parents=True, exist_ok=True)
    (out / "pages").mkdir(exist_ok=True)

    pages = [read_lines(p) for p in doc]
    chars: Counter = Counter()
    for lines in pages:
        for l in lines:
            for s in l["inked"]:
                chars[(s["family"], s["size"])] += len(s["text"])
    body_family, body_size = chars.most_common(1)[0][0]

    def sig(line):
        s = line["inked"][0]
        return (s["family"], s["size"], s["color"])

    def uniform(line):
        return len({(s["family"], s["size"], s["color"]) for s in line["inked"]}) == 1

    # the running section title is the big coloured line at the top of most pages
    tops: Counter = Counter()
    for lines in pages[1:]:
        for l in lines:
            if l["y1"] < 60 and l["size"] >= body_size + 4 and uniform(l):
                tops[sig(l)] += 1
    section_sig = tops.most_common(1)[0][0] if tops else None

    def kind(line, block_len):
        text = line["text"].strip()
        if re.fullmatch(r"Page\s+\d+\s+of\s+\d+", text, re.I) or re.fullmatch(r"\d{1,3}", text) and line["y0"] > 700:
            return "footer"
        if section_sig and uniform(line) and sig(line) == section_sig:
            return "section"
        if (section_sig and all(s["family"] == section_sig[0] != body_family for s in line["inked"])
                and line["size"] >= body_size and len(text) < 120):
            return "h3"
        if (all(s["bold"] for s in line["inked"]) and len(text) < 90 and not text.endswith((".", ","))
                and (block_len == 1 or line["size"] >= body_size + 1) and line["size"] < body_size + 4):
            return "h4"
        return "body"

    issue = {**meta, "pageCount": len(doc), "events": [], "sections": [], "pages": []}
    sections: list[dict] = issue["sections"]
    current: dict | None = None
    img_count = 0

    def add(block: dict):
        nonlocal current
        if current is None:
            current = {"title": "Newsletter", "blocks": []}
            sections.append(current)
        last = current["blocks"][-1] if current["blocks"] else None
        if last and block["t"] in ("ol", "ul") and last["t"] == block["t"]:
            last["items"] += block["items"]
        elif (last and block["t"] == "p" and last["t"] == "p" and block.get("lead") == last.get("lead")
              and re.match(r"[a-z]", block["html"])
              and not re.search(r"[.!?:][”’)\"']*$", TAG_RE.sub("", last["html"]))):
            last["html"] += " " + block["html"]  # one paragraph the page layout split in two
        elif last and block["t"] == "gallery" and last["t"] == "gallery":
            last["images"] += block["images"]
        else:
            current["blocks"].append(block)

    for pno, page in enumerate(doc):
        W, H = page.rect.width, page.rect.height
        lines = pages[pno]
        by_block: dict[int, list] = {}
        for l in lines:
            by_block.setdefault(l["block"], []).append(l)
        for l in lines:
            l["kind"] = kind(l, len(by_block[l["block"]]))
        lines = [l for l in lines if l["kind"] != "footer"]

        # ---- front page: masthead and the "What's on" side column
        top_cut = 0.0
        if pno == 0:
            first = min((l["y0"] for l in lines if l["kind"] == "section"), default=None)
            # the side column sits left or right depending on the issue; find it by its headings
            anchors = [l for l in lines if re.search(r"what.?s on|term dates", l["text"], re.I)]
            side_x = min((l["x0"] for l in anchors), default=None)
            side = [l for l in lines if side_x is not None and abs(l["x0"] - side_x) < 25
                    and l["x1"] - l["x0"] < 0.3 * W and l["kind"] != "section"]
            if first is not None:
                top_cut = first
                head = [l for l in lines if l["y0"] < first - 4 or (l in side and l["y0"] < first + 6)]
                m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+" + MONTH_RE + r",?\s+(\d{4})", plain(head), re.I)
                if m:
                    issue["date"] = dt.date(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])).isoformat()
                lines = [l for l in lines if l not in head]
                side = [l for l in side if l not in head]
            if len(side) >= 4:
                lines = [l for l in lines if l not in side]
                groups: dict[int, list] = {}
                for l in side:
                    groups.setdefault(l["block"], []).append(l)
                year = int(issue.get("date", f"{meta.get('year') or dt.date.today().year}")[:4])
                month = int(issue["date"][5:7]) if "date" in issue else 6
                right = max(l["x1"] for l in side)
                for group in sorted(groups.values(), key=lambda g: g[0]["y0"]):
                    text = plain(group)
                    if re.search(r"term dates", text, re.I):
                        issue["termDates"] = re.sub(r"^.*?term dates:?\s*", "", text, flags=re.I)
                    elif len(group) == 1 and group[0]["size"] >= body_size + 2:
                        issue["events"].append({"heading": text.rstrip(":")})
                    else:
                        tones = Counter(tone(s["color"]) for l in group for s in l["inked"])
                        raw = max(group[0]["inked"], key=lambda s: len(s["text"]))["color"]
                        r, g, b = raw >> 16 & 255, raw >> 8 & 255, raw & 255
                        issue["events"].append({
                            "html": inline(group, short_breaks(group, right), plain_color=True),
                            "date": event_date(text, year, month),
                            "tone": "alert" if tones.most_common(1)[0][0] == "alert"
                                    else "end" if r > 200 and 120 < g < 200 and b < 120 else None,
                        })

        # ---- pictures on this page
        pics = []
        for info in page.get_image_info(xrefs=True):
            x0, y0, x1, y1 = info["bbox"]
            if not info["xref"] or min(x1 - x0, y1 - y0) < 40 or y1 <= top_cut:
                continue
            img_count += 1
            name = f"img/{img_count:03d}.webp"
            size = save_image(doc, info, out / name)
            if not size:
                continue
            big = (x1 - x0) >= 0.55 * W or (x1 - x0) * (y1 - y0) >= 0.22 * W * H
            pics.append({"src": name, "w": size[0], "h": size[1], "x0": x0, "y0": y0, "y1": y1,
                         "f": round((x1 - x0) / W, 2), "poster": big})
        row_h = 60
        pics.sort(key=lambda p: (round(p["y0"] / row_h), p["x0"]))

        def flush(before: float | None = None):
            nonlocal pics
            ready = [p for p in pics if before is None or p["y0"] < before]
            pics = [p for p in pics if p not in ready]
            for p in ready:
                ref = {k: p[k] for k in ("src", "w", "h", "f")}
                add({"t": "poster", **ref} if p["poster"] else {"t": "gallery", "images": [ref]})

        column_right = max((l["x1"] for l in lines), default=W)

        def right_edge(line):
            edge = column_right
            for p in pics_all:
                if p["x0"] > line["x0"] + 40 and p["y0"] < line["y1"] and p["y1"] > line["y0"]:
                    edge = min(edge, p["x0"])
            return edge

        pics_all = list(pics)

        # ---- text, in reading order
        blocks: dict[int, list] = {}
        for l in lines:
            blocks.setdefault(l["block"], []).append(l)
        for group in sorted(blocks.values(), key=lambda g: (round(min(l["y0"] for l in g)), g[0]["x0"])):
            group.sort(key=lambda l: (round(l["y0"] / 3), l["x0"]))
            i = 0
            while i < len(group):
                l = group[i]
                if l["kind"] == "section":
                    title = plain([l])
                    flush(l["y0"])
                    y = current.get("y") if current else None
                    if y and y[0] == pno and 0 <= l["y0"] - y[1] < 12 and not current["blocks"]:
                        current["y"] = (pno, l["y1"])
                        current["title"] += " " + title  # a title that wrapped onto a second line
                        i += 1
                        continue
                    if current is None or current["title"] != title:
                        current = {"title": title, "blocks": [], "y": (pno, l["y1"])}
                        sections.append(current)
                    i += 1
                    continue
                if l["kind"] in ("h3", "h4"):
                    j = i + 1
                    while j < len(group) and group[j]["kind"] == l["kind"] and group[j]["y0"] - group[j - 1]["y1"] < 6:
                        j += 1
                    flush(l["y0"])
                    add({"t": l["kind"], "html": html.escape(plain(group[i:j]), quote=False)})
                    i = j
                    continue
                j = i
                while j < len(group) and group[j]["kind"] == "body":
                    j += 1
                emit_body(group[i:j], right_edge, add, body_size)
                i = j
        flush()

        # ---- a picture of the original page, for anything the reflow gets wrong
        pix = page.get_pixmap(dpi=110)
        im = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        name = f"pages/{pno + 1:02d}.webp"
        im.save(out / name, "WEBP", quality=72, method=5)
        issue["pages"].append({"src": name, "w": im.width, "h": im.height})

    issue["sections"] = [s for s in sections if s["blocks"]]
    for n, s in enumerate(issue["sections"]):
        s.pop("y", None)
        s["id"] = re.sub(r"[^a-z0-9]+", "-", s["title"].lower()).strip("-") or f"section-{n + 1}"
    if "date" not in issue:
        m = re.match(r"D:(\d{4})(\d{2})(\d{2})", doc.metadata.get("creationDate") or "")
        if m:
            issue["date"] = f"{m[1]}-{m[2]}-{m[3]}"
    issue["schema"] = SCHEMA
    (out / "issue.json").write_text(json.dumps(issue, ensure_ascii=False, separators=(",", ":")), "utf-8")
    return issue


TAG_RE = re.compile(r"<[^>]+>")
LIST_RE = re.compile(r"^\s*(?:(\d{1,2})[.)]|([•·▪●]))\s+")


def short_breaks(lines: list[dict], right) -> set[int]:
    """Indexes of lines that end early on purpose (a line break), not because they wrapped."""
    out = set()
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        edge = right(a) if callable(right) else right
        per_char = (b["x1"] - b["x0"]) / max(len(b["text"].rstrip()), 1)
        first_word = (b["text"].split() or [""])[0]
        if a["x1"] + (len(first_word) + 1) * per_char < edge - 4:
            out.add(i)
    return out


def emit_body(lines: list[dict], right_edge, add, body_size: float):
    """Split a run of body lines into paragraphs and list items."""
    if not lines:
        return
    chunks: list[tuple[str, list]] = []
    for l in lines:
        m = LIST_RE.match(l["text"])
        if m:
            chunks.append(("ol" if m[1] else "ul", [l]))
        elif chunks and (chunks[-1][0] in ("ol", "ul") or chunks[-1][0] == "p"):
            chunks[-1][1].append(l)
        else:
            chunks.append(("p", [l]))
    for t, ls in chunks:
        if t == "p":
            lead = max(l["size"] for l in ls) >= body_size + 3
            for part in inline(ls, short_breaks(ls, right_edge), paragraphs=True).split("\f"):
                if part:
                    add({"t": "p", "html": part, **({"lead": True} if lead else {})})
        else:
            add({"t": t, "items": [inline(ls, strip=LIST_RE.pattern)]})
        for v in videos_in(ls):
            add(v)


# ----------------------------------------------------------------- main

def build_issue(meta: dict, pdf_path: Path | None = None) -> dict | None:
    out = DATA / meta["id"]
    existing = out / "issue.json"
    if existing.exists() and pdf_path is None:
        old = json.loads(existing.read_text("utf-8"))
        if old.get("pdf") == meta["pdf"] and old.get("schema") == SCHEMA:
            print(f"  {meta['title']} {meta['year']}: already built")
            return old
    print(f"  {meta['title']} {meta['year']}: building")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    src = pdf_path
    if src is None:
        src = out / "source.pdf"
        src.write_bytes(fetch(meta["pdf"]))
    try:
        return extract(src, meta, out)
    finally:
        if pdf_path is None:
            src.unlink(missing_ok=True)


def summary(issue: dict, built: bool) -> dict:
    keep = ("id", "title", "year", "term", "week", "date", "pdf", "sort")
    return {**{k: issue[k] for k in keep if k in issue}, "built": built}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, help="build this local PDF instead of fetching from the website")
    ap.add_argument("--count", type=int, default=4, help="how many of the newest issues to build (default 4)")
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    index_path = DATA / "index.json"
    index = json.loads(index_path.read_text("utf-8")) if index_path.exists() else {"issues": []}
    entries = {i["id"]: i for i in index["issues"]}

    if args.pdf:
        meta = describe(args.pdf.name)
        meta["pdf"] = entries.get(meta["id"], {}).get("pdf", "")
        issue = build_issue(meta, args.pdf)
        entries[meta["id"]] = summary(issue, True)
    else:
        print(f"Reading {LISTING_URL}")
        listing = list_issues()
        if not listing:
            sys.exit("No newsletter PDFs found on the page - has the website changed?")
        entries = {}
        for n, meta in enumerate(listing):
            issue = None
            if n < args.count:
                try:
                    issue = build_issue(meta)
                except Exception as e:
                    print(f"    failed: {e}")
            entries[meta["id"]] = summary(issue or meta, issue is not None)
        for folder in DATA.iterdir():  # drop issues that have aged out
            if folder.is_dir() and not entries.get(folder.name, {}).get("built"):
                shutil.rmtree(folder)

    issues = sorted(entries.values(), key=lambda i: i["sort"], reverse=True)
    built = [i for i in issues if i["built"]]
    index = {"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "latest": built[0]["id"] if built else None, "issues": issues}
    if not built:
        sys.exit("No issue could be built - leaving the published site as it is.")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")
    print(f"Done: {len(built)} readable issue(s), {len(issues)} listed. Latest: {index['latest']}")


if __name__ == "__main__":
    main()
