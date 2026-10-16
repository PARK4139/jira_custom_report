
const config=WEB_CONFIG;
const yearSelect=byId('year'), form=byId('query-form'), status=byId('query-status');
for(let year=config.currentYear+1;year>=1970;year--){const option=document.createElement('option');option.value=String(year);option.textContent=year;yearSelect.append(option)}
// Filters are remembered per browser origin; preference()/remember() live in preferences.js (hoisted).
const savedList=key=>{try{const value=JSON.parse(preference(key,'[]'));return Array.isArray(value)?value.filter(item=>typeof item==='string'):[]}catch{return []}};
const savedYear=Number(preference('year',''));
yearSelect.value=String(Number.isInteger(savedYear)&&savedYear>=1970&&savedYear<=config.currentYear+1?savedYear:config.currentYear);
byId('report-panel').hidden=true;byId('period-tabs').hidden=true;
const savedPeriod=preference('period','monthly');
let activePeriod=['1week','2week','monthly','yearly'].includes(savedPeriod)?savedPeriod:'monthly',hasResults=false;
let projectCatalog=[];
let loadedProjectReports=[];
const projectsInput=byId('projects');
const splitTokens=value=>[...new Set(value.split(/[,，、;\n]/).map(name=>name.trim()).filter(Boolean))];
function resolveProjects(){
const keys=[],unknown=[];
for(const token of splitTokens(projectsInput.value)){
const lower=token.toLowerCase(),hit=projectCatalog.find(project=>project.key.toLowerCase()===lower)||projectCatalog.find(project=>project.name.toLowerCase()===lower);
if(hit)keys.push(hit.key);else unknown.push(token);
}
return {keys:[...new Set(keys)],unknown};
}
const reportersInput=byId('reporters');
reportersInput.value=preference('reporters','')||config.reporters.join(', ');
const parseReporters=()=>[...new Set(reportersInput.value.split(/[,，、;\n]/).map(name=>name.trim()).filter(Boolean))];
async function loadProjects(){
const select=projectsInput,previous=resolveProjects().keys;
if(!previous.length)previous.push(...savedList('projects'));
if(!previous.length)previous.push(...config.project.trim().split(/\s+/).filter(Boolean));
select.disabled=true;
hasResults=false;byId('report-panel').hidden=true;byId('period-tabs').hidden=true;byId('period-controls').hidden=true;
status.className='';queryStatus('projectsLoading');
try{
const response=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':config.session},body:'{}'});
const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not load projects.');
projectCatalog=result.projects;
select.value=projectCatalog.filter(project=>previous.includes(project.key)).map(project=>project.key).join(', ');
select.disabled=projectCatalog.length===0;
queryStatus(projectCatalog.length?'projectsReady':'projectsEmpty');
}catch(error){select.value='';status.className='error';queryStatus('projectsFailed',{},error.message)}
if(!select.disabled)scheduleReport();
}
for(const tab of byId('period-tabs').children)tab.addEventListener('click',()=>{activePeriod=tab.dataset.period});
let queryGeneration=0,queryRunning=false,queuedQuery=false,queryTimer;
function invalidateReport(){hasResults=false;byId('period-note').hidden=true;byId('report-panel').hidden=true;byId('period-tabs').hidden=true;byId('period-controls').hidden=true}
function queryStatus(key,values={},error=''){
if(typeof setStatus==='function'){setStatus(key,values,error);return}
status.textContent=key==='loading'?'Loading Jira results for '+values.year+'...':key==='done'?values.year+': '+values.count+' Jira request(s) completed.':key==='failed'?'Jira query failed. '+error:'Choose a project and enter reporters to load results automatically.';
}
function scheduleReport(){queryGeneration++;invalidateReport();clearTimeout(queryTimer);queryTimer=setTimeout(loadReport,250)}
async function loadReport(){
if(queryRunning){queuedQuery=true;return}
const generation=queryGeneration;
const year=Number(yearSelect.value),{keys:projects,unknown}=resolveProjects(),reporters=parseReporters();
if(unknown.length){invalidateReport();status.className='error';queryStatus('projectUnknown',{names:unknown.join(', ')});return}
if(!form.checkValidity()||!projects.length||!reporters.length){invalidateReport();status.className='';queryStatus('idle');return}
const displayNames=projects.map(key=>{const project=projectCatalog.find(project=>project.key===key);return project.name+' ('+key+')'});
queryRunning=true;
remember('year',String(year));remember('projects',JSON.stringify(projects));remember('reporters',reporters.join(', '));remember('period',activePeriod);
status.className='';queryStatus('loading',{year});invalidateReport();
try{
const response=await fetch('/api/report',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':config.session},body:JSON.stringify({year,projects,reporters})});
const result=await response.json();if(generation!==queryGeneration)return;if(!response.ok)throw new Error(result.error||'Query failed.');
datasets=result.datasets;loadedProjectReports=result.projectReports||[];
if(typeof loadedFilters!=='undefined')loadedFilters={year,projects:displayNames,reporters};
const selectedYear=byId('selected-year');if(selectedYear)selectedYear.textContent=year;
render(activePeriod);byId('report-panel').hidden=false;byId('period-note').hidden=false;byId('period-controls').hidden=false;
queryStatus('done',{year,count:result.queryCount,projects:projects.length});hasResults=true;
}catch(error){if(generation===queryGeneration){invalidateReport();status.className='error';queryStatus('failed',{},error.message)}}
finally{queryRunning=false;if(queuedQuery||generation!==queryGeneration){queuedQuery=false;clearTimeout(queryTimer);queryTimer=setTimeout(loadReport,0)}}
}
form.addEventListener('submit',event=>{event.preventDefault();scheduleReport()});
yearSelect.addEventListener('change',()=>{remember('year',yearSelect.value);scheduleReport()});
const projectsChanged=()=>{remember('projects',JSON.stringify(resolveProjects().keys));scheduleReport()};
const reportersChanged=()=>{remember('reporters',reportersInput.value);scheduleReport()};
projectsInput.addEventListener('change',projectsChanged);
reportersInput.addEventListener('change',reportersChanged);
const noMatch=query=>query.trim()?t('comboNoMatch'):'';
attachCombo(projectsInput,{source:()=>projectCatalog.map(project=>({value:project.key,label:project.name+' ('+project.key+')'})),onPick:projectsChanged,limit:10,emptyText:noMatch});
// Jira narrows by the typed text; the unfiltered first page is merged in so skim-style subsequence matches ("ks" -> kimsh) still work.
const reporterCache=new Map();
function searchJiraUsers(query){
const key=query.trim().toLowerCase();
if(!reporterCache.has(key))reporterCache.set(key,(async()=>{
const response=await fetch('/api/reporters',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':config.session},body:JSON.stringify({query:query.trim()})});
const result=await response.json();if(!response.ok)throw new Error(result.error||'Reporter search failed.');
return result.reporters.map(user=>({value:user.name,label:user.displayName===user.name?user.name:user.displayName+' ('+user.name+')'}));
})().catch(error=>{reporterCache.delete(key);throw error}));
return reporterCache.get(key);
}
async function searchReporters(query){
const [searched,base]=await Promise.all([query.trim()?searchJiraUsers(query):[],searchJiraUsers('').catch(()=>[])]);
const merged=new Map();for(const candidate of [...searched,...base])if(!merged.has(candidate.value))merged.set(candidate.value,candidate);
return [...merged.values()];
}
attachCombo(reportersInput,{source:searchReporters,onPick:reportersChanged,limit:10,delay:200,emptyText:noMatch});
byId('period-select').value=activePeriod;
byId('period-select').addEventListener('change',()=>{activePeriod=byId('period-select').value;remember('period',activePeriod);if(hasResults)render(activePeriod);else if(!queryRunning)scheduleReport()});
byId('download-csv').addEventListener('click',async()=>{
const rows=[['project_key','project_name','period','start','end','created','resolved']];
for(const project of loadedProjectReports)for(const [period,values] of Object.entries(project.datasets))for(const row of values)rows.push([project.key,project.name,period,row.start,row.end,row.created,row.resolved]);
const cell=value=>{let text=String(value);if(/^[=+@\-\t\r]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
const csv='\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n');
try{
 const now=new Date(),stamp=now.getFullYear()+String(now.getMonth()+1).padStart(2,'0')+String(now.getDate()).padStart(2,'0')+'-'+String(now.getHours()).padStart(2,'0')+String(now.getMinutes()).padStart(2,'0')+String(now.getSeconds()).padStart(2,'0');
 const response=await fetch('/api/output',{method:'POST',headers:{'Content-Type':'text/csv;charset=utf-8','X-Session-Token':config.session,'X-Output-Name':'jira_'+stamp+'_'+yearSelect.value+'_issues.csv'},body:csv});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'CSV save failed.');setStatus('exportDone',{filename:result.saved});
}catch(error){setStatus('csvFailed',{},error.message)}
});
