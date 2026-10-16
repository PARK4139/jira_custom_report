async function exportJpg(){
 if(!hasResults||!loadedFilters||queryRunning)return;
 const previousStatus=[statusKey,statusValues,statusError],button=byId('download-jpg');button.disabled=true;button.textContent=t('exporting');
 const controls=[...form.elements,byId('locale'),byId('theme'),byId('period-select'),byId('download-csv')];
 const disabled=controls.map(control=>control.disabled);controls.forEach(control=>control.disabled=true);
 try{
  if(document.fonts)await document.fonts.ready;
  const css=getComputedStyle(document.documentElement),canvas=document.createElement('canvas');
  canvas.width=1800;const ctx=canvas.getContext('2d'),lines=[];
  const titleFont='bold 34px "Segoe UI", "Malgun Gothic", sans-serif',bodyFont='24px "Segoe UI", "Malgun Gothic", sans-serif';
  let font=titleFont;
  // Measure first, then size the canvas so even long filters remain in the JPG.
  function text(value){ctx.font=font;let line='';for(const char of value){if(ctx.measureText(line+char).width>1670){lines.push({text:line,font});line=''}line+=char}lines.push({text:line,font})}
  text(byId('report-title').textContent);font=bodyFont;
  text(messages[locale].periods[activePeriod]);text(t('projects')+': '+loadedFilters.projects.join(', '));text(t('reporters')+': '+loadedFilters.reporters.join(', '));
  const rows=datasets[activePeriod],{created,resolved}=cumulativeTotals(rows);
  text(t('created')+': '+created+'    '+t('resolved')+': '+resolved+'    '+t('ratio')+': '+(created?(resolved/created*100).toFixed(1)+'%':'—'));
  text(t(calcMode==='periodic'?'notePeriodic':'note',{buckets:rows.length,count:rows.length*2}));
  const chartY=62+lines.length*42+24;
  const charts=[...document.querySelectorAll('.project-report')].map(section=>({title:section.querySelector('h3').textContent,svg:section.querySelector('svg')}));
  if(!charts.length)charts.push({title:'',svg:document.querySelector('svg')});
  canvas.height=Math.max(1100,chartY+charts.length*740);ctx.fillStyle=css.getPropertyValue('--page').trim();ctx.fillRect(0,0,1800,canvas.height);
  ctx.fillStyle=css.getPropertyValue('--ink').trim();lines.forEach((line,i)=>{ctx.font=line.font;ctx.fillText(line.text,60,62+i*42)});
  for(const [index,chart] of charts.entries()){
  const top=chartY+index*740;
  ctx.font=bodyFont;ctx.fillStyle=css.getPropertyValue('--ink').trim();ctx.fillText(chart.title,60,top,1680);
  const svg=chart.svg.cloneNode(true);svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('width','1680');svg.setAttribute('height','650');svg.setAttribute('font-family','Segoe UI, Malgun Gothic, sans-serif');
  const image=new Image(),url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));
  try{await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('image timeout')),15000);image.onload=()=>{clearTimeout(timer);resolve()};image.onerror=error=>{clearTimeout(timer);reject(error)};image.src=url});ctx.drawImage(image,60,top+20,1680,650)}finally{URL.revokeObjectURL(url)}
  }
  ctx.font='24px "Segoe UI", "Malgun Gothic", sans-serif';ctx.fillStyle=css.getPropertyValue('--created').trim();ctx.fillText('● '+t('created'),60,canvas.height-35);ctx.fillStyle=css.getPropertyValue('--resolved').trim();ctx.fillText('● '+t('resolved'),300,canvas.height-35);
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.94));if(!blob)throw new Error('encoding failed');
  const now=new Date(),stamp=now.getFullYear()+String(now.getMonth()+1).padStart(2,'0')+String(now.getDate()).padStart(2,'0')+'-'+String(now.getHours()).padStart(2,'0')+String(now.getMinutes()).padStart(2,'0')+String(now.getSeconds()).padStart(2,'0');
  const filename='jira_'+stamp+'_'+loadedFilters.year+'_'+activePeriod+'_'+locale+'_'+theme+'.jpg';
  const response=await fetch('/api/output',{method:'POST',headers:{'Content-Type':'image/jpeg','X-Session-Token':config.session,'X-Output-Name':filename},body:blob});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'JPG save failed.');setStatus(...previousStatus);
 }catch(error){console.error('JPG export failed:',error);status.className='error';setStatus('exportFailed')}
 finally{controls.forEach((control,i)=>control.disabled=disabled[i]);button.disabled=false;button.textContent=t('jpg')}
}
byId('download-jpg').addEventListener('click',exportJpg);
translateReport();
loadProjects();
