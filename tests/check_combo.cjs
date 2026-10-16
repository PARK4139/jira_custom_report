const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Node {
  constructor(tag = '') { this.tag = tag; this.children = []; this.attributes = {}; this.handlers = {}; this.className = ''; this.hidden = false; this.textContent = ''; this.value = ''; this.placeholder = ''; this.parentNode = null; }
  append(...items) { for (const item of items) { item.remove(); item.parentNode = this; this.children.push(item); } }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  before(node) { node.remove(); node.parentNode = this.parentNode; this.parentNode.children.splice(this.parentNode.children.indexOf(this), 0, node); }
  remove() { if (this.parentNode) { this.parentNode.children.splice(this.parentNode.children.indexOf(this), 1); this.parentNode = null; } }
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
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8') + '\nthis.fuzzyMatch=fuzzyMatch;this.rankCandidates=rankCandidates;this.attachCombo=attachCombo;', context);
const { fuzzyMatch, rankCandidates, attachCombo } = context;
const flushTimers = async () => { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); await settle(); };
const texts = list => list.children.map(item => item.children.map(part => part.textContent).join(''));
function field(source, options = {}) {
  const label = new Node('label'), input = new Node('input'); label.append(input); input.placeholder = 'ctrl space + tab';
  const changes = [];
  const combo = attachCombo(input, { source, onChange: () => changes.push(combo.values.map(chip => chip.value).join()), ...options });
  const box = input.parentNode, list = box.children.at(-1);
  const chipNodes = () => box.children.filter(node => node.className === 'chip');
  return { input, box, list, combo, changes, chipNodes, chipTexts: () => chipNodes().map(node => node.children[0].textContent) };
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
const resolveProject = text => projects.find(project => project.value.toLowerCase() === text.toLowerCase() || project.label.toLowerCase() === text.toLowerCase()) ?? null;

async function main() {
  // Fuzzy ranking: skim-style subsequence match, substring and word-start matches win, non-subsequences are dropped.
  assert.equal(fuzzyMatch('xyz', 'Quality team (DEMO)'), null);
  assert.ok(fuzzyMatch('qt', 'Quality team (DEMO)'), 'subsequence matches');
  assert.ok(fuzzyMatch('demo', 'Quality team (DEMO)').score > fuzzyMatch('dmo', 'Quality team (DEMO)').score, 'contiguous substring outranks a scattered match');
  same(rankCandidates('plat', projects, 5).map(row => row.candidate.value), ['OTHER']);
  same(rankCandidates('', projects, 2).map(row => row.candidate.value), ['DEMO', 'OTHER'], 'empty query lists candidates in source order, limited');
  assert.ok(fuzzyMatch('정훈', '박정훈 (parkjh)'), 'Korean substrings match');

  // Click opens the full candidate list; typing narrows it; Tab turns the candidate into a chip.
  const a = field(() => projects, { resolve: resolveProject });
  assert.equal(a.input.placeholder, 'ctrl space + tab');
  fire(a.input, 'click'); await settle();
  assert.equal(a.list.hidden, false);
  same(texts(a.list), projects.map(project => project.label), 'all Jira candidates are offered on click');
  a.input.value = 'plat'; fire(a.input, 'input'); await settle();
  same(texts(a.list), ['Platform team (OTHER)']);
  assert.ok(a.list.children[0].children.some(part => part.tag === 'mark'), 'matched characters are highlighted');
  const tab = fire(a.input, 'keydown', { key: 'Tab' });
  assert.equal(tab.prevented, true); assert.equal(a.input.value, '', 'the input is cleared once the value is a chip');
  same(a.chipTexts(), ['Platform team (OTHER)'], 'the chip shows the full label');
  same(a.combo.values, [{ value: 'OTHER', label: 'Platform team (OTHER)' }]);
  assert.equal(a.input.placeholder, '', 'placeholder is hidden once a chip exists');
  assert.equal(a.list.hidden, true, 'list closes after completion');
  a.input.value = 'd'; fire(a.input, 'input'); await settle();
  fire(a.input, 'keydown', { key: 'Tab' });
  same(a.chipTexts(), ['Platform team (OTHER)', 'Quality team (DEMO)'], 'chips accumulate in order');
  same(a.changes, ['OTHER', 'OTHER,DEMO'], 'every pick notifies the page');
  a.input.value = ''; fire(a.input, 'input'); await settle();
  same(texts(a.list), ['Hotel group (HTG)'], 'already chosen values are not offered again');

  // Removing chips: the x button, and Backspace on an empty input; the placeholder returns when none are left.
  a.chipNodes()[0].children[1].handlers.click[0]();
  same(a.combo.values.map(chip => chip.value), ['DEMO']); same(a.chipTexts(), ['Quality team (DEMO)']);
  fire(a.input, 'keydown', { key: 'Backspace' }); await settle();
  same(a.combo.values, []); assert.equal(a.chipNodes().length, 0); assert.equal(a.input.placeholder, 'ctrl space + tab');
  a.input.value = 'x'; assert.equal(fire(a.input, 'keydown', { key: 'Backspace' }).prevented, undefined, 'Backspace with text just edits the text');

  // Typed text: a known value becomes a chip on Enter, comma, or blur; unknown text stays put when the field has no free values.
  const t = field(() => projects, { resolve: resolveProject });
  t.input.value = 'demo'; fire(t.input, 'input'); await settle();
  assert.equal(fire(t.input, 'keydown', { key: 'Enter' }).prevented, true);
  same(t.combo.values, [{ value: 'DEMO', label: 'Quality team (DEMO)' }], 'Enter commits a typed project name as its chip');
  t.input.value = 'htg, nope'; fire(t.input, 'input');
  same(t.combo.values.map(chip => chip.value), ['DEMO', 'HTG'], 'a comma commits the finished token');
  assert.equal(t.input.value, 'nope'); assert.equal(t.combo.pending, 'nope');
  fire(t.input, 'blur');
  assert.equal(t.input.value, 'nope', 'unknown text is not turned into a chip');
  assert.equal(t.changes.at(-1), 'DEMO,HTG', 'the page is still notified so it can report the unknown text');
  t.input.value = 'nope, other'; fire(t.input, 'input');
  assert.equal(t.input.value, 'nope, other', 'unresolved tokens are kept in the input');

  // Fields that accept free values (reporter IDs) turn any typed token into a chip and ignore duplicates.
  const f = field(async () => reporters, { allowRaw: true });
  f.input.value = '이민수, 박민호 ,이민수'; fire(f.input, 'input');
  fire(f.input, 'keydown', { key: 'Enter' }); await settle();
  same(f.combo.values.map(chip => chip.value), ['이민수', '박민호'], 'free values are trimmed, de-duplicated chips');
  f.input.value = 'kimsh'; fire(f.input, 'blur');
  same(f.combo.values.map(chip => chip.value), ['이민수', '박민호', 'kimsh'], 'blur commits the pending text');

  // Programmatic set/relabel (restoring saved chips, adding names once Jira resolves them) is silent.
  const s = field(() => reporters, { allowRaw: true });
  s.combo.set([{ value: 'parkjh', label: 'parkjh' }, { value: 'kimsh' }]);
  same(s.chipTexts(), ['parkjh', 'kimsh']); same(s.changes, []);
  s.combo.relabel('parkjh', '박정훈 (parkjh)');
  same(s.chipTexts(), ['박정훈 (parkjh)', 'kimsh'], 'the chip shows both the name and the employee ID once known');

  // Ctrl+Space reopens the candidates after Esc or completion (also from the middle of typing).
  const h = field(() => projects);
  h.input.value = 'plat'; fire(h.input, 'input'); await settle(); fire(h.input, 'keydown', { key: 'Escape' });
  assert.equal(h.list.hidden, true);
  const reopen = fire(h.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  assert.equal(reopen.prevented, true); same(texts(h.list), ['Platform team (OTHER)'], 'Ctrl+Space shows candidates again');
  fire(h.input, 'keydown', { key: 'Tab' }); same(h.combo.values.map(chip => chip.value), ['OTHER']);
  fire(h.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  same(texts(h.list), ['Quality team (DEMO)', 'Hotel group (HTG)'], 'Ctrl+Space after completion lists the remaining candidates');
  assert.equal(fire(h.input, 'keydown', { key: ' ', code: 'Space' }).prevented, undefined, 'plain Space still types a space');

  // Ctrl+Space on a list that is already open (e.g. after a mouse click on the field) adds the highlighted candidate as a chip.
  const k = field(() => projects);
  fire(k.input, 'focus'); await settle();
  fire(k.input, 'keydown', { key: 'ArrowDown' }); fire(k.input, 'keydown', { key: 'ArrowDown' });
  assert.equal(k.list.children[2].className, 'active');
  const add = fire(k.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  assert.equal(add.prevented, true, 'Ctrl+Space never types a space');
  same(k.combo.values.map(chip => chip.value), ['HTG'], 'Ctrl+Space adds the highlighted (third) candidate');
  assert.equal(k.list.hidden, true, 'the list closes after the chip is added');
  fire(k.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  same(texts(k.list), ['Quality team (DEMO)', 'Platform team (OTHER)'], 'a second Ctrl+Space reopens the remaining candidates');
  fire(k.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  same(k.combo.values.map(chip => chip.value), ['HTG', 'DEMO'], 'and a third one adds the first remaining candidate');

  // Clicking the field opens the list; Ctrl+Space then adds the first candidate without any arrow key.
  const m = field(() => projects);
  fire(m.input, 'click'); await settle();
  fire(m.input, 'keydown', { key: ' ', code: 'Space', ctrlKey: true }); await settle();
  assert.equal(m.combo.values.length, 1, 'one chip after click + Ctrl+Space');

  // Tab with nothing typed moves focus normally; arrows then Enter select without typing.
  const b = field(() => projects);
  fire(b.input, 'focus'); await settle();
  assert.equal(fire(b.input, 'keydown', { key: 'Tab' }).prevented, undefined, 'Tab on an empty token does not hijack focus');
  fire(b.input, 'keydown', { key: 'ArrowDown' }); fire(b.input, 'keydown', { key: 'ArrowDown' });
  assert.equal(b.list.children[2].className, 'active');
  assert.equal(fire(b.input, 'keydown', { key: 'Enter' }).prevented, true);
  same(b.combo.values.map(chip => chip.value), ['HTG']);
  fire(b.input, 'click'); await settle(); fire(b.input, 'keydown', { key: 'Escape' });
  assert.equal(b.list.hidden, true, 'Escape closes the list');
  fire(b.input, 'click'); await settle(); fire(b.input, 'blur');
  assert.equal(b.list.hidden, true, 'blur closes the list');

  // Tab with no match: nothing is hijacked and a hint is shown.
  const c = field(() => projects, { emptyText: query => (query.trim() ? 'No matches' : '') });
  c.input.value = 'zzz'; fire(c.input, 'input'); await settle();
  assert.equal(fire(c.input, 'keydown', { key: 'Tab' }).prevented, undefined);
  same(c.list.children.map(item => item.textContent), ['No matches']);

  // Jira-backed source: debounced, queried with the typed text, and Korean candidates become chips labelled with name and ID.
  const queries = [];
  const d = field(async query => { queries.push(query); return reporters; }, { delay: 200, allowRaw: true });
  d.input.value = '정'; fire(d.input, 'input'); d.input.value = '정훈'; fire(d.input, 'input');
  same(queries, [], 'nothing is sent before the debounce');
  await flushTimers();
  same(queries, ['정훈'], 'only the latest keystroke queries Jira');
  same(texts(d.list), ['박정훈 (parkjh)']);
  fire(d.input, 'keydown', { key: 'Tab' });
  same(d.combo.values, [{ value: 'parkjh', label: '박정훈 (parkjh)' }]);
  same(d.chipTexts(), ['박정훈 (parkjh)']);
  d.input.value = '이'; fire(d.input, 'input'); await flushTimers();
  assert.equal(queries.at(-1), '이', 'the query is only the text typed after the chips');

  // A slow earlier search can never overwrite the newer one.
  const resolvers = [];
  const e = field(query => new Promise(resolve => resolvers.push(() => resolve(query === 'a' ? [{ value: 'old', label: 'old' }] : [{ value: 'new', label: 'new' }]))), {});
  e.input.value = 'a'; fire(e.input, 'input'); e.input.value = 'n'; fire(e.input, 'input');
  resolvers[1](); await settle(); resolvers[0](); await settle();
  same(texts(e.list), ['new'], 'stale response is ignored');

  // Source failure leaves a usable, empty field.
  const g0 = field(async () => { throw new Error('offline'); });
  g0.input.value = 'x'; fire(g0.input, 'input'); await settle();
  assert.equal(g0.list.children.length, 0);

  // Candidate and chip text is never interpreted as HTML.
  const g = field(() => [{ value: 'x', label: '<img src=x onerror=alert(1)>' }]);
  fire(g.input, 'click'); await settle();
  assert.equal(texts(g.list)[0], '<img src=x onerror=alert(1)>');
  assert.ok(g.list.children[0].children.every(part => ['span', 'mark'].includes(part.tag)));
  fire(g.input, 'keydown', { key: 'ArrowDown' }); fire(g.input, 'keydown', { key: 'Enter' });
  same(g.chipTexts(), ['<img src=x onerror=alert(1)>']); assert.equal(g.chipNodes()[0].children[0].tag, 'span');
  console.log('PASS: fuzzy ranking, chips for every selected value, name+ID labels, Tab/Enter/comma/blur commits, Backspace and x removal, Ctrl+Space, debounced Jira queries, stale-response rejection, and safe rendering.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
