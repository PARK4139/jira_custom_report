// Regenerates the QUICK START screenshots in docs/quick-start/ from the demo server (dummy data, no Jira).
// node tests/capture_quick_start.cjs
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.local', 'ui-verification');
const images = path.join(root, 'docs', 'quick-start');
const demoInputs = path.join(root, '.local', 'demo-inputs.json');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitFor(action, label) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) { const result = await action(); if (result) return result; await delay(50); }
  throw Error('Timed out: ' + label);
}

async function main() {
  await fs.mkdir(output, {recursive: true});
  await fs.mkdir(images, {recursive: true});
  await fs.rm(demoInputs, {force: true});
  const profile = await fs.mkdtemp(path.join(output, 'chrome-profile-'));
  const demo = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'),
    ['-u', '-c', "import sys, jira_demo; sys.argv = ['jira-demo', '--no-open']; jira_demo.main()"], {cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
  let log = '', chrome, client;
  demo.stdout.on('data', chunk => log += chunk.toString());
  demo.stderr.on('data', chunk => process.stderr.write(chunk));
  const outputsBefore = new Set(await fs.readdir(path.join(root, 'outputs')).catch(() => []));
  try {
    await waitFor(() => /http:\/\/127\.0\.0\.1:\d+\//.test(log), 'demo ready');
    const origin = log.match(/http:\/\/127\.0\.0\.1:\d+/)[0];
    chrome = spawn(process.env.CHROME_EXE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=1400,900', '--lang=ko-KR',
      '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'
    ], {windowsHide: true, stdio: 'ignore'});
    const port = await waitFor(async () => { try { return (await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return null; } }, 'Chrome ready');
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    client = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { client.onopen = resolve; client.onerror = reject; });
    let sequence = 0; const pending = new Map();
    client.onmessage = event => { const message = JSON.parse(event.data); if (message.id) { const task = pending.get(message.id); pending.delete(message.id); if (message.error) task.reject(Error(JSON.stringify(message.error))); else task.resolve(message.result); } };
    const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 30000); pending.set(id, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }}); client.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const value = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true}); if (value.exceptionDetails) throw Error(JSON.stringify(value.exceptionDetails)); return value.result.value; };
    const key = async (name, code, windowsVirtualKeyCode, modifiers = 0) => { for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', {type, key: name, code, windowsVirtualKeyCode, modifiers}); };
    const click = async selector => { const spot = await evaluate(`(()=>{const r=document.querySelector('${selector}').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`); for (const kind of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type: kind, x: spot[0], y: spot[1], button: 'left', clickCount: 1}); };
    const setSelect = (id, value) => evaluate(`(()=>{const node=document.getElementById('${id}');node.value='${value}';node.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    const rect = selector => evaluate(`(()=>{const r=document.querySelector('${selector}').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
    const shoot = async (name, clip) => {
      const params = {format: 'png', ...(clip ? {clip: {x: Math.max(0, Math.floor(clip.x)), y: Math.max(0, Math.floor(clip.y)), width: Math.ceil(clip.width), height: Math.ceil(clip.height), scale: 1}} : {})};
      const shot = await send('Page.captureScreenshot', params);
      await fs.writeFile(path.join(images, name), Buffer.from(shot.data, 'base64'));
      console.log('saved', name);
    };
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Emulation.setDeviceMetricsOverride', {width: 1400, height: 900, deviceScaleFactor: 1, mobile: false});
    await send('Page.navigate', {url: origin});
    await waitFor(() => evaluate("typeof hasResults!=='undefined' && hasResults===true && !document.getElementById('report-panel').hidden"), 'report loaded');
    await setSelect('locale', 'ko');
    await waitFor(() => evaluate("document.getElementById('projects-label').textContent.startsWith('프로젝트')"), 'Korean UI');
    await waitFor(() => evaluate("[...document.querySelectorAll('#reporters-label ~ * .chip-label, .chip-label')].some(node=>node.textContent.includes('홍길동'))"), 'reporter names');
    await delay(1200); // let the chart draw-in animation finish

    // 1. Whole dashboard right after it opens.
    await shoot('01-dashboard.png');
    // 2. Top bar: language, theme, auto login.
    await shoot('02-topbar.png', {x: 0, y: 0, width: 1400, height: 52});
    // 3. Filters: year, project and reporter chips, period.
    await shoot('03-filters.png', await rect('.controls'));
    // 4. Project autocomplete: click, then type to narrow (Ctrl+Space lists the candidates again).
    await evaluate("document.querySelector('#projects-label').scrollIntoView()");
    for (const chip of [1, 0]) { await evaluate(`document.querySelectorAll('#projects')[0].parentElement.querySelectorAll('.chip-remove')[${chip}]&&document.querySelectorAll('#projects')[0].parentElement.querySelectorAll('.chip-remove')[${chip}].click()`); }
    await delay(400);
    await click('#projects');
    await delay(500);
    await send('Input.insertText', {text: 'l'});
    await waitFor(() => evaluate("document.querySelectorAll('#projects')[0].parentElement.querySelectorAll('.combo-list li').length>0"), 'project candidates');
    await delay(300);
    const controls = await rect('.controls');
    await shoot('04-project-autocomplete.png', {x: controls.x, y: controls.y, width: controls.width, height: 430});
    await key('Escape', 'Escape', 27);
    await evaluate("document.getElementById('projects').value=''");
    await evaluate("document.getElementById('projects').blur()");
    // 5. Reporter search by name (Jira is asked while typing). Start from an empty field so the placeholder and candidates show.
    await evaluate("reportersField.set([])");
    await click('#reporters');
    await send('Input.insertText', {text: '김'});
    await waitFor(() => evaluate("document.querySelectorAll('#reporters')[0].parentElement.querySelectorAll('.combo-list li').length>0"), 'reporter candidates');
    await delay(300);
    const reporterBox = await rect('#reporters-label');
    await shoot('05-reporter-autocomplete.png', {x: controls.x, y: reporterBox.y - 10, width: controls.width, height: 230});
    await key('Escape', 'Escape', 27);
    await evaluate("document.getElementById('reporters').value='';document.getElementById('reporters').blur()");
    await evaluate("reportersField.set([['hong01','홍길동'],['kim02','김민수'],['lee03','이서연'],['park04','박지훈'],['choi05','최유진'],['jung06','정하늘'],['kang07','강도윤'],['yoon08','윤서아']].map(([value,name])=>({value,label:name+' ('+value+')'})));reportersChanged()");
    // restore the three default projects for the remaining pictures
    await evaluate("projectsField.set([{value:'ATLAS',label:'Atlas Platform (ATLAS)'},{value:'HELIX',label:'Helix Firmware (HELIX)'},{value:'NOVA',label:'Nova Mobile (NOVA)'}]);projectsChanged()");
    await waitFor(() => evaluate("hasResults===true && !document.getElementById('report-panel').hidden"), 'report again');
    await delay(1200);
    // 6. Another period: quarterly.
    await setSelect('period-select', 'quarterly');
    await delay(1200);
    await shoot('06-quarterly.png');
    await setSelect('period-select', 'monthly');
    await delay(1200);
    // 7. Hover tooltip on the chart.
    const chart = await rect('#project-graphs .project-report svg');
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: chart.x + chart.width * 0.55, y: chart.y + chart.height * 0.5});
    await delay(500);
    const panel = await rect('#project-graphs .project-report');
    await shoot('07-tooltip.png', {x: panel.x, y: panel.y, width: panel.width, height: panel.height});
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 5, y: 5});
    // 8. CSV export and its message.
    await evaluate("window.scrollTo(0,0)");
    await click('#download-csv');
    await waitFor(() => evaluate("/outputs\\//.test(document.getElementById('query-status').textContent)"), 'CSV saved');
    const afterExport = await rect('.controls');
    await shoot('08-export.png', {x: 0, y: 52, width: 1400, height: Math.ceil(afterExport.y + afterExport.height + 12 - 52)});
    // 9. Dark theme.
    await click('#theme');
    await delay(1200);
    await shoot('09-dark.png');
    console.log('done');
    try { await send('Browser.close'); } catch {}
  } finally {
    client?.close(); chrome?.kill(); demo.kill();
    await fs.rm(demoInputs, {force: true});
    for (const name of await fs.readdir(path.join(root, 'outputs')).catch(() => [])) if (!outputsBefore.has(name)) await fs.rm(path.join(root, 'outputs', name), {force: true});
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
