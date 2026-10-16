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
  getBoundingClientRect(){return {left:0,top:0,width:1060,height:410}}
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
const datasets={};for(const period of ['1week','monthly','yearly'])datasets[period]=[payload.year-2020,0,2].map((created,index)=>({label:String(index+1),start:payload.year+'-0'+(index+1)+'-01',end:payload.year+'-0'+(index+2)+'-01',created,resolved:[1,0,3][index],queries:{created:'created query '+payload.year,resolved:'resolved query '+payload.year}}));
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
assert.equal(elements.get('report-title').textContent,'ISSUE STATISTICS WITH JIRA API','the page title is fixed text');
assert.ok(elements.get('period-heading').textContent.length>0);
assert.equal(elements.get('report-panel').hidden,false);
assert.equal(elements.get('project-graphs').children.length,2);
assert.equal(elements.get('project-graphs').children[0].children[0].textContent,'Quality team (DEMO)');
assert.equal(elements.get('project-graphs').children[1].children[0].textContent,'Other team (OTHER)');
assert.equal(elements.get('summary').children.length,0,'no combined totals; each project graph carries its own ratio');
assert.ok(form.elements.every(input=>input.disabled!==true));
}
const tabs=elements.get('period-tabs').children;tabs[2].click();
assert.match(elements.get('period-heading').textContent,/Yearly/);
assert.notEqual(elements.get('project-graphs').children[0].children[1].children[0].textContent,elements.get('project-graphs').children[1].children[1].children[0].textContent);
const rawProjectData=vm.runInContext('JSON.stringify(loadedProjectReports)',context);
const firstProject=elements.get('project-graphs').children[0];
const points=firstProject.querySelectorAll('circle');
assert.deepEqual(points.slice(0,3).map(point=>point.children[0].dataset.cumulativeValue),['6','7','10']);
assert.deepEqual(points.slice(3).map(point=>point.children[0].dataset.cumulativeValue),['1','1','4']);
assert.equal(points[4].attributes.cy,points[3].attributes.cy,'zero periods carry the previous resolved count');
assert.ok(Math.abs(points[2].attributes.cy-(320-290*10/12))<1e-8,'chart scale uses cumulative maximum');
// Hover: a guide line, the highlighted points, and a tooltip with the cumulative values of the nearest period.
{
const svgNode=firstProject.querySelector('svg'),capture=svgNode.querySelector('rect'),tip=firstProject.children.find(node=>node.className==='chart-tip');
const guide=svgNode.querySelectorAll('line').find(node=>node.attributes.class==='hover-line');
const hot=()=>svgNode.querySelectorAll('circle').filter(node=>node.attributes.class==='series-dot hot');
assert.equal(guide.attributes.visibility,'hidden');assert.equal(tip.hidden,true);assert.equal(hot().length,0);
capture.handlers.pointermove[0]({clientX:1037,clientY:120});
assert.equal(guide.attributes.visibility,'visible');assert.equal(hot().length,2,'one highlighted point per series');
assert.equal(String(guide.attributes.x1),String(points[2].attributes.cx),'the guide sits on the last period');
assert.equal(tip.hidden,false);
const tipText=tip.children.map(node=>node.textContent).join(' | ');
assert.match(tipText,/Quality team \(DEMO\)/);assert.match(tipText,/10 \(\+/);assert.match(tipText,/4 \(\+/);assert.match(tipText,/%/);
capture.handlers.pointermove[0]({clientX:0,clientY:120});
assert.equal(String(guide.attributes.x1),String(points[0].attributes.cx),'moving left snaps to the first period');
capture.handlers.pointerleave[0]();
assert.equal(guide.attributes.visibility,'hidden');assert.equal(tip.hidden,true);assert.equal(hot().length,0);
}
const ratios=project=>project.querySelectorAll('text').filter(node=>node.dataset.ratio);
assert.equal(ratios(firstProject).length,1,'ratio is drawn inside each graph');assert.equal(ratios(firstProject)[0].dataset.ratio,'40.0%');assert.equal(ratios(firstProject)[0].textContent,'Resolved-to-Created Ratio: 40.0%');
assert.equal(firstProject.querySelector('table').children[2].children[1].textContent,'1','project table remains per-period');
// Quarterly (four quarter buckets) and daily are cumulative from January 1 like every other period.
elements.get('period-select').value='quarterly';for(const handler of elements.get('period-select').handlers.change)handler();
const quarterProject=elements.get('project-graphs').children[0];
const quarterPoints=quarterProject.querySelectorAll('circle');
assert.deepEqual(quarterPoints.slice(0,4).map(point=>point.children[0].dataset.cumulativeValue),['4','7','8','14'],'created accumulates over Q1..Q4');
assert.deepEqual(quarterPoints.slice(4).map(point=>point.children[0].dataset.cumulativeValue),['1','3','4','6'],'resolved accumulates over Q1..Q4');
assert.equal(quarterProject.querySelectorAll('text').filter(node=>node.dataset.ratio)[0].dataset.ratio,'42.9%','ratio is cumulative resolved / created (6 / 14)');
assert.equal(quarterProject.querySelector('table').children.length,5,'one table row per quarter plus the header');
assert.match(elements.get('period-heading').textContent,/Quarterly|분기간/,'the section heading names the period');
elements.get('period-select').value='daily';for(const handler of elements.get('period-select').handlers.change)handler();
const dailyProject=elements.get('project-graphs').children[0];
assert.deepEqual(dailyProject.querySelectorAll('circle').slice(0,3).map(point=>point.children[0].dataset.cumulativeValue),['2','3','6'],'daily created accumulates day by day');
assert.match(elements.get('period-heading').textContent,/Daily|일간/);
// Output mode: non-cumulative plots each period's own counts and relabels heading, note, and tooltip; switching never queries Jira.
{
const queriesBefore=requests.length,change=value=>{elements.get('calc-mode').value=value;for(const handler of elements.get('calc-mode').handlers.change)handler()};
const periodRows=JSON.parse(vm.runInContext("JSON.stringify(loadedProjectReports[0].datasets[activePeriod])",context));
const pointsOf=(project,key)=>project.querySelectorAll('circle').slice(0,periodRows.length).map(circle=>circle.children[0].dataset[key]);
const cumulativeBefore=pointsOf(elements.get('project-graphs').children[0],'cumulativeValue');
assert.ok(cumulativeBefore.every(value=>value!==undefined),'cumulative is the default mode');
change('periodic');
let project=elements.get('project-graphs').children[0];
assert.deepEqual(pointsOf(project,'periodValue').map(Number),periodRows.map(row=>row.created),'each point is each period own created count');
assert.ok(pointsOf(project,'cumulativeValue').every(value=>value===undefined),'no running totals in non-cumulative mode');
assert.match(elements.get('period-heading').textContent,/Non-cumulative|비누적/);
assert.doesNotMatch(elements.get('period-note').textContent,/cumulative counts|누적 \//,'the note describes per-period counts');
const capture=project.querySelector('svg').querySelector('rect'),tip=project.children.find(node=>node.className==='chart-tip');
capture.handlers.pointermove[0]({clientX:1037,clientY:120});
const periodTip=tip.children.map(node=>node.textContent).join(' | ');
assert.ok(periodTip.includes(String(periodRows.at(-1).created)),'the tooltip shows the hovered period own count');
assert.doesNotMatch(periodTip,/Cumulative|누적/,'no running total in the non-cumulative tooltip');
assert.equal(requests.length,queriesBefore,'switching the output mode does not query Jira');
change('cumulative');
project=elements.get('project-graphs').children[0];
assert.deepEqual(pointsOf(project,'cumulativeValue'),cumulativeBefore,'back to the same cumulative points');
assert.doesNotMatch(elements.get('period-heading').textContent,/Non-cumulative|비누적/);
}
const koPeriods=JSON.parse(vm.runInContext("JSON.stringify(['daily','1week','monthly','quarterly','yearly'].map(period=>messages.ko.periods[period]))",context));
assert.deepEqual(koPeriods,['일간','주간','월간','분기간','연간'],'Korean period names');
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
