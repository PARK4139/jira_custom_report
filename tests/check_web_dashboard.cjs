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
async function main(){
const elements=new Map();
const document={documentElement:new Element(),getElementById(id){if(!elements.has(id)){const node=new Element();node.parentElement=new Element('label');elements.set(id,node)}return elements.get(id)},createElement(tag){return new Element(tag)},createElementNS(ns,tag){return new Element(tag)},querySelector(selector){return this.getElementById(selector)},querySelectorAll(){return []}};
const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
document.querySelectorAll=selector=>{
 const nodes=[...new Set([...elements.values()].flatMap(node=>[node,...descendants(node)]))];
 if(selector==='[data-text]')return nodes.filter(node=>node.dataset.text);
 if(selector==='[data-metric]')return nodes.filter(node=>node.dataset.metric);
 if(selector==='summary:not([data-text])')return nodes.filter(node=>node.tag==='summary'&&!node.dataset.text);
 if(selector==='table')return nodes.filter(node=>node.tag==='table');
 if(selector.startsWith('.project-report svg ')){
  const tags=selector.split(',').map(part=>part.trim().split(' ').at(-1));
  return descendants(document.getElementById('project-graphs')).filter(node=>tags.includes(node.tag));
 }
 return [];
};
const form=document.getElementById('query-form');
form.elements=['year','projects','reporters','query-button'].map(id=>document.getElementById(id));
let failure=false;const requests=[];
const context=vm.createContext({document,setTimeout,clearTimeout,navigator:{language:'en'},localStorage:{getItem(){return null},setItem(){}},matchMedia(){return {matches:false}},getComputedStyle(){return {getPropertyValue(key){return ({'--created':'#bd2944','--resolved':'#16714d','--grid':'#d2dce8','--muted':'#405674'})[key]||'#e8edf8'}}},async fetch(url,options){
if(url==='/api/inputs')return {ok:true,async json(){return {saved:true}}};
if(url==='/api/reporters')return {ok:true,async json(){return {reporters:[{name:'sample',displayName:'Sample User'}]}}};
if(url==='/api/projects')return {ok:true,async json(){return {projects:[{key:'DEMO',name:'Quality team'},{key:'OTHER',name:'Other team'}]}}};
const payload=JSON.parse(options.body);requests.push(payload);
if(failure)return {ok:false,async json(){return {error:'Synthetic query failure'}}};
const datasets={};for(const period of ['1week','2week','monthly','yearly'])datasets[period]=[payload.year-2020,0,2].map((created,index)=>({label:String(index+1),start:payload.year+'-0'+(index+1)+'-01',end:payload.year+'-0'+(index+2)+'-01',created,resolved:[1,0,3][index],queries:{created:'created query '+payload.year,resolved:'resolved query '+payload.year}}));
datasets.quarterly=[3,2,0,5].map((created,index)=>({label:'Q'+(index+1),start:payload.year+'-'+['01','04','07','10'][index]+'-01',end:(index<3?payload.year+'-'+['04','07','10'][index]:(payload.year+1)+'-01')+'-01',created,resolved:[1,2,1,2][index],queries:{created:'q',resolved:'q'}}));
datasets.daily=[1,0,2].map((created,index)=>({label:'01/0'+(index+1),start:payload.year+'-01-0'+(index+1),end:payload.year+'-01-0'+(index+2),created,resolved:[0,1,1][index],queries:{created:'d',resolved:'d'}}));
const projectReports=payload.projects.map((key,i)=>({key,name:key==='DEMO'?'Quality team':'Other team',datasets:Object.fromEntries(Object.entries(datasets).map(([period,rows])=>[period,rows.map(row=>({...row,created:row.created+i+1}))]))}));
return {ok:true,async json(){return {datasets,projectReports,queryCount:186*payload.projects.length}}};
}});
const script=fs.readFileSync(process.argv[2],'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
vm.runInContext(script,context);
await new Promise(resolve=>setImmediate(resolve));
assert.equal(requests.length,0);
assert.equal(elements.get('projects').disabled,false,'project field is ready after the catalog loads');
assert.equal(elements.get('report-panel').hidden,true);
vm.runInContext("projectsField.set([{value:'DEMO',label:'Quality team (DEMO)'},{value:'OTHER',label:'Other team (OTHER)'}])",context);
for(const year of [2024,2025]){
elements.get('year').value=String(year);
await vm.runInContext('loadReport()',context);
assert.equal(requests.at(-1).year,year);
assert.deepEqual(requests.at(-1).projects,['DEMO','OTHER']);
assert.ok(elements.get('report-title').textContent.includes('ISSUE Resolved/Created'));
assert.ok(elements.get('report-title').textContent.includes(String(year)));
assert.equal(elements.get('report-panel').hidden,false);
assert.equal(elements.get('project-graphs').children.length,2);
assert.equal(elements.get('project-graphs').children[0].children[0].textContent,'Quality team (DEMO)');
assert.equal(elements.get('project-graphs').children[1].children[0].textContent,'Other team (OTHER)');
assert.equal(elements.get('summary').children.length,0,'no combined totals; each project graph carries its own ratio');
assert.ok(form.elements.every(input=>input.disabled!==true));
}
const tabs=elements.get('period-tabs').children;tabs[3].click();
assert.match(elements.get('period-heading').textContent,/Yearly/);
assert.notEqual(elements.get('project-graphs').children[0].children[1].children[0].textContent,elements.get('project-graphs').children[1].children[1].children[0].textContent);
const rawProjectData=vm.runInContext('JSON.stringify(loadedProjectReports)',context);
const firstProject=elements.get('project-graphs').children[0];
const points=firstProject.querySelectorAll('circle');
assert.deepEqual(points.slice(0,3).map(point=>point.children[0].dataset.cumulativeValue),['6','7','10']);
assert.deepEqual(points.slice(3).map(point=>point.children[0].dataset.cumulativeValue),['1','1','4']);
assert.equal(points[4].attributes.cy,points[3].attributes.cy,'zero periods carry the previous resolved count');
assert.ok(Math.abs(points[2].attributes.cy-(320-290*10/12))<1e-8,'chart scale uses cumulative maximum');
const ratios=project=>project.querySelectorAll('text').filter(node=>node.dataset.ratio);
assert.equal(ratios(firstProject).length,1,'ratio is drawn inside each graph');assert.equal(ratios(firstProject)[0].dataset.ratio,'40.0%');assert.equal(ratios(firstProject)[0].textContent,'Resolved / Created: 40.0%');
assert.equal(firstProject.querySelector('table').children[2].children[1].textContent,'1','project table remains per-period');
// Quarterly (four quarter buckets) and daily are cumulative from January 1 like every other period.
elements.get('period-select').value='quarterly';for(const handler of elements.get('period-select').handlers.change)handler();
const quarterProject=elements.get('project-graphs').children[0];
const quarterPoints=quarterProject.querySelectorAll('circle');
assert.deepEqual(quarterPoints.slice(0,4).map(point=>point.children[0].dataset.cumulativeValue),['4','7','8','14'],'created accumulates over Q1..Q4');
assert.deepEqual(quarterPoints.slice(4).map(point=>point.children[0].dataset.cumulativeValue),['1','3','4','6'],'resolved accumulates over Q1..Q4');
assert.equal(quarterProject.querySelectorAll('text').filter(node=>node.dataset.ratio)[0].dataset.ratio,'42.9%','ratio is cumulative resolved / created (6 / 14)');
assert.equal(quarterProject.querySelector('table').children.length,5,'one table row per quarter plus the header');
assert.match(elements.get('report-title').textContent,/quarterly ISSUE/,'the title names the period');
elements.get('period-select').value='daily';for(const handler of elements.get('period-select').handlers.change)handler();
const dailyProject=elements.get('project-graphs').children[0];
assert.deepEqual(dailyProject.querySelectorAll('circle').slice(0,3).map(point=>point.children[0].dataset.cumulativeValue),['2','3','6'],'daily created accumulates day by day');
assert.match(elements.get('report-title').textContent,/daily ISSUE/);
const koPeriods=JSON.parse(vm.runInContext("JSON.stringify(['daily','1week','2week','monthly','quarterly','yearly'].map(period=>messages.ko.periods[period]))",context));
assert.deepEqual(koPeriods,['일간','1주간','2주간','월간','분기간','연간'],'Korean period names');
assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(Object.keys(messages.ko.periods))",context)).filter(key=>/^q\d$/.test(key)),[],'the separate 1-4 quarter options are gone');
elements.get('period-select').value='yearly';for(const handler of elements.get('period-select').handlers.change)handler();
const beforePreferences=requests.length;
elements.get('locale').value='ko';for(const handler of elements.get('locale').handlers.change)handler();
const project=elements.get('project-graphs').children[0];
assert.match(project.children[1].children[0].textContent,/생성:/);
assert.equal(project.querySelector('th').textContent,'기간 [시작일 포함, 종료일 제외)');
assert.equal(project.querySelector('summary').textContent,'JQL FOR DATA PROOF');
elements.get('theme').click();elements.get('theme').click();
assert.equal(project.querySelector('path').getAttribute('stroke'),'#bd2944');
assert.equal(project.querySelector('line').getAttribute('stroke'),'#d2dce8');
assert.equal(requests.length,beforePreferences,'language/theme must not query Jira');
assert.equal(vm.runInContext('JSON.stringify(loadedProjectReports)',context),rawProjectData,'redrawing cannot accumulate twice');
elements.get('locale').value='en';for(const handler of elements.get('locale').handlers.change)handler();
vm.runInContext("projectsField.set([{value:'OTHER',label:'Other team (OTHER)'}])",context);
await vm.runInContext('loadReport()',context);
assert.deepEqual(requests.at(-1).projects,['OTHER']);
assert.equal(elements.get('project-graphs').children.length,1);
assert.equal(elements.get('project-graphs').children[0].children[0].textContent,'Other team (OTHER)');
failure=true;await vm.runInContext('loadReport()',context);
assert.equal(elements.get('report-panel').hidden,true);
assert.equal(elements.get('query-status').textContent,'Jira query failed. Synthetic query failure');
assert.ok(form.elements.every(input=>input.disabled!==true));
console.log('Web dashboard: year-specific fetch, updated counts, period tabs, and failure recovery passed.');
}
main().catch(error=>{console.error(error);process.exitCode=1});
