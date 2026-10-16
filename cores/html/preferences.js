// Inputs live in localStorage and are mirrored to the git-ignored .local/inputs.json through the server, so they also
// survive a restart on a different port (a new origin starts with an empty localStorage). localStorage wins when both exist.
const SAVED_INPUTS=['year','projects','reporters','period','locale','theme'];
function preference(key,fallback){
let value=null;
try{value=localStorage.getItem('jira-'+key)}catch{}
if(value)return value;
const saved=config.saved&&config.saved[key];
return typeof saved==='string'&&saved?saved:fallback;
}
let locale=preference('locale',(navigator.language||'en').startsWith('ko')?'ko':'en');
if(!messages[locale])locale='en';
let theme=preference('theme','light');
if(!['light','dark'].includes(theme))theme='light';
let statusKey='idle',statusValues={},statusError='',loadedFilters=null;
function t(key,values={}){return Object.entries(values).reduce((text,[key,value])=>text.replaceAll('{'+key+'}',String(value)),messages[locale][key]||key)}
function setStatus(key,values={},error=''){statusKey=key;statusValues=values;statusError=error;status.textContent=(key==='done'||key==='loading'?'':t(key,values))+(error?' '+error:'')}
let inputSyncTimer;
function remember(key,value){try{localStorage.setItem('jira-'+key,value)}catch{}clearTimeout(inputSyncTimer);inputSyncTimer=setTimeout(syncInputs,400)}
async function syncInputs(){
const values={};
for(const key of SAVED_INPUTS){const value=preference(key,'');if(value)values[key]=value}
try{await fetch('/api/inputs',{method:'POST',headers:{'Content-Type':'application/json','X-Session-Token':config.session},body:JSON.stringify({values})})}catch{}
}
function colorChart(){
 const css=getComputedStyle(document.documentElement),colors={created:css.getPropertyValue('--created').trim(),resolved:css.getPropertyValue('--resolved').trim()};
 for(const line of byId('grid').children)line.setAttribute('stroke',css.getPropertyValue('--grid').trim());
 for(const label of byId('labels').children)label.setAttribute('fill',css.getPropertyValue('--muted').trim());
 for(const node of byId('series').children)for(const attr of ['stroke','fill']){const value=node.getAttribute(attr);if(['#ff6876','#bd2944'].includes(value))node.setAttribute(attr,colors.created);if(['#5bd4a4','#16714d'].includes(value))node.setAttribute(attr,colors.resolved)}
 document.querySelectorAll('.legend span').forEach((span,i)=>span.style.setProperty('--dot',i?colors.resolved:colors.created));
 document.querySelectorAll('.project-report svg line').forEach(node=>node.setAttribute('stroke',css.getPropertyValue('--grid').trim()));
 document.querySelectorAll('.project-report svg text').forEach(node=>node.setAttribute('fill',css.getPropertyValue('--muted').trim()));
 document.querySelectorAll('.project-report svg path,.project-report svg circle').forEach(node=>{
  for(const attr of ['stroke','fill']){const value=node.getAttribute(attr);if(['#ff6876','#bd2944'].includes(value))node.setAttribute(attr,colors.created);if(['#5bd4a4','#16714d'].includes(value))node.setAttribute(attr,colors.resolved)}
 });
}
function translateReport(){
 document.documentElement.lang=locale;document.documentElement.dataset.theme=theme;
 document.querySelectorAll('[data-text]').forEach(node=>node.textContent=t(node.dataset.text));
 for(const [id,key] of [['year','year'],['projects','projects'],['reporters','reporters']])byId(id+'-label').textContent=t(key);
 if(typeof showProjectCount==='function')showProjectCount();
 byId('download-csv').textContent=t('csv');byId('download-jpg').textContent=t('jpg');
 const themeButton=byId('theme');themeButton.textContent=t(theme);themeButton.setAttribute('aria-pressed',String(theme==='dark'));themeButton.setAttribute('aria-label',t('theme')+': '+t(theme));
 byId('footer-text').textContent=t('footer');
 for(const option of byId('period-select').options)option.textContent=messages[locale].periods[option.value];
 const rows=datasets[activePeriod]||[];
 byId('period-heading').textContent=messages[locale].periods[activePeriod]+' · '+t('title');
 byId('period-note').textContent=t('note',{buckets:rows.length,count:rows.length*2});
 document.querySelectorAll('table').forEach(table=>table.querySelectorAll('th').forEach((node,i)=>node.textContent=[t('range'),t('created'),t('resolved'),'JQL'][i]));
 document.querySelectorAll('summary:not([data-text])').forEach(node=>node.textContent=t('view'));
 document.querySelectorAll('[data-ratio]').forEach(node=>node.textContent=t('ratio')+': '+node.dataset.ratio);
 document.querySelectorAll('[data-metric]').forEach(node=>node.textContent=t(node.dataset.metric)+': '+Number(node.dataset.count).toLocaleString(locale)+'   ');
 document.querySelectorAll('.legend span').forEach((node,i)=>node.textContent=t(i?'resolved':'created'));
 document.querySelector('svg').setAttribute('aria-label',t('title'));
 document.querySelectorAll('svg title[data-cumulative-field]').forEach(node=>node.textContent=node.dataset.periodStart+' / '+node.dataset.periodEnd+' '+t('cumulative')+' '+t(node.dataset.cumulativeField)+': '+Number(node.dataset.cumulativeValue).toLocaleString(locale));
 byId('report-title').textContent=t('heading',{year:loadedFilters?loadedFilters.year:config.currentYear,period:activePeriod});document.title=byId('report-title').textContent;
 byId('period-select').value=activePeriod;
 byId('report-panel').setAttribute('aria-labelledby','period-heading');
 setStatus(statusKey,statusValues,statusError);colorChart();
}
const originalRender=render;
render=function(period){activePeriod=period;originalRender(period);translateReport()};
byId('period-select').value=activePeriod;

byId('locale').value=locale;
byId('locale').addEventListener('change',()=>{locale=byId('locale').value;remember('locale',locale);render(activePeriod)});
byId('theme').addEventListener('click',()=>{theme=theme==='light'?'dark':'light';remember('theme',theme);translateReport()});
