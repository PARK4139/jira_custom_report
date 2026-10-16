
const values=CHART_DATA;
const datasets=PERIOD_DATA;
const titles={'1week':'1 week','2week':'2 weeks',monthly:'Monthly',yearly:'Yearly',q1:'Q1',q2:'Q2',q3:'Q3',q4:'Q4'};
const byId=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
// Every view is cumulative from January 1: a quarter starts from the counts of the quarters before it (rows[0].carry).
function carryOf(rows){const carry=rows[0]&&rows[0].carry;return {created:carry?carry.created:0,resolved:carry?carry.resolved:0}}
function cumulativeRows(rows){
const carry=carryOf(rows);let created=carry.created,resolved=carry.resolved;
return rows.map(row=>({...row,created:created+=row.created,resolved:resolved+=row.resolved}));
}
function cumulativeTotals(rows){
const carry=carryOf(rows);
return {created:rows.reduce((sum,row)=>sum+row.created,carry.created),resolved:rows.reduce((sum,row)=>sum+row.resolved,carry.resolved)};
}
function add(id,tag,attrs,text){const el=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;byId(id).append(el);return el}
function render(period){
const rows=datasets[period];
const chartRows=cumulativeRows(rows);
for(const button of byId('period-tabs').children){const selected=button.dataset.period===period;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1}
byId('report-panel').setAttribute('aria-labelledby','tab-'+period);
byId('period-heading').textContent=titles[period]+' Cumulative Issue Trend';
byId('period-note').textContent='Chart: cumulative Created / Resolved from January 1 of the selected year. Table: counts for each period. '+rows.length+' periods / '+(rows.length*2)+' JQL queries. Date ranges include the start and exclude the end.';
const {created,resolved}=cumulativeTotals(rows);
byId('summary').replaceChildren();
for(const [label,value] of [['Resolved / Created',created?(resolved/created*100).toFixed(1)+'%':'—']]){const item=document.createElement('span');item.textContent=label;const strong=document.createElement('strong');strong.textContent=value;item.append(strong);byId('summary').append(item)}
for(const id of ['grid','series','labels'])byId(id).replaceChildren();
const L=69,R=1037,T=30,B=320,W=R-L,H=B-T,maxY=Math.max(4,Math.ceil(Math.max(1,...chartRows.flatMap(r=>[r.created,r.resolved]))/4)*4);
const x=i=>rows.length===1?(L+R)/2:L+W*i/(rows.length-1),y=v=>B-H*v/maxY;
for(let t=0;t<=4;t++){const v=maxY*t/4,yy=y(v);add('grid','line',{x1:L,y1:yy,x2:R,y2:yy,stroke:'#2a3d56'});add('labels','text',{x:52,y:yy+4,fill:'#a5b6cc','font-size':13,'text-anchor':'end'},v)}
const stride=Math.max(1,Math.ceil(rows.length/12));
rows.forEach((r,i)=>{if(i%stride===0||i===rows.length-1)add('labels','text',{x:x(i),y:350,fill:'#a5b6cc','font-size':12,'text-anchor':'end',transform:'rotate(-30 '+x(i)+' 350)'},r.label)});
for(const [key,color] of [['created','#ff6876'],['resolved','#5bd4a4']]){
const path=chartRows.map((r,i)=>(i?'L':'M')+x(i).toFixed(2)+','+y(r[key]).toFixed(2)).join(' ');
add('series','path',{d:path,stroke:color,'stroke-width':3,fill:'none'});
chartRows.forEach((r,i)=>{const c=add('series','circle',{cx:x(i),cy:y(r[key]),r:rows.length>30?3:5,fill:color});const title=document.createElementNS(ns,'title');title.dataset.cumulativeField=key;title.dataset.cumulativeValue=String(r[key]);title.dataset.periodStart=r.start;title.dataset.periodEnd=r.end;title.textContent=r.start+' to '+r.end+' cumulative '+key+': '+r[key];c.append(title)})
}
byId('period-rows').replaceChildren();
for(const row of rows){const tr=document.createElement('tr');for(const value of [row.start+' / '+row.end,row.created,row.resolved]){const td=document.createElement('td');td.textContent=value;if(typeof value==='number')td.className='num';tr.append(td)}const td=document.createElement('td'),details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='View 2 queries';details.append(summary);for(const field of ['created','resolved']){const pre=document.createElement('pre');pre.textContent=row.queries[field];details.append(pre)}td.append(details);tr.append(td);byId('period-rows').append(tr)}
}
for(const period of Object.keys(datasets)){const button=document.createElement('button');button.type='button';button.role='tab';button.id='tab-'+period;button.dataset.period=period;button.setAttribute('aria-controls','report-panel');button.textContent=titles[period];button.addEventListener('click',()=>render(period));button.addEventListener('keydown',event=>{const buttons=[...byId('period-tabs').children],i=buttons.indexOf(button);let next;if(event.key==='ArrowRight')next=(i+1)%buttons.length;else if(event.key==='ArrowLeft')next=(i+buttons.length-1)%buttons.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=buttons.length-1;else return;event.preventDefault();buttons[next].click();buttons[next].focus()});byId('period-tabs').append(button)}
render(datasets.monthly?'monthly':Object.keys(datasets)[0]);
