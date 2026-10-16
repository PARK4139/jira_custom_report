const renderCombined=render;
render=function(period){
renderCombined(period);byId('summary').replaceChildren();byId('combined-chart').hidden=true;byId('combined-table').hidden=true;
const container=byId('project-graphs');container.replaceChildren();
for(const project of loadedProjectReports){
const rows=project.datasets[period],section=document.createElement('section');section.className='project-report';section.setAttribute('aria-label',project.name+' ('+project.key+')');
const chartRows=cumulativeRows(rows);
const heading=document.createElement('h3');heading.textContent=project.name+' ('+project.key+')';section.append(heading);
const summary=document.createElement('p');for(const [field,label,color] of [['created','Created','red'],['resolved','Resolved','green']]){const span=document.createElement('span');span.className=color;span.dataset.metric=field;span.dataset.count=String(cumulativeTotals(rows)[field]);span.textContent=label+': '+span.dataset.count+'   ';summary.append(span)}
section.append(summary);
const chart=document.createElementNS(ns,'svg');chart.setAttribute('viewBox','0 0 1060 410');chart.setAttribute('role','img');chart.setAttribute('aria-label',project.name+' '+titles[period]+' Cumulative Created / Resolved');
const append=(tag,attrs,text)=>{const node=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==undefined)node.textContent=text;chart.append(node);return node};
const L=69,R=1037,T=30,B=320,maxY=Math.max(4,Math.ceil(Math.max(1,...chartRows.flatMap(row=>[row.created,row.resolved]))/4)*4),x=i=>rows.length===1?(L+R)/2:L+(R-L)*i/(rows.length-1),y=value=>B-(B-T)*value/maxY;
for(let i=0;i<=4;i++){const value=maxY*i/4;append('line',{x1:L,y1:y(value),x2:R,y2:y(value),stroke:'#34465e'});append('text',{x:52,y:y(value)+4,fill:'#a5b6cc','font-size':13,'text-anchor':'end'},value)}
rows.forEach((row,i)=>{if(i%Math.max(1,Math.ceil(rows.length/12))===0||i===rows.length-1)append('text',{x:x(i),y:350,fill:'#a5b6cc','font-size':12,'text-anchor':'end',transform:'rotate(-30 '+x(i)+' 350)'},row.label)});
for(const [field,color] of [['created','#ff6876'],['resolved','#5bd4a4']]){append('path',{d:chartRows.map((row,i)=>(i?'L':'M')+x(i)+','+y(row[field])).join(' '),stroke:color,'stroke-width':3,fill:'none'});chartRows.forEach((row,i)=>{const circle=append('circle',{cx:x(i),cy:y(row[field]),r:3.5,fill:color}),title=document.createElementNS(ns,'title');title.dataset.cumulativeField=field;title.dataset.cumulativeValue=String(row[field]);title.dataset.periodStart=row.start;title.dataset.periodEnd=row.end;title.textContent=project.name+' '+row.start+' cumulative '+field+': '+row[field];circle.append(title)})}
const sumOf=field=>cumulativeTotals(rows)[field],ratioNode=append('text',{x:R,y:16,fill:'#5e6c84','font-size':16,'font-weight':600,'text-anchor':'end'});
ratioNode.dataset.ratio=sumOf('created')?(sumOf('resolved')/sumOf('created')*100).toFixed(1)+'%':'—';ratioNode.textContent=t('ratio')+': '+ratioNode.dataset.ratio;
section.append(chart);
const details=document.createElement('details'),caption=document.createElement('summary');caption.dataset.text='details';caption.textContent='JQL FOR DATA PROOF';details.append(caption);
const table=document.createElement('table'),head=document.createElement('tr');for(const text of ['Period [start, end)','Created','Resolved','JQL']){const th=document.createElement('th');th.textContent=text;head.append(th)}table.append(head);
for(const row of rows){const tr=document.createElement('tr');for(const value of [row.start+' / '+row.end,row.created,row.resolved]){const td=document.createElement('td');td.textContent=value;tr.append(td)}const td=document.createElement('td');for(const field of ['created','resolved']){const pre=document.createElement('pre');pre.textContent=row.queries[field];td.append(pre)}tr.append(td);table.append(tr)}details.append(table);section.append(details);container.append(section);
}
};
