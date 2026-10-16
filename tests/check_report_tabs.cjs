// Execute generated report code against an in-memory DOM; no browser or network.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
  constructor() { this.children = []; this.attributes = {}; this.dataset = {}; this.handlers = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(event, handler) { this.handlers[event] = handler; }
  click() { this.handlers.click(); }
  focus() { this.focused = true; }
}
const elements = new Map();
const document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  createElement() { return new Element(); }, createElementNS() { return new Element(); },
};
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const context=vm.createContext({document});
vm.runInContext(script,context);
const sample=JSON.parse(vm.runInContext(`JSON.stringify(cumulativeRows(Object.freeze([
Object.freeze({created:2,resolved:0}),Object.freeze({created:0,resolved:3}),Object.freeze({created:5,resolved:0})])))`,context));
assert.deepEqual(sample.map(row=>row.created),[2,2,7]);
assert.deepEqual(sample.map(row=>row.resolved),[0,3,3]);
assert.equal(vm.runInContext('cumulativeRows([{created:1,resolved:0}])[0].created',context),1,'new series starts fresh');
const originalData=vm.runInContext('JSON.stringify(datasets)',context);
const tabs = elements.get('period-tabs').children;
assert.equal(tabs.length, 4);
const expected = { '1week': 53, '2week': 27, monthly: 12, yearly: 1 };
for (const tab of tabs) {
  tab.click();
  assert.equal(tab.attributes['aria-selected'], 'true');
  assert.equal(elements.get('period-rows').children.length, expected[tab.dataset.period]);
  assert.equal(tabs.filter(t => t.attributes['aria-selected'] === 'true').length, 1);
  assert.equal(elements.get('report-panel').attributes['aria-labelledby'], tab.id);
  assert.equal(elements.get('summary').children.length, 1);
  assert.ok(elements.get('series').children.length > 2);
  const points=elements.get('series').children.filter(node=>node.attributes.cy!==undefined);
  const count=expected[tab.dataset.period];
  assert.equal(points.length,count*2);
  for(let i=0;i<count;i++){
    assert.equal(points[i].children[0].dataset.cumulativeValue,String(2*(i+1)));
    assert.equal(points[count+i].children[0].dataset.cumulativeValue,String(i+1));
  }
  assert.equal(elements.get('period-rows').children[0].children[1].textContent,2,'table retains period count');
  assert.equal(vm.runInContext('JSON.stringify(datasets)',context),originalData,'redraw never mutates period counts');
}
tabs[0].handlers.keydown({key: 'End', preventDefault() {}});
assert.equal(tabs.at(-1).attributes['aria-selected'], 'true');
assert.equal(tabs.at(-1).focused, true);
console.log('Report tabs: four views, row counts, charts, ARIA selection, and keyboard navigation passed.');
