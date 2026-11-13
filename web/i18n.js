/* The screens in Kurdish (Sorani), right to left.

   The screens are drawn in English. With Kurdish chosen (Setup → Language),
   each piece of text is looked up in the Kurdish Mohammed made with Gemini and
   swapped in as it appears, and the page runs right to left. A piece is one
   element's own words, with what changes in it taken out as {0}, {1}…:
   numbers, dates, the names in the books, anything already in Kurdish, and
   the elements inside it. So "Filled Apple Mix: 500 g" and "Filled House Mix:
   300 g" are the one piece "Filled {0}: {1} g", and the Kurdish can put {0}
   and {1} wherever its grammar wants them.

   A piece with no Kurdish yet stays in English, kept left to right inside
   the right-to-left page so it still reads, and is sent to the server, so
   the next prompt for Gemini asks for it. Nothing in Kurdish is written in
   the app's code: it all lives in the books. */

const ch = code => String.fromCharCode(code);
const FSI = ch(0x2068);                  // a value keeps its own direction…
const PDI = ch(0x2069);                  // …inside the Kurdish around it
const MARKS = new RegExp(`[${ch(0x2066)}-${ch(0x2069)}]`, 'g');    // put in by an earlier pass
const HOLE = 0xE000;                     // an element inside a piece, while its key is made
const IS_HOLE = /^\p{Co}$/u;
const ATTRS = ['placeholder', 'title', 'aria-label'];
const LEAVE = 'script, style, noscript, textarea, code, pre, bdi, svg, [translate="no"]';

/* What changes inside a piece: paths and files, Kurdish already, the names in
   the books, month and weekday names (translated on their own), then dates,
   times and numbers. */
const FILES = String.raw`[A-Za-z]:\\(?:[\w.\- ]+\\)*[\w.\-]*|https?:\/\/\S+|[\w\-.:]+\.(?:zip|bak|db|json|csv|txt|pdf|bat)\b`;
const KURDISH = String.raw`\p{Script=Arabic}(?:[\p{Script=Arabic}\p{M}\p{Cf}]|\s(?=\p{Script=Arabic}))*`;
const MONTHS = 'January February March April May June July August September October November December'.split(' ');
const SHORT = MONTHS.map(m => m.slice(0, 3));
const DAYS = 'Monday Tuesday Wednesday Thursday Friday Saturday Sunday'.split(' ');
const CALENDAR = String.raw`(?:${MONTHS.join('|')})(?=\s\d{4})|(?<=\d\s)(?:${SHORT.join('|')})\b|\b(?:${DAYS.join('|')})\b`;
const NUMBERS = String.raw`\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\d{1,2}:\d{2}(?::\d{2})?|[-−+]?\d+(?:[,.]\d+)*%?`;
const CALENDAR_WORD = new RegExp(`^(?:${[...MONTHS, ...SHORT, ...DAYS].join('|')})$`);

let lang = 'en';
let dict = new Map();
let names = '';
let pattern = build();
let done = new WeakMap();                // element → its own text, once dealt with
let doneAttrs = new WeakMap();           // element → {attribute: value}, the same

function build() {
  return new RegExp([String.raw`\p{Co}`, FILES, KURDISH, names, CALENDAR, NUMBERS]
    .filter(Boolean).join('|'), 'gu');
}

const kurdish = () => lang === 'ckb';

/** English or Kurdish, and the page's direction with it. */
export function setLanguage(l) {
  const next = l === 'ckb' ? 'ckb' : 'en';
  if (next !== lang) forget();
  lang = next;
  const html = document.documentElement;
  html.lang = lang;
  html.dir = lang === 'ckb' ? 'rtl' : 'ltr';
}

/** The Kurdish: {English piece: Kurdish}. */
export function setDict(d) {
  dict = new Map(Object.entries(d || {}).filter(([, v]) => typeof v === 'string' && v));
  forget();
}

export const texts = () => dict;

function forget() {
  done = new WeakMap();
  doneAttrs = new WeakMap();
}

/* ------------------------------------------------------- the names in the books

   Names are values, never words to translate: people, pots, stock, the menu,
   what entries were for, folders. They are found in the state by the field
   they sit in. Some fields hold the app's own words instead, and are left
   out; so are three phrases the app itself writes into the books when nothing
   was typed. A name that is also one of the app's own words ("Ice" beside
   "Ice cream", "Electricity", "Foil") is taken as the word, so the app's
   sentences keep their words: the shipped text tells which they are. */

const NAME_FIELDS = new Set([
  'name', 'who', 'detail', 'brand', 'flavour', 'mix', 'pot', 'pot_to', 'main_pot', 'item',
  'group', 'portion', 'tables', 'opened_by', 'closed_by', 'supplier', 'rows', 'not_set',
  'fixed_names', 'second', 'local_folder', 'folder', 'path',
]);
const APP_WORDS = new Set(['checks', 'lang', 'recent', 'categories', 'accounts',
                           'targets', 'legs', 'differences', 'levels', 'update']);
const MADE = new Set(['Several items', 'Total sales of the day', 'not known']);
const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

let shipped = '';
const appWord = new Map();

/** The text that ships with the app (web/lang/catalog.json). */
export function setCatalog(keys) {
  shipped = Array.isArray(keys) ? keys.join('\n') : '';
  appWord.clear();
}

const usedByApp = s => {
  if (!appWord.has(s)) {
    appWord.set(s, new RegExp(String.raw`(?<![\p{L}\p{N}])${escape(s)}(?![\p{L}\p{N}])`, 'u').test(shipped));
  }
  return appWord.get(s);
};

export function setNames(state) {
  const found = new Set();
  const walk = (v, path) => {
    if (typeof v === 'string') {
      const [key, parent, grand] = path.slice(-3).reverse();
      const named = path[0] === 'lists' || NAME_FIELDS.has(key)
        || (key === 'what' && parent === 'receipt');
      const category = key === 'name' && (parent === 'categories'
                                          || (parent === 'groups' && grand === 'count'));
      const s = v.trim();
      if (named && !category && s.length > 1 && s.length < 160 && /\p{L}/u.test(s)
          && !MADE.has(s) && !dict.has(s) && !usedByApp(s)) found.add(s);
    } else if (Array.isArray(v)) {
      v.forEach(x => walk(x, path));
    } else if (v && typeof v === 'object') {
      for (const [k, x] of Object.entries(v)) if (!APP_WORDS.has(k)) walk(x, [...path, k]);
    }
  };
  walk(state, []);
  const list = [...found].sort((a, b) => b.length - a.length).map(escape);
  names = list.length ? String.raw`(?<![\p{L}\p{N}])(?:${list.join('|')})(?![\p{L}\p{N}])` : '';
  pattern = build();
}

/* ---------------------------------------------------------------- the pieces */

/** A piece's key: its words with everything that changes taken out. `words`
    is false when nothing is left to translate (only values, or one letter). */
function keyOf(text, holes = []) {
  const vals = [];
  const key = text.replace(MARKS, '').replace(pattern, m => {
    vals.push(IS_HOLE.test(m) ? holes[m.charCodeAt(0) - HOLE] : m);
    return `{${vals.length - 1}}`;
  }).replace(/\s+/g, ' ').trim();
  if (!key) return null;
  const letters = (key.replace(/\{\d+\}/g, '').match(/[A-Za-z]/g) || []).length;
  return { key, vals, words: letters > 1 || (letters === 1 && vals.length > 0) };
}

/** The key the screens would use for `text` (for the tests and the catalog). */
export const keyFor = text => {
  const k = keyOf(String(text || ''));
  return k && k.words ? k.key : null;
};

const ownText = el => {
  let s = '';
  for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
  return s;
};

const calendarWord = v => typeof v === 'string' && CALENDAR_WORD.test(v);

function fill(template, vals) {
  return template.split(/(\{\d+\})/).filter(Boolean).map(p => {
    const m = /^\{(\d+)\}$/.exec(p);
    if (!m) return document.createTextNode(p);
    const v = vals[Number(m[1])];
    if (v instanceof Node) return v;
    const word = calendarWord(v) && dict.get(v);
    return document.createTextNode(FSI + (word || v || '') + PDI);
  });
}

function put(el, text, nodes) {
  el.replaceChildren(...(/^\s/.test(text) ? [' '] : []), ...nodes,
                     ...(/\s$/.test(text) ? [' '] : []));
}

/** English left untranslated still reads left to right. */
function isolate(el) {
  const words = [...el.childNodes].filter(n => n.nodeType === 3 && /\S/.test(n.nodeValue));
  if (!words.length || !/[A-Za-z0-9]/.test(ownText(el)) || ownText(el).includes(FSI)) return;
  const first = words[0];
  const last = words[words.length - 1];
  first.nodeValue = first.nodeValue.replace(/^\s*/, s => s + FSI);
  last.nodeValue = last.nodeValue.replace(/\s*$/, s => PDI + s);
}

/** Translate one element's own words, if it has any. */
function piece(el) {
  const raw = ownText(el);
  if (!/\S/.test(raw) || done.get(el) === raw) return;
  const holes = [];
  let text = '';
  for (const n of el.childNodes) {
    if (n.nodeType === 3) text += n.nodeValue;
    else if (n.nodeType === 1) text += ch(HOLE + holes.push(n) - 1);
  }
  const k = keyOf(text, holes);
  if (k) {
    if (k.words && !dict.has(k.key)) note(k.key);
    k.vals.forEach(v => { if (calendarWord(v) && !dict.has(v)) note(v); });
    if (kurdish()) {
      if (k.words && dict.has(k.key)) put(el, text, fill(dict.get(k.key), k.vals));
      else if (!k.words && k.vals.some(v => calendarWord(v) && dict.has(v))) put(el, text, fill(k.key, k.vals));
      else isolate(el);
    }
  }
  done.set(el, ownText(el));
}

function attrs(el) {
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    const was = doneAttrs.get(el) || {};
    if (!v || was[a] === v) continue;
    let out = v;
    const k = keyOf(v);
    if (k && k.words) {
      if (!dict.has(k.key)) note(k.key);
      else if (kurdish()) {
        out = dict.get(k.key).replace(/\{(\d+)\}/g, (_, i) => {
          const x = k.vals[Number(i)];
          return (calendarWord(x) && dict.get(x)) || (typeof x === 'string' ? x : '');
        });
      }
    }
    if (out !== v) el.setAttribute(a, out);
    doneAttrs.set(el, { ...was, [a]: out });
  }
}

/** Translate everything in `root`, and `root` itself. Safe to run again: what
    is done is left alone. In English nothing changes; the pieces are only
    noted, so Gemini can be asked for them before Kurdish is chosen. */
function localise(root) {
  if (!root || root.nodeType !== 1 || root.closest(LEAVE)) return;
  const a = document.activeElement;
  let at = null;
  try { at = a && a.selectionStart !== undefined ? [a.selectionStart, a.selectionEnd] : null; } catch { /* not a text box */ }
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (el.closest(LEAVE)) continue;
    piece(el);
    attrs(el);
  }
  // a box whose label was rearranged keeps the cursor where it was
  if (a && a !== document.activeElement && document.contains(a)) {
    a.focus({ preventScroll: true });
    try { if (at && at[0] !== null) a.setSelectionRange(at[0], at[1]); } catch { /* not a text box */ }
  }
}

/* Whatever is drawn, redrawn or popped up is translated as it appears, before
   it is painted. */
const WATCH = { childList: true, subtree: true, characterData: true,
                attributes: true, attributeFilter: ATTRS };
let observer = null;

function quietly(fn) {
  if (!observer) return fn();
  observer.disconnect();
  try { return fn(); } finally { observer.observe(document.body, WATCH); }
}

export function watch() {
  if (observer) return;
  observer = new MutationObserver(records => {
    const roots = new Set();
    for (const r of records) {
      const t = r.target.nodeType === 1 ? r.target : r.target.parentElement;
      if (t && t.isConnected) roots.add(t);
    }
    quietly(() => roots.forEach(t => localise(t)));
  });
  quietly(() => localise(document.body));
}

/** Translate now, for a page about to be printed. */
export const localiseNow = root => quietly(() => localise(root));

/* ---------------------------------------------------- pieces with no Kurdish */

const noted = new Set();
const pending = new Set();
let timer = 0;

function note(key) {
  if (key.length > 400 || noted.has(key)) return;
  noted.add(key);
  pending.add(key);
  clearTimeout(timer);
  timer = setTimeout(flush, 3000);
}

function flush(keepalive = false) {
  if (!pending.size) return;
  const keys = [...pending].slice(0, 500);
  keys.forEach(k => pending.delete(k));
  fetch('/api/lang/seen', {
    method: 'POST', keepalive, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keys }),
  }).catch(() => keys.forEach(k => noted.delete(k)));
  if (pending.size) timer = setTimeout(flush, 300);
}

if (typeof addEventListener === 'function') addEventListener('pagehide', () => flush(true));

/* ---------------------------------------------------------------- for Gemini */

export const BATCH = 150;

/** The prompt that asks Gemini for the Kurdish of `keys`. The words already
    chosen go with it, so every batch uses the same ones. */
export function prompt(keys) {
  const chosen = [...dict].filter(([k]) => !k.includes('{') && k.length <= 24 && k.split(' ').length <= 3)
    .sort((a, b) => a[0].length - b[0].length).slice(0, 60);
  return `You are translating the screens of a small bookkeeping app into Central Kurdish
(Sorani), written in the Kurdish Arabic script. The owner and staff of a hookah lounge
and café in Ranya, Kurdistan, use it every night to record sales, expenses, cash, stock
and staff.

Rules:
- Plain, short, everyday Kurdish, the way a café owner in Ranya speaks, not formal or
  literary. Buttons and headings stay short.
- Keep every {0}, {1}, {2}… exactly as written. Each stands for a number, a date, a name
  or another part of the screen. Move it to wherever Kurdish grammar needs it, but never
  drop, change or add one.
- Use the same Kurdish word for the same English word every time.
- Keep SambaPOS, Gemini, Tailscale, GitHub, USB and PDF as they are.
- Answer with JSON only: one object whose keys are the line numbers below and whose
  values are the Kurdish, like {"1": "…", "2": "…"}, with nothing before or after it.
${chosen.length ? `
Words already used on these screens. Keep using them:
${chosen.map(([k, v]) => `${k} = ${v}`).join('\n')}
` : ''}
Lines:
${keys.map((k, i) => `${i + 1}. ${k}`).join('\n')}
`;
}

/** Gemini's answer back into {English: Kurdish}: by line number for the
    batch it was asked, or by the English itself. Throws if it is not JSON. */
export function answer(text, batch = []) {
  const s = String(text || '');
  const from = s.indexOf('{');
  const to = s.lastIndexOf('}');
  if (from < 0 || to < from) throw new Error('no JSON');
  const o = JSON.parse(s.slice(from, to + 1));
  const out = {};
  for (const [k, v] of Object.entries(o)) {
    if (typeof v !== 'string' || !v.trim()) continue;
    const key = /^\d+$/.test(k) ? batch[Number(k) - 1] : k;
    if (key) out[key] = v.trim();
  }
  return out;
}
