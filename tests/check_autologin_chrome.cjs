// Real Chrome against the demo server: the Auto login button sits right of the theme button, asks before saving, and mirrors the server.
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.local', 'ui-verification');
const demoInputs = path.join(root, '.local', 'demo-inputs.json');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitFor(action, label) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) { const result = await action(); if (result) return result; await delay(50); }
  throw Error('Timed out: ' + label);
}

async function main() {
  await fs.mkdir(output, {recursive: true});
  await fs.rm(demoInputs, {force: true});
  const profile = await fs.mkdtemp(path.join(output, 'chrome-profile-'));
  const demo = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'),
    ['-u', '-c', "import sys, jira_demo; sys.argv = ['jira-demo', '--no-open']; jira_demo.main()"], {cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
  let log = '', chrome, client;
  demo.stdout.on('data', chunk => log += chunk.toString());
  demo.stderr.on('data', chunk => process.stderr.write(chunk));
  try {
    await waitFor(() => /http:\/\/127\.0\.0\.1:\d+\//.test(log), 'demo ready');
    const origin = log.match(/http:\/\/127\.0\.0\.1:\d+/)[0];
    chrome = spawn(process.env.CHROME_EXE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=1400,700',
      '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'
    ], {windowsHide: true, stdio: 'ignore'});
    const port = await waitFor(async () => { try { return (await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return null; } }, 'Chrome ready');
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    client = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { client.onopen = resolve; client.onerror = reject; });
    let sequence = 0; const pending = new Map(), exceptions = [], posts = [], dialogs = [];
    client.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.id) { const task = pending.get(message.id); pending.delete(message.id); if (message.error) task.reject(Error(JSON.stringify(message.error))); else task.resolve(message.result); }
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
      if (message.method === 'Network.requestWillBeSent' && message.params.request.url.endsWith('/api/autologin')) posts.push(JSON.parse(message.params.request.postData));
      if (message.method === 'Page.javascriptDialogOpening') dialogs.push(message.params.message);
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 30000); pending.set(id, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }}); client.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const value = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true}); if (value.exceptionDetails) throw Error(JSON.stringify(value.exceptionDetails)); return value.result.value; };
    const clickButton = async () => { const spot = await evaluate("(()=>{const r=document.getElementById('autologin').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()"); for (const kind of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type: kind, x: spot[0], y: spot[1], button: 'left', clickCount: 1}); };
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Page.navigate', {url: origin});
    await waitFor(() => evaluate("document.getElementById('autologin')!==null && typeof hasResults!=='undefined'"), 'page ready');

    // Placement: in the top bar, to the right of the theme (화면 모드) control.
    const boxes = await evaluate("(()=>{const box=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,right:r.right,y:r.y,height:r.height,width:r.width}};return {theme:box('theme'),auto:box('autologin'),field:box('autologin-field')}})()");
    assert.ok(boxes.auto.width > 0 && boxes.auto.height > 0, 'the button is visible');
    assert.ok(boxes.field.x >= boxes.theme.right, 'the Auto login control is to the right of the theme button');
    assert.ok(Math.abs(boxes.auto.y - boxes.theme.y) < 8, 'both are on the same row of the top bar');
    assert.equal(await evaluate("getComputedStyle(document.getElementById('autologin-field')).display"), 'flex');
    assert.equal(await evaluate("document.querySelector('#autologin-field span').textContent"), await evaluate("messages[locale].autoLogin"));

    // Off at first. Declining the confirmation saves nothing; accepting turns it on.
    assert.equal(await evaluate("document.getElementById('autologin').getAttribute('aria-pressed')"), 'false');
    await evaluate("window.__answers=[false,true];window.confirm=message=>{window.__asked=(window.__asked||[]).concat(message);return window.__answers.shift()}");
    await clickButton(); await delay(300);
    assert.equal(posts.length, 0, 'declining the confirmation sends nothing');
    assert.equal(await evaluate("document.getElementById('autologin').getAttribute('aria-pressed')"), 'false');
    assert.match(await evaluate("window.__asked[0]"), /Windows/, 'the confirmation explains where the login is stored');
    await clickButton();
    await waitFor(() => evaluate("document.getElementById('autologin').getAttribute('aria-pressed')==='true'"), 'turned on');
    assert.deepEqual(posts, [{enabled: true}]);
    assert.equal(await evaluate("document.getElementById('autologin').textContent"), await evaluate("t('autoOn')"));
    const shot = await send('Page.captureScreenshot', {format: 'png', clip: {x: 0, y: 0, width: 1400, height: 90, scale: 1}});
    await fs.writeFile(path.join(output, 'autologin-topbar.png'), Buffer.from(shot.data, 'base64'));

    // The server keeps the state: a reload shows On, and turning it off needs no confirmation.
    await send('Page.reload');
    await waitFor(() => evaluate("document.getElementById('autologin')!==null && document.getElementById('autologin').getAttribute('aria-pressed')==='true'"), 'still on after reload');
    await evaluate("window.confirm=()=>{window.__unexpected=true;return true}");
    await clickButton();
    await waitFor(() => evaluate("document.getElementById('autologin').getAttribute('aria-pressed')==='false'"), 'turned off');
    assert.deepEqual(posts, [{enabled: true}, {enabled: false}]);
    assert.equal(await evaluate("window.__unexpected===undefined"), true, 'turning it off does not ask');

    // Korean.
    await evaluate("(()=>{const node=document.getElementById('locale');node.value='ko';node.dispatchEvent(new Event('change',{bubbles:true}))})()");
    assert.equal(await evaluate("document.querySelector('#autologin-field span').textContent"), '자동 로그인');
    assert.equal(await evaluate("document.getElementById('autologin').textContent"), '꺼짐');
    assert.deepEqual(dialogs, []);
    assert.deepEqual(exceptions, []);
    console.log('PASS: actual Chrome, the Auto login button is right of the theme button, asks before saving, and mirrors the server state across reloads.');
    try { await send('Browser.close'); } catch {}
  } finally { client?.close(); chrome?.kill(); demo.kill(); await fs.rm(demoInputs, {force: true}); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
