# BMS Newsletter

A phone-friendly reader for the Beechworth Montessori School newsletter. The school
publishes it as a PDF at <https://www.beechworthmontessori.vic.edu.au/newsletter/>;
this turns each issue into text that fits your screen, a "What's on" date list,
tappable photo galleries and full-size notices.

Unofficial: a parent's side project, not run by the school.

## How it works

- `tools/build.py` reads the school's newsletter page, works out the newest issues from
  the file names (`Week-6-Term-4-2026-Newsletter.pdf`), downloads them and writes
  `public/data/` — text, photos and a picture of every original page.
- `public/` is a static web app (no framework, no build step) that shows that data.
  It can be added to a phone's home screen and keeps working offline.

The school site doesn't allow other sites to fetch its PDFs from a browser, which is
why the conversion runs ahead of time rather than in the app.

## Run it locally

```bash
pip install -r requirements.txt
python tools/build.py
python -m http.server 8123 --directory public
```

Then open <http://localhost:8123>. Other build options:

```bash
python tools/build.py --count 8                                # keep more back issues readable
python tools/build.py --pdf Week-6-Term-4-2026-Newsletter.pdf  # build from a file you downloaded
```

## Put it on your phone

It needs to live at a web address. `.github/workflows/publish.yml` does this with
GitHub Pages: push this folder to a GitHub repo, set Settings → Pages → Source to
"GitHub Actions", and it rebuilds every three hours so new issues appear by themselves.
Open the address on your phone and choose "Add to Home Screen".

Note that GitHub Pages sites are public, and the newsletters contain children's names
and photos. They are already public on the school website, but think about whether you
want a second copy out there; a private host (e.g. Cloudflare Pages behind Access) is
the alternative.

## When an issue looks wrong

The text is recovered from the PDF's layout, so an unusual page can come out oddly.
Every issue has an "Original" tab with the untouched pages, and the layout rules live
in `extract()` in `tools/build.py`. Bump `SCHEMA` there to force a rebuild of
everything.
