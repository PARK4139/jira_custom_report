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
async function main(){
const elements=new Map();
const document={documentElement:new Element(),getElementById(id){if(!elements.has(id)){const node=new Element();node.parentElement=new Element('label');elements.set(id,node)}return elements.get(id)},createElement(tag){return new Element(tag)},createElementNS(ns,tag){return new Element(tag)},querySelector(selector){return this.getElementById(selector)},querySelectorAll(){return []}};
const form=document.getElementById('query-form');
form.elements=['year','projects','reporters'].map(id=>document.getElementById(id));
const store=new Map(),timers=new Map();let timerId=0,failure=false,holdNext=false,finishHeld;
const requests=[],reporterSearches=[];
const context=vm.createContext({document,navigator:{language:'en'},localStorage:{getItem(key){return store.has(key)?store.get(key):null},setItem(key,value){store.set(key,String(value))}},matchMedia(){return {matches:false}},getComputedStyle(){return {getPropertyValue(){return '#e8edf8'}}},setTimeout(fn){timers.set(++timerId,fn);return timerId},clearTimeout(id){timers.delete(id)},async fetch(url,options){
if(url==='/api/reporters'){reporterSearches.push(JSON.parse(options.body).query);return {ok:true,async json(){return {reporters:[{name:'parkjh',displayName:'박정훈'},{name:'kimsh',displayName:'김선희'}]}}}}
if(url==='/api/projects')return {ok:true,async json(){return {projects:[{key:'DEMO',name:'Quality team'},{key:'OTHER',name:'Platform team'}]}}};
const payload=JSON.parse(options.body);requests.push(payload);
const datasets={};for(const period of ['1week','2week','monthly','yearly'])datasets[period]=[{label:String(payload.year),start:payload.year+'-01-01',end:(payload.year+1)+'-01-01',created:payload.year-2020,resolved:1,queries:{created:'created query',resolved:'resolved query'}}];
const projectReports=payload.projects.map((key,i)=>({key,name:key==='DEMO'?'Quality team':'Platform team',datasets:Object.fromEntries(Object.entries(datasets).map(([period,rows])=>[period,rows.map(row=>({...row,created:row.created+i+1}))]))}));
const response={ok:!failure,async json(){return failure?{error:'Synthetic failure'}:{datasets,projectReports,queryCount:186*payload.projects.length}}};
if(holdNext){holdNext=false;return new Promise(resolve=>{finishHeld=()=>resolve(response)})}return response;
}});
const html=fs.readFileSync(process.argv[2],'utf8');assert.ok(!html.includes('id="query-button"'));assert.ok(html.includes('id="period-select"'));
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],context);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function flush(){const pending=[...timers.values()];timers.clear();for(const fn of pending)fn();await settle()}
function change(id,value,event='change'){if(value!==undefined)elements.get(id).value=value;for(const fn of elements.get(id).handlers[event]||[])fn()}
await settle();await flush();assert.equal(requests.length,1,'valid defaults load without submit');
const count=requests.length;change('period-select','1week');assert.equal(requests.length,count);assert.equal(elements.get('project-graphs').children.length,1);
assert.match(elements.get('period-heading').textContent,/1 week|Weekly/);
change('projects','demo, Platform team');await flush();assert.deepEqual(requests.at(-1).projects,['DEMO','OTHER'],'projects resolve by key or exact name');assert.equal(elements.get('projects').value,'demo, Platform team');assert.equal(elements.get('project-graphs').children.length,2);
const beforeRapid=requests.length;change('year','2024');change('year','2025');change('year','2023');await flush();assert.equal(requests.length,beforeRapid+1);assert.equal(requests.at(-1).year,2023);
holdNext=true;change('year','2024');await flush();const beforeQueued=requests.length;change('year','2025');await flush();assert.equal(requests.length,beforeQueued,'no parallel report request');assert.equal(elements.get('report-panel').hidden,true);
change('period-select','yearly');finishHeld();await settle();assert.equal(elements.get('report-panel').hidden,true,'old response is not displayed');await flush();assert.equal(requests.at(-1).year,2025);assert.ok(elements.get('report-title').textContent.includes('2025'));assert.match(elements.get('period-heading').textContent,/Yearly/);
const beforeUnknown=requests.length;change('projects','NOPE');await flush();assert.equal(requests.length,beforeUnknown,'unknown project names do not query Jira');assert.ok(elements.get('query-status').textContent.includes('NOPE'));
const beforeEmpty=requests.length;change('projects','');await flush();assert.equal(requests.length,beforeEmpty);assert.equal(elements.get('report-panel').hidden,true);
failure=true;change('projects','OTHER');await flush();assert.ok(elements.get('query-status').textContent.includes('Synthetic failure'));assert.equal(elements.get('report-panel').hidden,true);
failure=false;change('year','2024');await flush();assert.equal(elements.get('report-panel').hidden,false);assert.equal(elements.get('project-graphs').children.length,1);
const beforeReporter=requests.length;change('reporters',' , ');await flush();assert.equal(requests.length,beforeReporter);assert.equal(elements.get('report-panel').hidden,true);
change('reporters','박정훈, 김선희 ,박정훈');await flush();assert.deepEqual(requests.at(-1).reporters,['박정훈','김선희'],'comma-separated names are trimmed and de-duplicated');assert.equal(elements.get('report-panel').hidden,false);
assert.equal(store.get('jira-reporters'),'박정훈, 김선희','reporters are remembered');assert.equal(store.get('jira-year'),'2024','year is remembered');assert.equal(store.get('jira-period'),'yearly','period is remembered');assert.deepEqual(JSON.parse(store.get('jira-projects')),['OTHER'],'projects are remembered');
change('reporters','박','input');assert.deepEqual(reporterSearches,[],'reporter search is debounced');await flush();assert.deepEqual([...reporterSearches].sort(),['','박'],'typing queries Jira users and loads the base list once');
const completion={key:'Tab',preventDefault(){completion.prevented=true}};for(const fn of elements.get('reporters').handlers.keydown)fn(completion);
assert.equal(completion.prevented,true);assert.equal(elements.get('reporters').value,'parkjh, ','Tab completes to the real Jira username');await flush();assert.deepEqual(requests.at(-1).reporters,['parkjh'],'completed reporter triggers the report');
console.log('PASS: dropdown-only automatic load, project/year refresh, local period changes, debounce, serialized requests, stale response rejection, empty selection, and recovery.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
