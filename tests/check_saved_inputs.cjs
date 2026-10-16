// Saved inputs: restored from the server copy into localStorage, localStorage wins when both exist, and every change is mirrored back.
// node tests/check_saved_inputs.cjs PAGE_WITH_SAVED_VALUES PAGE_WITHOUT_SAVED_VALUES
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  get options(){return this.children}
  get firstChild(){return this.textNode}
  get textContent(){return this.textNode.textContent}
  set textContent(value){this.textNode.textContent=String(value)}
  get selectedOptions(){return this.children.filter(option=>option.selected)}
  constructor(tag=''){this.tag=tag;this.children=[];this.attributes={};this.dataset={};this.handlers={};this.value='';this.textNode={textContent:''};this.style={setProperty(){}};}
  append(...items){this.children.push(...items)}
  before(){}
  remove(){}
  replaceChildren(...items){this.children=items}
  setAttribute(key,value){this.attributes[key]=value}
  getAttribute(key){return this.attributes[key]}
  querySelectorAll(tag){return this.children.flatMap(child=>[...(child.tag===tag?[child]:[]),...child.querySelectorAll(tag)])}
  querySelector(tag){return this.querySelectorAll(tag)[0]}
  addEventListener(event,handler){(this.handlers[event]??=[]).push(handler)}
  click(){for(const handler of this.handlers.click??[])handler()}
  reportValidity(){return true}
  checkValidity(){return true}
}
const settle = () => new Promise(resolve => setImmediate(resolve));
async function launch(pagePath, initialStore) {
  const elements = new Map(), store = new Map(Object.entries(initialStore)), timers = new Map(), requests = [], inputSyncs = [];
  let timerId = 0, localStorageBroken = false;
  const document = {documentElement: new Element(), getElementById(id) { if (!elements.has(id)) { const node = new Element(); node.parentElement = new Element('label'); elements.set(id, node); } return elements.get(id); }, createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag), querySelector(selector) { return this.getElementById(selector); }, querySelectorAll() { return []; }};
  document.getElementById('query-form').elements = ['year', 'projects', 'reporters'].map(id => document.getElementById(id));
  const context = vm.createContext({document, navigator: {language: 'en'},
    localStorage: {getItem(key) { if (localStorageBroken) throw Error('blocked'); return store.has(key) ? store.get(key) : null; }, setItem(key, value) { if (localStorageBroken) throw Error('blocked'); store.set(key, String(value)); }},
    matchMedia() { return {matches: false}; }, getComputedStyle() { return {getPropertyValue() { return '#e8edf8'; }}; },
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); },
    async fetch(url, options) {
      if (url === '/api/inputs') { inputSyncs.push(JSON.parse(options.body).values); return {ok: true, async json() { return {saved: true}; }}; }
      if (url === '/api/reporters') return {ok: true, async json() { return {reporters: [{name: 'parkjh', displayName: '박정훈'}, {name: 'kimsh', displayName: '김선희'}]}; }};
      if (url === '/api/projects') return {ok: true, async json() { return {projects: [{key: 'DEMO', name: 'Quality team'}, {key: 'OTHER', name: 'Platform team'}]}; }};
      const payload = JSON.parse(options.body); requests.push(payload);
      const datasets = {}; for (const period of ['1week', 'monthly', 'yearly']) datasets[period] = [{label: '1', start: payload.year + '-01-01', end: (payload.year + 1) + '-01-01', created: 1, resolved: 1, queries: {created: 'c', resolved: 'r'}}];
      const projectReports = payload.projects.map(key => ({key, name: key, datasets}));
      return {ok: true, async json() { return {datasets, projectReports, queryCount: 1}; }};
    }});
  vm.runInContext(fs.readFileSync(pagePath, 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
  const flush = async () => { const pending = [...timers.values()]; timers.clear(); for (const fn of pending) fn(); await settle(); };
  await settle(); await flush(); await flush();
  const chips = field => JSON.parse(vm.runInContext(`JSON.stringify(${field}Field.values)`, context));
  return {elements, store, requests, inputSyncs, context, flush, chips, settle, breakStorage() { localStorageBroken = true; }};
}

async function main() {
  const [withSaved, withoutSaved] = [process.argv[2], process.argv[3]];

  // A: nothing in localStorage (new origin after a restart): the server copy restores every input and seeds localStorage.
  const a = await launch(withSaved, {});
  assert.equal(a.requests.length, 1, 'restored filters load the report automatically');
  assert.equal(a.requests[0].year, 2024); assert.deepEqual(a.requests[0].projects, ['OTHER']); assert.deepEqual(a.requests[0].reporters, ['parkjh']);
  assert.deepEqual(a.chips('projects').map(chip => chip.value), ['OTHER']);
  assert.deepEqual(a.chips('reporters'), [{value: 'parkjh', label: '박정훈 (parkjh)'}], 'the reporter chip comes back with name and ID');
  assert.equal(a.elements.get('year').value, '2024');
  assert.equal(a.elements.get('locale').value, 'en'); assert.equal(a.context.document.documentElement.dataset.theme, 'dark');
  assert.match(a.elements.get('period-heading').textContent, /Yearly/, 'the saved period is restored');
  for (const [key, value] of Object.entries({year: '2024', period: 'yearly', locale: 'en', theme: 'dark', projects: '["OTHER"]'})) assert.equal(a.store.get('jira-' + key), value, key + ' is seeded into localStorage');
  assert.ok(JSON.parse(a.store.get('jira-reporters')).some(chip => chip.value === 'parkjh'));

  // Every later change is mirrored to the server with all inputs, so a restart keeps the latest values.
  a.elements.get('year').value = '2023'; for (const fn of a.elements.get('year').handlers.change) fn();
  await a.flush(); await a.flush();
  const last = a.inputSyncs.at(-1);
  assert.equal(last.year, '2023'); assert.equal(last.theme, 'dark'); assert.equal(last.locale, 'en'); assert.equal(last.period, 'yearly');
  assert.deepEqual(JSON.parse(last.projects), ['OTHER']); assert.equal(JSON.parse(last.reporters)[0].label, '박정훈 (parkjh)');
  assert.ok(Object.keys(last).every(key => ['year', 'projects', 'reporters', 'period', 'locale', 'theme'].includes(key)), 'only input values are sent');

  // B: localStorage already has values for this origin: it wins over the server copy, per key.
  const b = await launch(withSaved, {'jira-year': '2023', 'jira-projects': '["DEMO"]'});
  assert.equal(b.requests[0].year, 2023); assert.deepEqual(b.requests[0].projects, ['DEMO']);
  assert.deepEqual(b.requests[0].reporters, ['parkjh'], 'keys missing from localStorage still come from the server copy');
  assert.equal(b.store.get('jira-year'), '2023');

  // C: reporters saved by an older version (plain comma-separated IDs) are still restored as chips.
  const c = await launch(withoutSaved, {'jira-reporters': '이민수, 박민호', 'jira-projects': '["DEMO"]'});
  assert.deepEqual(c.chips('reporters').map(chip => chip.value), ['이민수', '박민호']);

  // D: no saved copy and no localStorage: the launch defaults are used.
  const d = await launch(withoutSaved, {});
  assert.deepEqual(d.chips('reporters').map(chip => chip.value), ['sample']);
  assert.equal(d.requests.length, 1);

  // E: blocked localStorage (private mode) must not break the page; the server copy still restores the inputs.
  const e = await launch(withSaved, {});
  e.breakStorage();
  assert.deepEqual(e.chips('projects').map(chip => chip.value), ['OTHER']);
  console.log('PASS: saved inputs restore after a restart, seed localStorage, defer to localStorage, mirror every change, and handle legacy and blocked storage.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
