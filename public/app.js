// BMS Newsletter reader. Data comes from tools/build.py (public/data/).

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v; // only ever markup produced by our own build script
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  node.append(...kids.flat().filter((k) => k != null && k !== false));
  return node;
}

const CHEVRON = '<svg class="chev" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

const deck = $('#deck');
const tabs = $('#tabs');
const state = { index: null, issue: null, base: '', panels: [], active: 0 };

// ---------------------------------------------------------------- data

async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

const parseDate = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
const longDate = (iso) => parseDate(iso).toLocaleDateString('en-AU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const shortDate = (iso) => parseDate(iso).toLocaleDateString('en-AU', { day: 'numeric', month: 'long', year: 'numeric' });
const niceTitle = (issue) => issue.title.replace(/^(Term \d+) (Week \d+)$/, '$1 · $2');

function daysFromToday(iso) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((parseDate(iso) - today) / 864e5);
}

// ---------------------------------------------------------------- start-up

async function start() {
  try {
    state.index = await getJSON('data/index.json');
  } catch {
    return fail('Could not load the newsletter. Check your connection and try again.');
  }
  const [id, panel] = location.hash.slice(1).split('/');
  const built = state.index.issues.filter((i) => i.built);
  const pick = built.find((i) => i.id === id) || built.find((i) => i.id === state.index.latest) || built[0];
  if (!pick) return fail('No newsletters are available yet.');
  await openIssue(pick.id, panel);
}

function fail(message) {
  deck.replaceChildren(el('div', { class: 'status' }, message, el('br'),
    el('a', { href: 'https://www.beechworthmontessori.vic.edu.au/newsletter/' }, 'Open the school newsletter page')));
}

async function openIssue(id, panelId) {
  let issue;
  try {
    issue = await getJSON(`data/${id}/issue.json`);
  } catch {
    return fail('Could not load that issue.');
  }
  state.issue = issue;
  state.base = `data/${id}/`;
  render(issue);
  const at = Math.max(0, state.panels.findIndex((p) => p.id === panelId));
  go(at, false);
  setActive(at, true);
}

// ---------------------------------------------------------------- rendering

function render(issue) {
  $('#issue-title').textContent = `${niceTitle(issue)}${issue.date ? ' · ' + shortDate(issue.date).replace(/ \d{4}$/, '') : ''}`;
  document.title = `${niceTitle(issue)} – BMS Newsletter`;

  const used = new Set(['home', 'pages']);
  const sections = issue.sections.map((s) => {
    let id = s.id, n = 2;
    while (used.has(id)) id = `${s.id}-${n++}`;
    used.add(id);
    return { ...s, id };
  });

  state.panels = [
    { id: 'home', tab: 'This issue', title: 'Front page' },
    ...sections.map((s) => ({ id: s.id, tab: shortTab(s.title), title: s.title, section: s })),
    { id: 'pages', tab: 'Original', title: 'Original pages' },
  ];

  tabs.replaceChildren(...state.panels.map((p, i) => el('button', { class: 'tab', onclick: () => go(i) }, p.tab)));
  deck.replaceChildren(...state.panels.map((p, i) => {
    const inner = el('div', { class: 'inner' });
    if (p.id === 'home') inner.append(...homePanel(issue));
    else if (p.id === 'pages') inner.append(...pagesPanel(issue));
    else inner.append(...sectionPanel(issue, p.section));
    inner.append(pager(i));
    return el('section', { class: 'panel', id: `panel-${p.id}`, 'aria-label': p.title }, inner);
  }));
}

// "A Message from the Principal" is a mouthful for a tab
function shortTab(title) {
  return title
    .replace(/^A Message from the /i, '')
    .replace(/^Committee of Management\s*[–-]\s*/i, '')
    .replace(/ News$/i, '')
    .replace(/^Community Notices$/i, 'Community');
}

function homePanel(issue) {
  const out = [];
  out.push(el('div', { class: 'hero' },
    el('img', { class: 'hero-logo', src: 'icons/logo.png', alt: 'Beechworth Montessori School', width: 552, height: 240 }),
    el('p', { class: 'eyebrow' }, 'Newsletter'),
    el('h1', {}, niceTitle(issue)),
    issue.date && el('p', { class: 'date' }, longDate(issue.date))));

  const latest = state.index.issues.find((i) => i.id === state.index.latest);
  if (latest && latest.id !== issue.id) {
    out.push(el('button', { class: 'notice', onclick: () => switchIssue(latest.id) },
      el('span', {}, `Newer issue: ${niceTitle(latest)}`), el('span', { html: CHEVRON })));
  }

  if (issue.events.length) {
    const rows = [];
    let nextMarked = false;
    let title = "What's on";
    const first = issue.events[0];
    if (first.heading) title = first.heading;
    for (const ev of issue.events.slice(first.heading ? 1 : 0)) {
      if (ev.heading) { rows.push(el('li', { class: 'events-heading' }, ev.heading)); continue; }
      const away = ev.date ? daysFromToday(ev.date) : null;
      const d = ev.date ? parseDate(ev.date) : null;
      const badge = d
        ? el('div', { class: 'badge' },
            el('small', {}, d.toLocaleDateString('en-AU', { weekday: 'short' })),
            el('b', {}, String(d.getDate())),
            el('small', {}, d.toLocaleDateString('en-AU', { month: 'short' })))
        : el('div', { class: 'badge blank' });
      const text = el('div', { html: ev.html });
      let label = null;
      if (away === 0) label = 'Today';
      else if (away === 1) label = 'Tomorrow';
      else if (away > 1 && !nextMarked) label = `In ${away} days`;
      if (away != null && away >= 0) nextMarked = true;
      if (label) text.append(' ', el('span', { class: 'when' }, label));
      rows.push(el('li', { class: ['event', ev.tone, away != null && away < 0 && 'past'].filter(Boolean).join(' ') }, badge, text));
    }
    out.push(el('h2', { class: 'block-title' }, title.replace(/’/g, "'")),
      issue.termDates && el('p', { class: 'term-dates' }, issue.termDates.replace(/(Term \d) /g, '$1: ').replace(/(\S) (Term \d:)/g, '$1 · $2')),
      el('ul', { class: 'events' }, rows));
  }

  out.push(el('h2', { class: 'block-title' }, 'In this issue'),
    el('ul', { class: 'contents' }, state.panels.slice(1, -1).map((p, n) => {
      const heads = p.section.blocks.filter((b) => b.t === 'h3' || b.t === 'h4').map((b) => stripTags(b.html));
      const photos = p.section.blocks.reduce((sum, b) => sum + (b.t === 'gallery' ? b.images.length : b.t === 'poster' ? 1 : 0), 0);
      const sub = heads.slice(0, 4).join(' · ') + (heads.length > 4 ? ' …' : '') || (photos ? `${photos} picture${photos > 1 ? 's' : ''}` : '');
      return el('li', {}, el('button', { onclick: () => go(n + 1) },
        el('span', {}, el('span', { class: 'c-title' }, p.title), sub && el('span', { class: 'c-sub' }, sub)),
        el('span', { html: CHEVRON })));
    })));
  return out;
}

const stripTags = (html) => { const t = document.createElement('template'); t.innerHTML = html; return t.content.textContent; };

function picture(img, cls) {
  const src = state.base + img.src;
  return el('button', { class: cls, 'data-full': src, 'aria-label': 'View picture', style: cls === 'poster' ? `max-width:${Math.max(img.w, 420)}px` : null },
    el('img', { src, width: img.w, height: img.h, loading: 'lazy', decoding: 'async', alt: '' }));
}

function sectionPanel(issue, section) {
  const out = [el('header', { class: 'sec-head' },
    el('p', { class: 'eyebrow' }, niceTitle(issue)),
    el('h2', {}, section.title))];
  for (const b of section.blocks) {
    if (b.t === 'h3' || b.t === 'h4') out.push(el(b.t, { html: b.html }));
    else if (b.t === 'p') out.push(el('p', { class: b.lead && 'lead', html: b.html }));
    else if (b.t === 'ol' || b.t === 'ul') out.push(el(b.t, {}, b.items.map((i) => el('li', { html: i }))));
    else if (b.t === 'poster') out.push(picture(b, 'poster'));
    else if (b.t === 'gallery') {
      const n = b.images.length;
      const g = el('div', { class: `gallery ${n === 1 ? 'one' : n === 2 || n === 4 ? 'two' : ''}` }, b.images.map((i) => picture(i, 'ph')));
      // a lone picture keeps roughly the share of the page it had in print (logos and QR codes stay small)
      if (n === 1) g.firstChild.style.maxWidth = `max(150px, ${Math.min(100, Math.round((b.images[0].f || 0.6) * 170))}%)`;
      out.push(g);
    } else if (b.t === 'video') {
      const src = b.provider === 'youtube' ? `https://www.youtube-nocookie.com/embed/${b.id}` : `https://player.vimeo.com/video/${b.id}`;
      out.push(el('div', { class: 'video' }, el('iframe', { src, loading: 'lazy', title: 'Video', allowfullscreen: true,
        allow: 'accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen' })));
    }
  }
  return out;
}

function pagesPanel(issue) {
  return [
    el('header', { class: 'sec-head' }, el('p', { class: 'eyebrow' }, niceTitle(issue)), el('h2', {}, 'Original pages')),
    el('p', {}, 'The newsletter exactly as the school published it. Tap a page to zoom in.'),
    ...issue.pages.map((p, i) => el('button', { class: 'page-img', 'data-full': state.base + p.src, 'aria-label': `Page ${i + 1}` },
      el('img', { src: state.base + p.src, width: p.w, height: p.h, loading: 'lazy', decoding: 'async', alt: `Page ${i + 1}` }))),
    issue.pdf && el('p', { class: 'source' }, el('a', { href: issue.pdf, target: '_blank', rel: 'noopener' }, 'Open the PDF on the school website')),
  ];
}

function pager(i) {
  const prev = state.panels[i - 1], next = state.panels[i + 1];
  return el('nav', { class: 'pager', 'aria-label': 'More sections' },
    prev && el('button', { class: 'prev', onclick: () => go(i - 1) }, el('small', {}, 'Back'), el('span', {}, prev.title)),
    next && el('button', { class: 'next', onclick: () => go(i + 1) }, el('small', {}, i === 0 ? 'Start reading' : 'Next'), el('span', {}, next.title)));
}

// ---------------------------------------------------------------- moving between panels

function go(i, smooth = true) {
  i = Math.max(0, Math.min(state.panels.length - 1, i));
  deck.scrollTo({ left: i * deck.clientWidth, behavior: smooth ? 'smooth' : 'instant' });
}

function setActive(i, force = false) {
  if (i === state.active && !force) return;
  state.active = i;
  [...tabs.children].forEach((t, n) => t.setAttribute('aria-current', n === i));
  const tab = tabs.children[i];
  if (tab) tabs.scrollTo({ left: tab.offsetLeft - (tabs.clientWidth - tab.offsetWidth) / 2, behavior: 'smooth' });
  const p = state.panels[i];
  if (p) history.replaceState(history.state, '', `#${state.issue.id}${p.id === 'home' ? '' : '/' + p.id}`);
}

let ticking = false;
deck.addEventListener('scroll', () => {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    if (state.panels.length) setActive(Math.round(deck.scrollLeft / deck.clientWidth));
  });
}, { passive: true });

window.addEventListener('resize', () => go(state.active, false));
$('#home').addEventListener('click', () => { go(0); $('#panel-home')?.scrollTo({ top: 0, behavior: 'smooth' }); });

document.addEventListener('keydown', (e) => {
  if (e.target.closest('dialog')) return;
  if (!lightbox.hidden) {
    if (e.key === 'Escape') closeLightbox();
    if (e.key === 'ArrowRight') strip.scrollBy({ left: strip.clientWidth, behavior: 'smooth' });
    if (e.key === 'ArrowLeft') strip.scrollBy({ left: -strip.clientWidth, behavior: 'smooth' });
    return;
  }
  if (e.key === 'ArrowRight') go(state.active + 1);
  if (e.key === 'ArrowLeft') go(state.active - 1);
});

// ---------------------------------------------------------------- photo viewer

const lightbox = $('#lightbox');
const strip = $('#lb-strip');

deck.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-full]');
  if (!btn) return;
  const all = [...btn.closest('.panel').querySelectorAll('[data-full]')];
  strip.replaceChildren(...all.map((b) => el('div', { class: 'lb-slide' }, el('img', { src: b.dataset.full, alt: '' }))));
  lightbox.hidden = false;
  strip.scrollTo({ left: all.indexOf(btn) * strip.clientWidth, behavior: 'instant' });
  countSlides();
  history.pushState({ lightbox: true }, '');
});

function countSlides() {
  const n = Math.round(strip.scrollLeft / strip.clientWidth) + 1;
  $('#lb-count').textContent = strip.children.length > 1 ? `${n} of ${strip.children.length}` : '';
}
strip.addEventListener('scroll', countSlides, { passive: true });

// tap to zoom in on the spot that was tapped, tap again to zoom back out
strip.addEventListener('click', (e) => {
  const img = e.target.closest('img');
  if (!img) return closeLightbox();
  const slide = img.parentElement;
  const box = img.getBoundingClientRect();
  const fx = (e.clientX - box.left) / box.width, fy = (e.clientY - box.top) / box.height;
  const zoomed = slide.classList.toggle('zoom');
  if (zoomed) {
    slide.scrollLeft = fx * slide.scrollWidth - slide.clientWidth / 2;
    slide.scrollTop = fy * slide.scrollHeight - slide.clientHeight / 2;
  }
});

function closeLightbox() {
  if (lightbox.hidden) return;
  if (history.state?.lightbox) history.back();
  else hideLightbox();
}
function hideLightbox() { lightbox.hidden = true; strip.replaceChildren(); }
window.addEventListener('popstate', hideLightbox); // so the phone's back button closes the viewer
$('#lb-close').addEventListener('click', closeLightbox);

// ---------------------------------------------------------------- issue list

const sheet = $('#issues');

$('#open-issues').addEventListener('click', () => {
  const { issues, latest } = state.index;
  const built = issues.filter((i) => i.built);
  const older = issues.filter((i) => !i.built && i.pdf);
  const years = [...new Set(older.map((i) => i.year))];
  $('#issue-list').replaceChildren(
    ...built.map((i) => el('button', { class: 'issue-btn', 'aria-current': i.id === state.issue?.id, onclick: () => { sheet.close(); switchIssue(i.id); } },
      el('span', {}, el('b', {}, niceTitle(i)), el('small', {}, i.date ? shortDate(i.date) : String(i.year))),
      i.id === latest && el('span', { class: 'tag' }, 'Latest'))),
    older.length && el('h3', {}, 'Older issues (PDF)'),
    ...years.map((y) => el('details', {}, el('summary', {}, String(y)),
      older.filter((i) => i.year === y).map((i) => el('a', { href: i.pdf, target: '_blank', rel: 'noopener' }, niceTitle(i))))));
  sheet.showModal();
});
sheet.addEventListener('click', (e) => { if (e.target === sheet || e.target.closest('[data-close]')) sheet.close(); });

async function switchIssue(id) {
  if (id === state.issue?.id) return go(0);
  await openIssue(id);
}

// ---------------------------------------------------------------- new issue check

const toast = $('#toast');
document.addEventListener('visibilitychange', async () => {
  if (document.hidden || !state.index) return;
  try {
    const fresh = await getJSON('data/index.json');
    if (fresh.latest && fresh.latest !== state.index.latest) {
      state.index = fresh;
      const issue = fresh.issues.find((i) => i.id === fresh.latest);
      toast.textContent = `New issue: ${niceTitle(issue)} – tap to read`;
      toast.hidden = false;
      toast.onclick = () => { toast.hidden = true; switchIssue(fresh.latest); };
    }
  } catch { /* offline: keep showing what we have */ }
});

if ('serviceWorker' in navigator && !['localhost', '127.0.0.1'].includes(location.hostname)) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

start();
