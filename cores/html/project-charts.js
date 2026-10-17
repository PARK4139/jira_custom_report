const renderCombined=render;
render=function(period){
renderCombined(period);byId('summary').replaceChildren();byId('combined-chart').hidden=true;byId('combined-table').hidden=true;
const container=byId('project-graphs');container.replaceChildren();
for(const project of loadedProjectReports){
const rows=project.datasets[period],section=document.createElement('section');section.className='project-report';section.setAttribute('aria-label',project.name+' ('+project.key+')');
const periodic=calcMode==='periodic',unresolvedMode=calcMode==='unresolved',chartRows=periodic?rows:cumulativeRows(rows);
const heading=document.createElement('h3');heading.textContent=project.name+' ('+project.key+')';section.append(heading);
const summary=document.createElement('p');if(unresolvedMode){const span=document.createElement('span');span.className='blue';span.dataset.metric='unresolved';span.dataset.count=String(rows.at(-1)?.unresolved??0);span.textContent=t('unresolved')+': '+span.dataset.count;summary.append(span)}else for(const [field,label,color] of [['created','Created','red'],['resolved','Resolved','green']]){const span=document.createElement('span');span.className=color;span.dataset.metric=field;span.dataset.count=String(cumulativeTotals(rows)[field]);span.textContent=label+': '+span.dataset.count+'   ';summary.append(span)}
section.append(summary);
const chart=document.createElementNS(ns,'svg');chart.setAttribute('viewBox','0 0 1060 410');chart.setAttribute('role','img');chart.setAttribute('aria-label',project.name+' '+titles[period]+(unresolvedMode?' Unresolved trend':periodic?' Created / Resolved per period':' Cumulative Created / Resolved'));
const append=(tag,attrs,text)=>{const node=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==undefined)node.textContent=text;chart.append(node);return node};
const L=69,R=1037,T=30,B=320,maxY=Math.max(4,Math.ceil(Math.max(1,...chartRows.flatMap(row=>unresolvedMode?[row.unresolved||0]:[row.created,row.resolved]))/4)*4),x=i=>rows.length===1?(L+R)/2:L+(R-L)*i/(rows.length-1),y=value=>B-(B-T)*value/maxY;
for(let i=0;i<=4;i++){const value=maxY*i/4;append('line',{x1:L,y1:y(value),x2:R,y2:y(value),stroke:'#34465e'});append('text',{x:52,y:y(value)+4,fill:'#a5b6cc','font-size':13,'text-anchor':'end'},value)}
rows.forEach((row,i)=>{if(i%Math.max(1,Math.ceil(rows.length/12))===0||i===rows.length-1)append('text',{x:x(i),y:350,fill:'#a5b6cc','font-size':12,'text-anchor':'end',transform:'rotate(-30 '+x(i)+' 350)'},row.label)});
const dots=[];
for(const [field,color] of (unresolvedMode?[['unresolved','#4c9aff']]:[['created','#ff6876'],['resolved','#5bd4a4']])){append('path',{d:chartRows.map((row,i)=>(i?'L':'M')+x(i)+','+y(row[field]||0)).join(' '),stroke:color,'stroke-width':3,fill:'none',pathLength:1,class:'series-line'});chartRows.forEach((row,i)=>{const circle=append('circle',{cx:x(i),cy:y(row[field]||0),r:rows.length>60?1.5:3.5,fill:color,class:'series-dot'}),title=document.createElementNS(ns,'title');if(unresolvedMode){title.dataset.unresolvedValue=String(row.unresolved||0)}else if(periodic){title.dataset.periodField=field;title.dataset.periodValue=String(row[field])}else{title.dataset.cumulativeField=field;title.dataset.cumulativeValue=String(row[field])}title.dataset.periodStart=row.start;title.dataset.periodEnd=row.end;title.textContent=project.name+' '+row.start+(unresolvedMode||periodic?' ':' cumulative ')+field+': '+(row[field]||0);circle.style.setProperty('--i',String(i));(dots[i]??=[]).push(circle);circle.append(title)})}
const sumOf=field=>cumulativeTotals(rows)[field],ratioNode=append('text',{x:R,y:16,fill:'#5e6c84','font-size':16,'font-weight':600,'text-anchor':'end'});
ratioNode.dataset.ratio=sumOf('created')?(sumOf('resolved')/sumOf('created')*100).toFixed(1)+'%':'—';ratioNode.textContent=t('ratio')+': '+ratioNode.dataset.ratio;
// Hover: vertical guide, highlighted points, and a tooltip with the cumulative values of the nearest period.
const guide=append('line',{x1:L,y1:T,x2:L,y2:B,class:'hover-line',stroke:'#94a6bd','stroke-width':1,visibility:'hidden'});
const capture=append('rect',{x:L-8,y:T-12,width:R-L+16,height:B-T+12,fill:'transparent',class:'hover-capture'});
const tip=document.createElement('div');tip.className='chart-tip';tip.hidden=true;tip.setAttribute('role','status');
const activeDot=active=>dots.forEach((pair,j)=>pair.forEach(circle=>circle.setAttribute('class',j===active?'series-dot hot':'series-dot')));
const hideHover=()=>{guide.setAttribute('visibility','hidden');activeDot(-1);tip.hidden=true};
const showHover=event=>{
const box=chart.getBoundingClientRect(),host=section.getBoundingClientRect();
const svgX=(event.clientX-box.left)*1060/(box.width||1060);
const index=rows.length===1?0:Math.max(0,Math.min(rows.length-1,Math.round((svgX-L)/(R-L)*(rows.length-1))));
const row=rows[index],point=chartRows[index];
guide.setAttribute('x1',x(index));guide.setAttribute('x2',x(index));guide.setAttribute('visibility','visible');activeDot(index);
tip.replaceChildren();
const title=document.createElement('strong');title.textContent=project.name+' ('+project.key+')';
const range=document.createElement('span');range.className='tip-range';range.textContent=row.start+' ~ '+row.end;
tip.append(title,range);
for(const [field,color] of (unresolvedMode?[['unresolved','blue']]:[['created','red'],['resolved','green']])){
const line=document.createElement('span');line.className='tip-row '+color;
line.textContent=unresolvedMode?t('unresolved')+': '+Number(row.unresolved||0).toLocaleString(locale):periodic?t(field)+': '+Number(point[field]).toLocaleString(locale):t('cumulative')+' '+t(field)+': '+Number(point[field]).toLocaleString(locale)+' (+'+Number(row[field]).toLocaleString(locale)+')';tip.append(line)}
const ratio=document.createElement('span');ratio.className='tip-row';ratio.textContent=t('ratio')+': '+(point.created?(point.resolved/point.created*100).toFixed(1)+'%':'—');tip.append(ratio);
tip.hidden=false;
const width=tip.offsetWidth||0,left=event.clientX-host.left+16;
tip.style.left=Math.max(8,left+width>host.width-8?event.clientX-host.left-16-width:left)+'px';
tip.style.top=Math.max(8,event.clientY-host.top-12)+'px';
};
capture.addEventListener('pointermove',showHover);capture.addEventListener('pointerdown',showHover);capture.addEventListener('pointerleave',hideHover);capture.addEventListener('pointercancel',hideHover);
section.append(chart,tip);
const details=document.createElement('details'),caption=document.createElement('summary');caption.dataset.text='details';caption.textContent='JQL FOR DATA PROOF';details.append(caption);
const table=document.createElement('table'),head=document.createElement('tr');for(const text of ['Period [start, end)','Created','Resolved',...(unresolvedMode?['Unresolved']:[]),'JQL']){const th=document.createElement('th');th.textContent=text;head.append(th)}table.append(head);
for(const row of rows){const tr=document.createElement('tr');for(const value of [row.start+' / '+row.end,row.created,row.resolved,...(unresolvedMode?[row.unresolved??'—']:[])]){const td=document.createElement('td');td.textContent=value;tr.append(td)}const td=document.createElement('td');for(const field of ['created','resolved',...(row.queries.unresolved?['unresolved']:[])]){const pre=document.createElement('pre');pre.textContent=row.queries[field];td.append(pre)}tr.append(td);table.append(tr)}details.append(table);section.append(details);container.append(section);
}
const guides=document.createElement('section');guides.className='chart-guides';guides.setAttribute('aria-labelledby','chart-guides-heading');
const guideHeading=document.createElement('h3');guideHeading.id='chart-guides-heading';guideHeading.dataset.text='chartGuideHeading';guideHeading.textContent=t('chartGuideHeading');guides.append(guideHeading);
for(const project of loadedProjectReports){
const guide=document.createElement('section');guide.className='chart-guide';
const heading=document.createElement('h4');heading.textContent=project.name+' ('+project.key+')';guide.append(heading);
const points=document.createElement('ul');
const keys=unresolvedMode?['guideUnresolved1','guideUnresolved2','guideUnresolved3']:periodic?['guidePeriodic1','guidePeriodic2','guidePeriodic3']:['guideCumulative1','guideCumulative2','guideCumulative3'];
for(const key of keys){const point=document.createElement('li');point.dataset.text=key;point.textContent=t(key);points.append(point)}
guide.append(points);guides.append(guide);
}
container.append(guides);
};
