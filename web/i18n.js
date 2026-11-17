/* The screens in Kurdish (Sorani), right to left.

   The Kurdish comes with the app, in lang/ckb.json, by the same names as the
   English in lang/en.json. With Kurdish chosen (Setup → This app), the
   screens' own sentences come out of t() and th() (lib.js) in Kurdish
   already, each one run right to left with every value in it (a number, a
   date, a name) kept its own way round inside it. A sentence with no Kurdish
   yet comes out in English, as one run left to right.

   What the server says arrives in English, filled in: a refusal, a check, a
   line in Recent changes, a phrase the app wrote into the books. It is put
   into Kurdish here, as it is shown. A piece of text is one element's own
   words with what changes in it taken out as {0}, {1}…: numbers, dates, the
   names in the books, anything in Kurdish already, and the elements inside
   it. So "Filled Apple Mix: 1,500 g" is the piece "Filled {0}: {1} g", and is
   looked up among the English sentences, each made into the same shape. A
   piece whose value is a sentence itself ("Deleted: Daily expense · …") is
   matched to the sentence around it, and its parts put into Kurdish in turn.
   The Kurdish Mohammed kept in his books, before the Kurdish came with the
   app, is used where lang/ckb.json has none.

   Nothing in Kurdish is written in the code: it is all in lang/ckb.json. */

const ch = code => String.fromCharCode(code);
const LRI = ch(0x2066);                  // the screens' own English, with no Kurdish yet
const RLI = ch(0x2067);                  // the screens' own Kurdish
const FSI = ch(0x2068);                  // a value keeps its own direction…
const PDI = ch(0x2069);                  // …inside the words around it
const MARKS = new RegExp(`[${ch(0x2066)}-${ch(0x2069)}]`, 'g');
const MARKED = new RegExp(`[${ch(0x2066)}-${ch(0x2069)}]`);
const HOLE = 0xE000;                     // an element inside a piece, while its key is made
const IS_HOLE = /^\p{Co}$/u;
const ATTRS = ['placeholder', 'title', 'aria-label', 'label'];
const LEAVE = 'script, style, noscript, textarea, code, pre, bdi, svg, [translate="no"]';

/* What changes inside a piece: paths and files, Kurdish already, the names in
   the books, month and weekday names (put into Kurdish on their own), then
   dates, times and numbers. */
const FILES = String.raw`[A-Za-z]:\\(?:[\w.\- ]+\\)*[\w.\-]*|https?:\/\/\S+|[\w\-.:]+\.(?:zip|bak|db|json|csv|txt|pdf|bat)\b`;
const KURDISH = String.raw`\p{Script=Arabic}(?:[\p{Script=Arabic}\p{M}\p{Cf}]|\s(?=\p{Script=Arabic}))*`;
let CALENDAR = '';                       // month and day names: set by calendar()
const NUMBERS = String.raw`\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\d{1,2}:\d{2}(?::\d{2})?|[-−+]?\d+(?:[,.]\d+)*%?`;
let CALENDAR_WORD = /^$/;

let lang = 'en';
let dict = new Map();                    // piece → its Kurdish, from lang/ckb.json
let kept = new Map();                    // piece → its Kurdish, from the books
let sentences = [];                      // the sentences with values in them, to match a piece to
let worked = new Map();                  // piece → its Kurdish, or null, once worked out
let names = '';
let pattern = build();
let done = new WeakMap();                // element → its own text, once dealt with
let doneAttrs = new WeakMap();           // element → {attribute: value}, the same

function build() {
  return new RegExp([String.raw`\p{Co}`, FILES, KURDISH, names, CALENDAR, NUMBERS]
    .filter(Boolean).join('|'), 'gu');
}

/** Whether the screens are in Kurdish. */
export const kurdish = () => lang === 'ckb';

/** A sentence of the screens' own as it goes on a page in Kurdish: its
    Kurdish as one run right to left, or its English, as one run left to
    right; and a value, kept its own way round. */
export const inKurdish = s => RLI + s + PDI;
export const inEnglish = s => LRI + s + PDI;
export const ownWay = v => FSI + v + PDI;

/** English or Kurdish, and the page's direction with it. */
export function setLanguage(l) {
  const next = l === 'ckb' ? 'ckb' : 'en';
  if (next !== lang) forget();
  lang = next;
  const html = document.documentElement;
  html.lang = lang;
  html.dir = lang === 'ckb' ? 'rtl' : 'ltr';
}

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
   sentences keep their words: the app's own words (lang/en.json) tell which
   they are. */

const NAME_FIELDS = new Set([
  'name', 'who', 'detail', 'brand', 'flavour', 'mix', 'pot', 'pot_to', 'main_pot', 'item',
  'group', 'portion', 'tables', 'opened_by', 'closed_by', 'supplier', 'rows', 'not_set',
  'fixed_names', 'second', 'local_folder', 'folder', 'path',
]);
const APP_WORDS = new Set(['checks', 'lang', 'recent', 'categories', 'accounts',
                           'targets', 'legs', 'differences', 'levels', 'update']);
let MADE = new Set();
const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

let shipped = '';
const appWord = new Map();

/** The app's words (lang/en.json) and their Kurdish (lang/ckb.json), once
    they are read: the month and day names, the sentences that tell a name
    from a word, the phrases the app writes into the books itself, and every
    sentence made into the shape a piece of text is looked up by. */
export function useWords(english, ckb) {
  calendar(english);
  shipped = Object.entries(english).filter(([k]) => !/^(cli|migration)\./.test(k)).map(([, v]) => v).join('\n');
  appWord.clear();
  MADE = new Set([english['receipt.several'], english['entry.sales_detail'], english['cash.not_known']]);
  learn(english, ckb || {});
}

/** The Kurdish kept in the books, {piece: Kurdish}, for what lang/ckb.json
    has no Kurdish for. */
export function useBooks(d) {
  kept = new Map(Object.entries(d || {}).filter(([, v]) => typeof v === 'string' && v));
  worked = new Map();
  forget();
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
          && !MADE.has(s) && !dict.has(s) && !kept.has(s) && !usedByApp(s)) found.add(s);
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

/** The month and day names, from the words: a month with its year, a short
    month after a day, and a day, are values in a piece of text, put into
    Kurdish on their own. */
function calendar(words) {
  const nn = i => String(i + 1).padStart(2, '0');
  const months = Array.from({ length: 12 }, (_, i) => words[`month.${nn(i)}`]);
  const short = Array.from({ length: 12 }, (_, i) => words[`month.short.${nn(i)}`]);
  const days = Array.from({ length: 7 }, (_, i) => words[`day.${i + 1}`]);
  CALENDAR = String.raw`(?:${months.join('|')})(?=\s\d{4})|(?<=\d\s)(?:${short.join('|')})\b|\b(?:${days.join('|')})\b`;
  CALENDAR_WORD = new RegExp(`^(?:${[...months, ...short, ...days].join('|')})$`);
  pattern = build();
}

const CALENDAR_NAME = /^(?:month|day)\.(?:short\.)?\d+$/;
const letter = s => /[A-Za-z]/.test(s.replace(/\{\d+\}/g, ''));

/** Every sentence that has its Kurdish, made into the shape a piece of text
    is looked up by: its values, and the numbers, dates and months written in
    it, as {0}, {1}… in the order they are read, with its Kurdish numbered the
    same way. Numbers written in a sentence are its own: its Kurdish has them
    written in it too. A sentence with values is also kept to match a piece
    whose values are words. */
function learn(english, ckb) {
  dict = new Map();
  sentences = [];
  worked = new Map();
  const shape = new RegExp([String.raw`\{\d+\}`, FILES, KURDISH, CALENDAR, NUMBERS].join('|'), 'gu');
  for (const [name, k] of Object.entries(ckb)) {
    const e = english[name];
    if (typeof e !== 'string' || typeof k !== 'string' || !k.trim()) continue;
    if (CALENDAR_NAME.test(name)) {      // a month or a day: a value, put into Kurdish on its own
      dict.set(e, k);
      continue;
    }
    const at = [];
    let n = 0;
    const key = e.replace(shape, m => {
      const hole = /^\{(\d+)\}$/.exec(m);
      if (hole) at[Number(hole[1])] = n;
      return `{${n++}}`;
    }).replace(/\s+/g, ' ').trim();
    if (!letter(key)) continue;          // nothing to put into Kurdish
    const kur = k.replace(/\{(\d+)\}/g, (_, i) => `{${at[Number(i)]}}`);
    if (!dict.has(key)) dict.set(key, kur);
    if (n) sentences.push(shaped(key, kur));
  }
  // the one that says the most in words first
  sentences.sort((a, b) => b.weight - a.weight);
}

function shaped(key, kur) {
  const bits = key.split(/\{\d+\}/);
  return { re: new RegExp(`^${bits.map(escape).join('(.+?)')}$`, 'u'),
           bits: bits.filter(Boolean), kur,
           weight: bits.join('').replace(/[^A-Za-z]/g, '').length };
}

/* A sentence matched to a piece only when its words say at least this much:
   so a short one ("{0} g", "for {0}") never takes a whole sentence that has
   no Kurdish yet for one of its values. Unless every value is put into
   Kurdish too. */
const SAYS_ENOUGH = 8;

/** The Kurdish for a piece, its values still {0}, {1}…; or null. */
function kurdishFor(key, depth = 0) {
  if (worked.has(key)) return worked.get(key);
  let out = dict.get(key) ?? kept.get(key) ?? null;
  if (out === null && depth < 4) out = setOff(key, depth) ?? matched(key, depth);
  if (worked.size > 5000) worked = new Map();
  worked.set(key, out);
  return out;
}

/** A sentence set off by a dash or a bullet, or in brackets, as a check's
    detail is: "— every entry's two sides cancel". */
function setOff(key, depth) {
  const lead = /^(?:[—–·•(]\s*)+/.exec(key)?.[0] || '';
  const tail = /(?:\s*\))+$/.exec(key)?.[0] || '';
  if (!lead && !tail) return null;
  const k = within(key.slice(lead.length, key.length - tail.length), depth);
  return k === null ? null : lead + k + tail;
}

/** A piece one of the sentences makes with words for some of its values: the
    sentence's Kurdish, with each value put into Kurdish in turn. Or a list of
    them, as Recent changes says what an entry was ("Daily expense · {0} ·
    {1}") and a supplier's statement what came in ("Goods received — {0}"). */
function matched(key, depth) {
  for (const s of sentences) {
    if (!s.bits.every(b => key.includes(b))) continue;
    const m = s.re.exec(key);
    if (!m) continue;
    const parts = m.slice(1).map(p => part(p, depth));
    if (s.weight < SAYS_ENOUGH && parts.some(p => p.startsWith(FSI))) continue;
    return s.kur.replace(/\{(\d+)\}/g, (_, i) => parts[Number(i)]);
  }
  const bits = key.split(/( [·—] )/);
  if (bits.length > 1) {
    const parts = bits.map((b, i) => (i % 2 ? b : part(b, depth)));
    if (parts.some((p, i) => p !== bits[i] && !p.startsWith(FSI))) return parts.join('');
  }
  return null;
}

/** A value inside a matched sentence: as it is if it is only values; in
    Kurdish if it is a sentence too; else in English, kept left to right. */
function part(p, depth) {
  if (!letter(p)) return p;
  return within(p, depth) ?? ownWay(p);
}

/** The Kurdish for part of a piece, its values numbered as in the piece:
    looked up with them numbered from nought, as a sentence on its own is. */
function within(p, depth) {
  const ids = [];
  const key = p.replace(/\{(\d+)\}/g, (_, i) => `{${ids.push(i) - 1}}`).trim();
  const k = kurdishFor(key, depth + 1);
  return k === null ? null : k.replace(/\{(\d+)\}/g, (_, j) => `{${ids[Number(j)]}}`);
}

const calendarWord = v => typeof v === 'string' && CALENDAR_WORD.test(v);
const calendarKurdish = v => calendarWord(v) && (dict.get(v) || kept.get(v));

const ownText = el => {
  let s = '';
  for (const n of el.childNodes) if (n.nodeType === 3) s += n.nodeValue;
  return s;
};

function fill(template, vals) {
  return template.split(/(\{\d+\})/).filter(Boolean).map(p => {
    const m = /^\{(\d+)\}$/.exec(p);
    if (!m) return document.createTextNode(p);
    const v = vals[Number(m[1])];
    if (v instanceof Node) return v;
    return document.createTextNode(ownWay(calendarKurdish(v) || v || ''));
  });
}

function put(el, text, nodes) {
  el.replaceChildren(...(/^\s/.test(text) ? [' '] : []), ...nodes,
                     ...(/\s$/.test(text) ? [' '] : []));
}

/** The Kurdish for a piece's key; only as it is written, for the screens'
    own English (it has no Kurdish yet, though the books may) and for a
    piece with elements inside it. */
const lookUp = (key, asWritten) => (asWritten ? dict.get(key) ?? kept.get(key) ?? null : kurdishFor(key));

/** Put one element's own words into Kurdish, if it has any: all of them as
    one piece, else each run of text between the elements inside it on its
    own, as what the server said sits between them ("— every entry's two
    sides cancel"). The screens' own sentences are left as they are, in
    Kurdish already or with none yet. English left over still reads left to
    right. */
function piece(el) {
  const raw = ownText(el);
  if (!/\S/.test(raw) || done.get(el) === raw) return;
  const holes = [];
  let text = '';
  let k = null;
  let kur = null;
  if (!raw.includes(RLI)) {
    for (const n of el.childNodes) {
      if (n.nodeType === 3) text += n.nodeValue;
      else if (n.nodeType === 1) text += ch(HOLE + holes.push(n) - 1);
    }
    k = keyOf(text, holes);
    kur = k && k.words ? lookUp(k.key, holes.length > 0 || raw.includes(LRI)) : null;
  }
  if (kur !== null) put(el, text, fill(kur, k.vals));
  else runs(el);
  done.set(el, ownText(el));
}

function runs(el) {
  let run = [];
  const end = () => {
    const text = run.map(n => n.nodeValue).join('');
    const nodes = MARKED.test(text) ? null : runOf(text);
    if (nodes) {
      run[0].before(...(/^\s/.test(text) ? [' '] : []), ...nodes, ...(/\s$/.test(text) ? [' '] : []));
      run.forEach(n => n.remove());
    }
    run = [];
  };
  for (const n of [...el.childNodes]) {
    if (n.nodeType === 3) run.push(n);
    else if (run.length) end();
  }
  if (run.length) end();
}

/** One run of text in Kurdish, as nodes; or null to leave it as it is. */
function runOf(text) {
  if (!/\S/.test(text)) return null;
  const k = keyOf(text);
  if (!k) return null;
  const kur = k.words ? kurdishFor(k.key) : null;
  if (kur !== null) return fill(kur, k.vals);
  if (!k.words && k.vals.some(calendarKurdish)) return fill(k.key, k.vals);
  if (!/[A-Za-z0-9]/.test(text)) return null;
  return [document.createTextNode(ownWay(text.trim()))];
}

/** Plain text in Kurdish, or null. */
function plain(text) {
  const k = keyOf(text);
  const kur = k && k.words ? kurdishFor(k.key) : null;
  return kur === null ? null : kur.replace(/\{(\d+)\}/g, (_, i) => {
    const x = k.vals[Number(i)];
    return ownWay(calendarKurdish(x) || (typeof x === 'string' ? x : ''));
  });
}

/** A sentence the server sent, as plain text, in the language of the
    screens: to go inside one of their own sentences. */
export function said(text) {
  const s = String(text ?? '');
  if (!kurdish()) return s;
  const kur = plain(s);
  return kur === null ? inEnglish(s) : inKurdish(kur);
}

function attrs(el) {
  for (const a of ATTRS) {
    const v = el.getAttribute(a);
    const was = doneAttrs.get(el) || {};
    if (!v || was[a] === v) continue;
    const out = MARKED.test(v) ? v : plain(v) ?? v;
    if (out !== v) el.setAttribute(a, out);
    doneAttrs.set(el, { ...was, [a]: out });
  }
}

/** Put everything in `root`, and `root` itself, into Kurdish. Safe to run
    again: what is done is left alone. In English nothing changes. */
function localise(root) {
  if (!kurdish() || !root || root.nodeType !== 1 || root.closest(LEAVE)) return;
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

/* Whatever is drawn, redrawn or popped up is put into Kurdish as it appears,
   before it is painted. */
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

/** Put into Kurdish now, for a page about to be printed. */
export const localiseNow = root => quietly(() => localise(root));
