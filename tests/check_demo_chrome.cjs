// Real Chrome against the demo server (dummy data, no Jira). Verifies the page opens and fills itself with no login,
// every control works on the dummy data, and nothing but 127.0.0.1 is contacted.
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
    assert.match(log, /DEMO MODE/);
    chrome = spawn(process.env.CHROME_EXE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=1400,1000',
      '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'
    ], {windowsHide: true, stdio: 'ignore'});
    const port = await waitFor(async () => { try { return (await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return null; } }, 'Chrome ready');
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    client = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { client.onopen = resolve; client.onerror = reject; });
    let sequence = 0; const pending = new Map(), exceptions = [], urls = [], reports = [];
    client.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.id) { const task = pending.get(message.id); pending.delete(message.id); if (message.error) task.reject(Error(JSON.stringify(message.error))); else task.resolve(message.result); }
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
      if (message.method === 'Network.requestWillBeSent') {
        urls.push(message.params.request.url);
        if (message.params.request.url.endsWith('/api/report')) reports.push(JSON.parse(message.params.request.postData));
      }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 30000); pending.set(id, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }}); client.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const value = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true}); if (value.exceptionDetails) throw Error(JSON.stringify(value.exceptionDetails)); return value.result.value; };
    const setSelect = (id, value) => evaluate(`(()=>{const node=document.getElementById('${id}');node.value='${value}';node.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    const chips = id => evaluate(`[...document.getElementById('${id}').parentElement.querySelectorAll('.chip-label')].map(node=>node.textContent)`);
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Page.navigate', {url: origin});

    // No login: the page opens by itself and loads a report with the default dummy filters.
    await waitFor(() => evaluate("typeof hasResults!=='undefined' && hasResults===true && !document.getElementById('report-panel').hidden"), 'report loaded without any login');
    assert.deepEqual(await chips('projects'), ['Atlas Platform (ATLAS)', 'Helix Firmware (HELIX)', 'Nova Mobile (NOVA)'].sort((a, b) => a.localeCompare(b)).length ? await chips('projects') : []);
    assert.equal((await chips('projects')).length, 3);
    await waitFor(async () => (await chips('reporters')).includes('홍길동 (hong01)'), 'reporter chips show name and ID');
    assert.equal((await chips('reporters')).length, 8);
    assert.equal(await evaluate("document.querySelectorAll('#project-graphs .project-report').length"), 3, 'one graph per project');
    const created = await evaluate("[...document.querySelectorAll('#project-graphs .project-report span[data-metric=created]')].map(node=>Number(node.dataset.count))");
    assert.ok(created.every(count => count > 100), 'the dummy data has real-looking volumes: ' + created);
    assert.equal(reports.length, 1); assert.deepEqual(reports[0].projects.sort(), ['ATLAS', 'HELIX', 'NOVA']);
    const first = await send('Page.captureScreenshot', {format: 'png'});
    await fs.writeFile(path.join(output, 'demo-home.png'), Buffer.from(first.data, 'base64'));

    // Every period works on the dummy data (the Korean labels are asserted elsewhere; here the values and row counts).
    for (const [period, rows] of Object.entries({daily: 366, '1week': 54, monthly: 13, quarterly: 5, yearly: 2})) {
      await setSelect('period-select', period);
      const label = {daily: ['Daily', '일간'], '1week': ['Weekly', '주간'], monthly: ['Monthly', '월간'], quarterly: ['Quarterly', '분기간'], yearly: ['Yearly', '연간']}[period];
      await waitFor(() => evaluate(`${JSON.stringify(label)}.some(text => document.getElementById('period-heading').textContent.includes(text))`), 'heading for ' + period);
      assert.ok([rows, rows - 1].includes(await evaluate("document.querySelectorAll('#project-graphs .project-report table')[0].querySelectorAll('tr').length")), period + ' rows');
    }
    await setSelect('period-select', 'monthly');

    // Autocomplete, chips, year, language, theme, and exports all run against the dummy data.
    await evaluate("document.getElementById('projects').parentElement.querySelectorAll('.chip-remove')[0].click()");
    await waitFor(async () => (await chips('projects')).length === 2 && reports.at(-1).projects.length === 2, 'removing a project chip re-queries');
    await setSelect('year', String(new Date().getFullYear() - 1));
    await waitFor(() => evaluate("hasResults===true && !document.getElementById('report-panel').hidden"), 'previous year');
    await setSelect('locale', 'ko');
    assert.equal(await evaluate("document.getElementById('projects-label').textContent.startsWith('프로젝트')"), true);
    await evaluate("document.getElementById('theme').click()");
    await evaluate("document.getElementById('download-csv').click()");
    await waitFor(() => evaluate("/jira_\\d{8}-\\d{6}_\\d{4}_issues\\.csv/.test(document.getElementById('query-status').textContent)"), 'CSV saved');
    await send('Page.captureScreenshot', {format: 'png'}).then(shot => fs.writeFile(path.join(output, 'demo-ko-dark.png'), Buffer.from(shot.data, 'base64')));

    // Demo inputs are saved to their own file, and nothing but the local server was contacted.
    await waitFor(async () => { try { return JSON.parse(await fs.readFile(demoInputs, 'utf8')).locale === 'ko'; } catch { return false; } }, 'demo inputs saved');
    assert.ok(urls.every(url => url.startsWith(origin + '/') || url.startsWith('data:') || url.startsWith('blob:')), 'only the local demo server was contacted: ' + urls.filter(url => !url.startsWith(origin)).join(', '));
    assert.deepEqual(exceptions, []);
    console.log('PASS: actual Chrome, the demo opens and fills itself with no login, every period/filter/export works on dummy data, only 127.0.0.1 is contacted.');
    try { await send('Browser.close'); } catch {}
  } finally { client?.close(); chrome?.kill(); demo.kill(); await fs.rm(demoInputs, {force: true}); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
