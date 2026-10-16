// Auto login button (right of the theme button): hidden when unavailable, confirms before saving, and mirrors the server state.
// node tests/check_autologin_button.cjs PAGE_AVAILABLE_OFF PAGE_AVAILABLE_ON PAGE_UNAVAILABLE
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
async function launch(pagePath, {confirmAnswer = true, serverFails = false} = {}) {
  const elements = new Map(), timers = new Map(), posts = [], confirms = [];
  let timerId = 0;
  const document = {documentElement: new Element(), getElementById(id) { if (!elements.has(id)) { const node = new Element(); node.parentElement = new Element('label'); elements.set(id, node); } return elements.get(id); }, createElement: tag => new Element(tag), createElementNS: (ns, tag) => new Element(tag), querySelector(selector) { return this.getElementById(selector); }, querySelectorAll() { return []; }};
  document.getElementById('query-form').elements = ['year', 'projects', 'reporters'].map(id => document.getElementById(id));
  const context = vm.createContext({document, navigator: {language: 'en'}, localStorage: {getItem() { return null; }, setItem() {}},
    matchMedia() { return {matches: false}; }, getComputedStyle() { return {getPropertyValue() { return '#e8edf8'; }}; },
    confirm(message) { confirms.push(message); return confirmAnswer; },
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); },
    async fetch(url, options) {
      if (url === '/api/autologin') {
        const body = JSON.parse(options.body); posts.push({body, session: options.headers['X-Session-Token']});
        return serverFails ? {ok: false, async json() { return {error: 'Could not save the login in Windows Credential Manager.'}; }} : {ok: true, async json() { return {enabled: body.enabled}; }};
      }
      if (url === '/api/projects') return {ok: true, async json() { return {projects: [{key: 'DEMO', name: 'Quality team'}]}; }};
      if (url === '/api/reporters') return {ok: true, async json() { return {reporters: []}; }};
      if (url === '/api/inputs') return {ok: true, async json() { return {saved: true}; }};
      return {ok: true, async json() { return {datasets: {monthly: [], yearly: [], '1week': [], daily: [], quarterly: []}, projectReports: [], queryCount: 1}; }};
    }});
  vm.runInContext(fs.readFileSync(pagePath, 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
  await settle();
  const button = elements.get('autologin'), field = elements.get('autologin-field');
  const click = async () => { for (const fn of button.handlers.click) await fn(); await settle(); };
  return {context, elements, button, field, posts, confirms, click};
}

async function main() {
  const [off, on, unavailable] = process.argv.slice(2);

  // Not available (no store): the control is hidden.
  const none = await launch(unavailable);
  assert.equal(none.field.hidden, true, 'hidden when auto login is not available');

  // Available and off: shows Off, asks before saving, and mirrors the server answer.
  const a = await launch(off);
  assert.equal(a.field.hidden, false);
  assert.equal(a.button.textContent, 'Off'); assert.equal(a.button.attributes['aria-pressed'], 'false');
  assert.equal(a.elements.get('autologin-field').hidden, false);
  const declined = await launch(off, {confirmAnswer: false});
  await declined.click();
  assert.equal(declined.confirms.length, 1); assert.match(declined.confirms[0], /Windows Credential Manager/);
  assert.equal(declined.posts.length, 0, 'declining the confirmation saves nothing');
  assert.equal(declined.button.textContent, 'Off');
  await a.click();
  assert.equal(a.confirms.length, 1, 'turning it on asks first');
  assert.deepEqual(a.posts.map(post => post.body), [{enabled: true}]);
  assert.equal(a.posts[0].session, 'synthetic-session', 'the request carries the session token');
  assert.equal(a.button.textContent, 'On'); assert.equal(a.button.attributes['aria-pressed'], 'true');
  assert.match(a.elements.get('query-status').textContent, /Auto login is on/);
  assert.equal(a.button.disabled, false);
  await a.click();
  assert.equal(a.confirms.length, 1, 'turning it off needs no confirmation');
  assert.deepEqual(a.posts.map(post => post.body), [{enabled: true}, {enabled: false}]);
  assert.equal(a.button.textContent, 'Off');
  assert.match(a.elements.get('query-status').textContent, /saved login was removed/);

  // Korean labels follow the language switch.
  vm.runInContext("locale='ko';translateReport()", a.context);
  assert.equal(a.button.textContent, '꺼짐');
  assert.equal(vm.runInContext("messages.ko.autoLogin", a.context), '자동 로그인');
  assert.equal(a.button.attributes['aria-label'], '자동 로그인: 꺼짐');

  // Already on at launch (a saved login exists): shows On, and turning it off does not ask.
  const b = await launch(on);
  assert.equal(b.button.textContent, 'On'); assert.equal(b.button.attributes['aria-pressed'], 'true');
  await b.click();
  assert.equal(b.confirms.length, 0); assert.deepEqual(b.posts.map(post => post.body), [{enabled: false}]);
  assert.equal(b.button.textContent, 'Off');

  // A storage failure is reported and the state does not change.
  const failing = await launch(off, {serverFails: true});
  await failing.click();
  assert.equal(failing.button.textContent, 'Off', 'the button keeps the real state');
  assert.equal(failing.elements.get('query-status').className, 'error');
  assert.match(failing.elements.get('query-status').textContent, /Could not change Auto login\. Could not save the login/);
  assert.equal(failing.button.disabled, false);
  console.log('PASS: auto login button: hidden when unavailable, confirms before saving, mirrors the server state, Korean labels, and reports failures.');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
