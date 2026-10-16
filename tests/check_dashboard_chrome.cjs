// Dependency-free Chrome fallback: Playwright installation is blocked by network
// policy in this environment. Uses only an isolated, synthetic local dashboard.
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.local', 'ui-verification');
const delay = ms=>new Promise(resolve=>setTimeout(resolve, ms));

async function waitFor(action, label) {
  const deadline=Date.now()+20000;
  while(Date.now()<deadline){const result=await action();if(result)return result;await delay(50)}
  throw Error('Timed out: '+label);
}
async function main(){
  await fs.mkdir(output,{recursive:true});
  const profile=await fs.mkdtemp(path.join(output,'chrome-profile-'));
  const fixture=spawn(path.join(root,'.venv','Scripts','python.exe'),['-c',"import runpy; runpy.run_path('tests/serve_dashboard_fixture.py', run_name='__main__')"],{cwd:root,windowsHide:true});
  let origin='',chrome,client;
  fixture.stdout.on('data',chunk=>origin+=chunk.toString());
  fixture.stderr.on('data',chunk=>process.stderr.write(chunk));
  try{
    await waitFor(()=>origin.includes('\n'),'fixture ready');origin=origin.trim();
    assert.match(origin,/^http:\/\/127\.0\.0\.1:\d+$/);
    chrome=spawn(process.env.CHROME_EXE||'C:/Program Files/Google/Chrome/Application/chrome.exe',[
      '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
      '--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'
    ],{windowsHide:true,stdio:'ignore'});
    chrome.on('error',error=>console.error(error.message));
    const port=await waitFor(async()=>{try{return (await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]}catch{return null}},'Chrome ready');
    const targets=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
    client=new WebSocket(targets.find(target=>target.type==='page').webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{client.onopen=resolve;client.onerror=reject});
    let sequence=0;const pending=new Map(),savedOutputs=[],exceptions=[];
    client.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const task=pending.get(message.id);pending.delete(message.id);if(message.error)task.reject(Error(JSON.stringify(message.error)));else task.resolve(message.result)}
      if(message.method==='Runtime.exceptionThrown')exceptions.push(message.params.exceptionDetails.text);
    };
    const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method))},20000);pending.set(id,{resolve:value=>{clearTimeout(timer);resolve(value)},reject:error=>{clearTimeout(timer);reject(error)}});client.send(JSON.stringify({id,method,params}))});
    const evaluate=async expression=>{const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(value.exceptionDetails)throw Error(JSON.stringify(value.exceptionDetails));return value.result.value};
    await send('Page.enable');await send('Runtime.enable');
    await send('Page.navigate',{url:origin});
    await waitFor(()=>evaluate("typeof hasResults!=='undefined' && document.querySelector('#projects').disabled===false && document.querySelector('#projects').value.includes('DEMO')"),'project list');
    const result=await evaluate(`(async()=>{
      const check=(value,message)=>{if(!value)throw Error(message)};
      const until=async predicate=>{const end=Date.now()+15000;while(!predicate()){if(Date.now()>end)throw Error('UI wait timeout');await new Promise(resolve=>setTimeout(resolve,30))}};
      const change=(id,value)=>{byId(id).value=value;byId(id).dispatchEvent(new Event('change',{bubbles:true}))};
      let requests=0;const originalFetch=fetch;window.fetch=async(url,options)=>{if(url==='/api/report')requests++;const response=await originalFetch(url,options);if(url==='/api/output'){const saved=await response.clone().json();savedOutputs.push(saved.saved)}return response};
      const setTheme=mode=>{if(document.documentElement.dataset.theme!==mode)byId('theme').click()};
      check(document.documentElement.dataset.theme==='light','white theme is the default');
      change('locale','ko');setTheme('dark');change('year','2026');
      await until(()=>hasResults);
      check(byId('report-title').textContent.includes('비율'),'Korean title');
      for(const [period,count]of Object.entries({'1week':53,'2week':27,monthly:12,yearly:1})){
        change('period-select',period);check(byId('project-graphs').querySelectorAll('table tr').length===count+1,'period rows '+period);
      }
      change('period-select','monthly');
      for(const [language,mode]of [['ko','dark'],['en','light']]){
        change('locale',language);setTheme(mode);
        check(document.documentElement.lang===language,'document locale');
        check(document.documentElement.dataset.theme===mode,'document theme');
        await exportJpg();check(statusKey!=='exportFailed','JPG export failed');
      }
      check(requests===1,'preferences or export triggered a Jira query');
      check(getComputedStyle(document.body).backgroundColor==='rgb(255, 255, 255)','light page');
      check(byId('project-graphs').querySelector('p').textContent.includes('Created'),'English project summary');
      const before=savedOutputs.length;byId('download-csv').click();await until(()=>savedOutputs.length>before);
      return {requests,language:document.documentElement.lang,theme:document.documentElement.dataset.theme,status:byId('query-status').textContent,savedOutputs};
    })()`);
    assert.equal(result.savedOutputs.length,3,'two JPGs and a CSV should be stored under outputs');
    for(const relative of result.savedOutputs.filter(filename=>filename.endsWith('.jpg'))){
      const file=path.join(output,'fixture-outputs',path.basename(relative));
      const data=await waitFor(async()=>{try{return await fs.readFile(file)}catch{return null}},'JPG saved');
      assert.equal(data.subarray(0,3).toString('hex'),'ffd8ff');
      const dimensions=await evaluate(`(async()=>{const bytes=Uint8Array.from(atob(${JSON.stringify(data.toString('base64'))}),c=>c.charCodeAt(0));const image=await createImageBitmap(new Blob([bytes],{type:'image/jpeg'}));return [image.width,image.height]})()`);
      assert.equal(dimensions[0],1800);assert.ok(dimensions[1]>=1100);
    }
    const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    await fs.writeFile(path.join(output,'en-light.png'),Buffer.from(screenshot.data,'base64'));
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});
    assert.equal(await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true,'mobile overflow');
    const mobile=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    await fs.writeFile(path.join(output,'mobile-light.png'),Buffer.from(mobile.data,'base64'));
    await send('Page.reload');
    await waitFor(()=>evaluate("document.querySelector('#locale')?.value==='en' && document.documentElement.dataset.theme==='light'"),'saved preferences');
    assert.deepEqual(exceptions,[]);
    await fs.writeFile(path.join(output,'result.json'),JSON.stringify({result,exceptions},null,2));
    console.log('PASS: actual Chrome, ko/en, four periods, theme toggle, JPG/CSV in outputs, mobile, persistence.');
    try{await send('Browser.close')}catch{}
  }finally{client?.close();chrome?.kill();fixture.kill()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
