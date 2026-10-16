const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Node {
  constructor(tag = '') { this.tag = tag; this.children = []; this.attributes = {}; this.handlers = {}; this.className = ''; this.hidden = false; this.textContent = ''; this.value = ''; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(event, handler) { (this.handlers[event] ??= []).push(handler); }
}
const fire = (node, event, detail = {}) => { const e = { preventDefault() { e.prevented = true; }, ...detail }; for (const handler of node.handlers[event] ?? []) handler(e); return e; };
const same = (actual, expected, message) => assert.equal(JSON.stringify(actual), JSON.stringify(expected), message);
const settle = () => new Promise(resolve => setImmediate(resolve));
const timers = new Map(); let timerId = 0;
const context = vm.createContext({
  document: { createElement: tag => new Node(tag) },
  setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
  clearTimeout(id) { timers.delete(id); },
});
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nthis.fuzzyMatch=fuzzyMatch;this.rankCandidates=rankCandidates;this.attachCombo=attachCombo;this.comboParts=comboParts;', context);
const { fuzzyMatch, rankCandidates, attachCombo, comboParts } = context;
const flushTimers = async () => { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); await settle(); };
const texts = list => list.children.map(item => item.children.map(part => part.textContent).join(''));
function field(source, options = {}) {
  const label = new Node('label'), input = new Node('input'); input.parentElement = label; label.children.push(input);
  const picks = [];
  const combo = attachCombo(input, { source, onPick: candidate => picks.push(candidate.value), ...options });
  return { input, list: label.children[1], picks, combo };
}
const projects = [
  { value: 'DEMO', label: 'Quality team (DEMO)' },
  { value: 'OTHER', label: 'Platform team (OTHER)' },
  { value: 'HTG', label: 'Hotel group (HTG)' },
];
const reporters = [
  { value: 'parkjh', label: '박정훈 (parkjh)' },
  { value: 'kimsh', label: '김선희 (kimsh)' },
  { value: 'leehc', label: '이현철 (leehc)' },
];

async function main() {
  // Fuzzy ranking: skim-style subsequence match, substring and word-start matches win, non-subsequences are dropped.
  assert.equal(fuzzyMatch('xyz', 'Quality team (DEMO)'), null);
  assert.ok(fuzzyMatch('qt', 'Quality team (DEMO)'), 'subsequence matches');
  assert.ok(fuzzyMatch('dm', 'Quality team (DEMO)').indices.length === 2);
  assert.ok(fuzzyMatch('demo', 'Quality team (DEMO)').score > fuzzyMatch('dmo', 'Quality team (DEMO)').score, 'contiguous substring outranks a scattered match');
  same(rankCandidates('plat', projects, 5).map(row => row.candidate.value), ['OTHER']);
  same(rankCandidates('', projects, 2).map(row => row.candidate.value), ['DEMO', 'OTHER'], 'empty query lists candidates in source order, limited');
  assert.ok(fuzzyMatch('정훈', '박정훈 (parkjh)'), 'Korean substrings match');
  const parts = comboParts('DEMO, OTH');
  assert.equal(parts.head, 'DEMO,'); assert.equal(parts.token, 'OTH'); assert.ok(parts.chosen.has('demo'), 'parts split at the last separator');

  // Click opens the full candidate list; typing narrows it; Tab completes to the real value and keeps the field multi-valued.
  const a = field(() => projects);
  fire(a.input, 'click'); await settle();
  assert.equal(a.list.hidden, false);
  same(texts(a.list), projects.map(project => project.label), 'all Jira candidates are offered on click');
  a.input.value = 'plat'; fire(a.input, 'input'); await settle();
  same(texts(a.list), ['Platform team (OTHER)']);
  assert.ok(a.list.children[0].children.some(part => part.tag === 'mark'), 'matched characters are highlighted');
  const tab = fire(a.input, 'keydown', { key: 'Tab' });
  assert.equal(tab.prevented, true); assert.equal(a.input.value, 'OTHER, '); same(a.picks, ['OTHER']);
  assert.equal(a.list.hidden, true, 'list closes after completion');
  a.input.value = 'OTHER, d'; fire(a.input, 'input'); await settle();
  fire(a.input, 'keydown', { key: 'Tab' });
  assert.equal(a.input.value, 'OTHER, DEMO, ', 'second token completes after the first');
  a.input.value = 'OTHER, DEMO, '; fire(a.input, 'input'); await settle();
  same(texts(a.list), ['Hotel group (HTG)'], 'already chosen values are not offered again');

  // Ctrl+Space reopens the candidates after Esc or completion (also from the middle of typing).
  const h = field(() => projects);
  h.input.value = 'plat'; fire(h.input, 'input'); await settle(); fire(h.input, 'keydown', { key: 'Escape' });
  assert.equal(h.list.hidden, true);
  const reopen = fire(h.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  assert.equal(reopen.prevented, true); same(texts(h.list), ['Platform team (OTHER)'], 'Ctrl+Space shows candidates again');
  fire(h.input, 'keydown', { key: 'Tab' }); assert.equal(h.input.value, 'OTHER, ');
  fire(h.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  same(texts(h.list), ['Quality team (DEMO)', 'Hotel group (HTG)'], 'Ctrl+Space after completion lists the remaining candidates');
  assert.equal(fire(h.input, 'keydown', { key: ' ', code: 'Space' }).prevented, undefined, 'plain Space still types a space');

  // Tab with nothing typed moves focus normally; arrows then Enter select without typing.
  const b = field(() => projects);
  fire(b.input, 'focus'); await settle();
  assert.equal(fire(b.input, 'keydown', { key: 'Tab' }).prevented, undefined, 'Tab on an empty token does not hijack focus');
  fire(b.input, 'keydown', { key: 'ArrowDown' }); fire(b.input, 'keydown', { key: 'ArrowDown' });
  assert.equal(b.list.children[2].className, 'active');
  assert.equal(fire(b.input, 'keydown', { key: 'Enter' }).prevented, true);
  assert.equal(b.input.value, 'HTG, ');
  fire(b.input, 'click'); await settle(); fire(b.input, 'keydown', { key: 'Escape' });
  assert.equal(b.list.hidden, true, 'Escape closes the list');
  fire(b.input, 'click'); await settle(); fire(b.input, 'blur');
  assert.equal(b.list.hidden, true, 'blur closes the list');
  const typed = field(() => projects); typed.input.value = 'DEMO'; fire(typed.input, 'input'); await settle();
  assert.equal(fire(typed.input, 'keydown', { key: 'Enter' }).prevented, undefined, 'Enter on typed text without navigation keeps the typed token');

  // Tab with no match: nothing is hijacked and a hint is shown.
  const c = field(() => projects, { emptyText: query => (query.trim() ? 'No matches' : '') });
  c.input.value = 'zzz'; fire(c.input, 'input'); await settle();
  assert.equal(fire(c.input, 'keydown', { key: 'Tab' }).prevented, undefined);
  same(c.list.children.map(item => item.textContent), ['No matches']);

  // Jira-backed source: debounced, queried with the current token, and Korean candidates complete to the username.
  const queries = [];
  const d = field(async query => { queries.push(query); return reporters; }, { delay: 200 });
  d.input.value = '정'; fire(d.input, 'input'); d.input.value = '정훈'; fire(d.input, 'input');
  same(queries, [], 'nothing is sent before the debounce');
  await flushTimers();
  same(queries, ['정훈'], 'only the latest keystroke queries Jira');
  same(texts(d.list), ['박정훈 (parkjh)']);
  fire(d.input, 'keydown', { key: 'Tab' });
  assert.equal(d.input.value, 'parkjh, ');
  d.input.value = 'parkjh, 이'; fire(d.input, 'input'); await flushTimers();
  assert.equal(queries.at(-1), '이', 'the query is only the token after the last comma');

  // A slow earlier search can never overwrite the newer one.
  const resolvers = [];
  const e = field(query => new Promise(resolve => resolvers.push(() => resolve(query === 'a' ? [{ value: 'old', label: 'old' }] : [{ value: 'new', label: 'new' }]))), {});
  e.input.value = 'a'; fire(e.input, 'input'); e.input.value = 'n'; fire(e.input, 'input');
  resolvers[1](); await settle(); resolvers[0](); await settle();
  same(texts(e.list), ['new'], 'stale response is ignored');

  // Source failure leaves a usable, empty field.
  const f = field(async () => { throw new Error('offline'); });
  f.input.value = 'x'; fire(f.input, 'input'); await settle();
  assert.equal(f.list.children.length, 0);

  // Candidate text is never interpreted as HTML.
  const g = field(() => [{ value: 'x', label: '<img src=x onerror=alert(1)>' }]);
  fire(g.input, 'click'); await settle();
  assert.equal(texts(g.list)[0], '<img src=x onerror=alert(1)>');
  assert.ok(g.list.children[0].children.every(part => ['span', 'mark'].includes(part.tag)));
  console.log('PASS: fuzzy ranking, click/typing candidates, Tab completion with multiple values, exclusion of chosen values, debounced Jira queries, stale-response rejection, and safe rendering.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
