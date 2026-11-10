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

## Hosting

The app is deployed on Vercel from the `main` branch. `vercel.json` tells Vercel to
install the Python packages, run `tools/build.py` and serve `public/`, so every
deployment fetches the newest issues. Open the site on your phone and choose
"Add to Home Screen".

To pick up new issues without pushing a commit, `api/refresh.js` is called by a Vercel
cron twice a day and starts a fresh deployment. It needs two environment variables in
the Vercel project (Settings -> Environment Variables):

- `DEPLOY_HOOK_URL`: create a hook for `main` under Settings -> Git -> Deploy Hooks and
  paste its URL here.
- `CRON_SECRET`: any long random string.

Until those are set, redeploy by hand from the Vercel dashboard when a new issue is out.

The site is public, and the newsletters contain children's names and photos. They are
already public on the school website, but this is a second copy.

## When an issue looks wrong

The text is recovered from the PDF's layout, so an unusual page can come out oddly.
Every issue has an "Original" tab with the untouched pages, and the layout rules live
in `extract()` in `tools/build.py`. Bump `SCHEMA` there to force a rebuild of
everything.
