// Workflow regression with a controlled canvas/image decoder; no JPEG fidelity claim.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const script=fs.readFileSync(process.argv[2],'utf8');
async function scenario(failure){
 const saves=[],draws=[],revoked=[],elements=new Map();let canvas,mime;
 const node=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:'',addEventListener(){}});return elements.get(id)};
 const svg=()=>({setAttribute(){},cloneNode(){return svg()}});
 const sections=['Alpha (A)','Beta (B)'].map(title=>({querySelector:selector=>selector==='h3'?{textContent:title}:svg()}));
 const document={documentElement:{},fonts:{ready:Promise.resolve()},body:{append(){}},querySelectorAll(){return sections},querySelector(){throw Error('Must not export the hidden combined chart')},createElement(tag){
  if(tag==='a')return {click(){downloads.push(this.download)},remove(){}};
  if(tag==='canvas')return canvas={width:0,height:0,getContext(){return {measureText:text=>({width:text.length*12}),fillRect(){},fillText(){},drawImage(...args){draws.push(args)}}},toBlob(callback,type){mime=type;callback(failure==='encoding'?null:new Blob(['synthetic-image']))}};
 }};
 const form={elements:[node('year'),node('projects')]};form.elements[1].disabled=true;
 const context=vm.createContext({document,form,byId:node,config:{session:'synthetic'},hasResults:true,loadedFilters:{year:2026,projects:['Alpha (A)','Beta (B)'],reporters:['sample']},queryRunning:false,activePeriod:'monthly',locale:'ko',theme:'light',datasets:{monthly:[{created:3,resolved:2}]},messages:{ko:{periods:{monthly:'월간'}}},t:key=>key,status:{},setStatus(key){context.statusKey=key},async fetch(url,options){saves.push({url,options});return {ok:true,status:201,json:async()=>({saved:'outputs/jira-synthetic.jpg'})}},getComputedStyle(){return {getPropertyValue(){return '#ffffff'}}},Blob,URL:{createObjectURL(){return 'blob:synthetic'},revokeObjectURL(url){revoked.push(url)}},XMLSerializer:class{serializeToString(){return '<svg/>'}},Image:class{set src(value){queueMicrotask(()=>failure==='decode'?this.onerror(Error('decode failed')):this.onload())}},setTimeout(callback,ms){const timer=setTimeout(callback,ms===15000?15000:0);timer.unref();return timer},clearTimeout,translateReport(){},loadProjects(){},loadReporters(){}});
 await vm.runInContext('async function unused(){}\n'+script+'\nexportJpg()',context);
 assert.equal(node('download-jpg').disabled,false);
 assert.equal(form.elements[0].disabled,false);
 assert.equal(form.elements[1].disabled,true,'restore originally disabled controls');
 assert.ok(revoked.length>=1,'release SVG URL even when decoding fails');
 if(failure){assert.equal(context.statusKey,'exportFailed');assert.equal(saves.length,0)}
 else{assert.equal(draws.length,2,'include every visible project chart');assert.ok(canvas.height>1500);assert.equal(mime,'image/jpeg');assert.equal(saves.length,1);assert.equal(saves[0].url,'/api/output');assert.equal(saves[0].options.headers['Content-Type'],'image/jpeg');assert.match(saves[0].options.headers['X-Output-Name'],/^jira_\d{8}-\d{6}_2026_monthly_ko_light\.jpg$/);assert.equal(saves[0].options.headers['X-Session-Token'],'synthetic')}
}
(async()=>{await scenario();await scenario('decode');await scenario('encoding');console.log('PASS: multi-project JPG composition, filename, decoding/encoding errors, and control restoration.')})().catch(error=>{console.error(error);process.exitCode=1});
