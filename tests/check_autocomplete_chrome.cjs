// Real Chrome check of project/reporter autocomplete with genuine key events, against the synthetic fixture (no Jira).
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.local', 'ui-verification');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

async function waitFor(action, label) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) { const result = await action(); if (result) return result; await delay(50); }
  throw Error('Timed out: ' + label);
}

async function main() {
  await fs.mkdir(output, {recursive: true});
  const profile = await fs.mkdtemp(path.join(output, 'chrome-profile-'));
  const fixture = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'),
    ['-c', "import runpy; runpy.run_path('tests/serve_dashboard_fixture.py', run_name='__main__')"], {cwd: root, windowsHide: true});
  let origin = '', chrome, client;
  fixture.stdout.on('data', chunk => origin += chunk.toString());
  fixture.stderr.on('data', chunk => process.stderr.write(chunk));
  try {
    await waitFor(() => origin.includes('\n'), 'fixture ready'); origin = origin.trim();
    chrome = spawn(process.env.CHROME_EXE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--window-size=1400,900',
      '--disable-background-networking', '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'
    ], {windowsHide: true, stdio: 'ignore'});
    const port = await waitFor(async () => { try { return (await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return null; } }, 'Chrome ready');
    const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    client = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { client.onopen = resolve; client.onerror = reject; });
    let sequence = 0; const pending = new Map(), exceptions = [], reporterQueries = [], reportBodies = [];
    client.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.id) { const task = pending.get(message.id); pending.delete(message.id); if (message.error) task.reject(Error(JSON.stringify(message.error))); else task.resolve(message.result); }
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
      if (message.method === 'Network.requestWillBeSent' && message.params.request.postData) {
        if (message.params.request.url.endsWith('/api/reporters')) reporterQueries.push(JSON.parse(message.params.request.postData).query);
        if (message.params.request.url.endsWith('/api/report')) reportBodies.push(JSON.parse(message.params.request.postData));
      }
    };
    const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++sequence; const timer = setTimeout(() => { pending.delete(id); reject(Error('CDP timeout: ' + method)); }, 20000); pending.set(id, {resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); }}); client.send(JSON.stringify({id, method, params})); });
    const evaluate = async expression => { const value = await send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true}); if (value.exceptionDetails) throw Error(JSON.stringify(value.exceptionDetails)); return value.result.value; };
    const key = async (name, code, windowsVirtualKeyCode) => { for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', {type, key: name, code, windowsVirtualKeyCode}); };
    const type = text => send('Input.insertText', {text});
    const clickField = async id => { const box = await evaluate(`(()=>{const r=document.getElementById('${id}').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`); for (const kind of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type: kind, x: box[0], y: box[1], button: 'left', clickCount: 1}); };
    const listTexts = id => evaluate(`[...document.getElementById('${id}').parentElement.querySelectorAll('.combo-list li')].map(li=>li.textContent)`);
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Page.navigate', {url: origin});
    await waitFor(() => evaluate("typeof hasResults!=='undefined' && document.getElementById('projects').disabled===false && !document.getElementById('report-panel').hidden"), 'initial report');
    const chips = id => evaluate(`[...document.getElementById('${id}').parentElement.querySelectorAll('.chip-label')].map(node=>node.textContent)`);
    const placeholder = id => evaluate(`document.getElementById('${id}').placeholder`);
    const removeChip = async (id, index) => { const spot = await evaluate(`(()=>{const r=document.getElementById('${id}').parentElement.querySelectorAll('.chip-remove')[${index}].getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`); for (const kind of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type: kind, x: spot[0], y: spot[1], button: 'left', clickCount: 1}); };
    const hint = async id => (await listTexts(id)).join();

    // Selected values are chips; the input stays empty and the placeholder only shows when there are no chips.
    assert.deepEqual(await chips('projects'), ['Demo team (DEMO)']);
    await waitFor(async () => (await chips('reporters')).join() === 'Sample User (sample)', 'reporter chip shows name and ID once Jira resolves it');
    assert.equal(await evaluate("document.getElementById('projects').value"), '');
    assert.equal(await placeholder('projects'), '', 'placeholder is hidden while chips exist');
    await removeChip('reporters', 0);
    assert.deepEqual(await chips('reporters'), []);
    assert.equal(await placeholder('reporters'), 'ctrl space + tab', 'placeholder is exactly "ctrl space + tab"');
    assert.equal(await placeholder('projects'), '', 'projects still has a chip');

    // Reporters: click lists Jira candidates; typing Korean searches Jira; Tab turns it into a chip with name and ID.
    await clickField('reporters');
    await waitFor(async () => (await listTexts('reporters')).length === 4, 'reporter candidates on click');
    assert.deepEqual((await listTexts('reporters')).sort(), ['Fail User (fail)', 'Sample User (sample)', '김선희 (kimsh)', '박정훈 (parkjh)'].sort());
    await type('정훈');
    await waitFor(async () => (await hint('reporters')) === '박정훈 (parkjh)', 'filtered Korean candidate');
    assert.ok(reporterQueries.includes('정훈'), 'typed text was sent to Jira as the search query');
    await key('Tab', 'Tab', 9);
    assert.deepEqual(await chips('reporters'), ['박정훈 (parkjh)'], 'the chip shows the name and the employee ID');
    assert.equal(await evaluate("document.getElementById('reporters').value"), '');
    assert.equal(await evaluate("document.activeElement.id"), 'reporters', 'Tab completes without leaving the field');
    assert.equal(await evaluate("document.getElementById('reporters').parentElement.querySelector('.combo-list').hidden"), true);
    await waitFor(() => reportBodies.at(-1)?.reporters?.join() === 'parkjh', 'report for the completed reporter');

    // Second reporter: skim-style subsequence match ("ks" -> kimsh); Backspace on an empty input removes the last chip.
    await type('ks');
    await waitFor(async () => (await hint('reporters')) === '김선희 (kimsh)', 'subsequence candidate');
    await key('Tab', 'Tab', 9);
    assert.deepEqual(await chips('reporters'), ['박정훈 (parkjh)', '김선희 (kimsh)']);
    await waitFor(() => reportBodies.at(-1)?.reporters?.join() === 'parkjh,kimsh', 'report for both reporters');
    await key('Backspace', 'Backspace', 8);
    assert.deepEqual(await chips('reporters'), ['박정훈 (parkjh)'], 'Backspace removes the last chip');
    await waitFor(() => reportBodies.at(-1)?.reporters?.join() === 'parkjh', 'report after removing a reporter');

    // Free text becomes a chip too: a typed name that identifies one Jira user becomes that user, an unknown ID is kept as typed.
    await type('김선희'); await key('Enter', 'Enter', 13);
    assert.deepEqual(await chips('reporters'), ['박정훈 (parkjh)', '김선희 (kimsh)'], 'a typed name resolves to the Jira user');
    await type('e1234,');
    assert.deepEqual(await chips('reporters'), ['박정훈 (parkjh)', '김선희 (kimsh)', 'e1234'], 'a comma commits an unknown ID as a chip');
    await removeChip('reporters', 2);

    // Projects: replace the chip; click lists the Jira catalog; typing narrows; arrows + Enter also select.
    await removeChip('projects', 0);
    assert.deepEqual(await chips('projects'), []);
    assert.equal(await placeholder('projects'), 'ctrl space + tab');
    await clickField('projects');
    await waitFor(async () => (await listTexts('projects')).length === 3, 'project candidates on click');
    await type('hot');
    await waitFor(async () => (await hint('projects')) === 'Hotel group (HTG)', 'filtered project');
    const shot = await send('Page.captureScreenshot', {format: 'png'});
    await fs.writeFile(path.join(output, 'autocomplete-open.png'), Buffer.from(shot.data, 'base64'));
    await key('Tab', 'Tab', 9);
    assert.deepEqual(await chips('projects'), ['Hotel group (HTG)']);
    await type('p');
    await waitFor(async () => (await hint('projects')) === 'Platform team (OTHER)', 'second project candidate');
    await key('ArrowDown', 'ArrowDown', 40); await key('Enter', 'Enter', 13);
    assert.deepEqual(await chips('projects'), ['Hotel group (HTG)', 'Platform team (OTHER)']);
    await waitFor(() => reportBodies.at(-1)?.projects?.join() === 'HTG,OTHER', 'report for both projects');
    const filled = await send('Page.captureScreenshot', {format: 'png'});
    await fs.writeFile(path.join(output, 'autocomplete-chips.png'), Buffer.from(filled.data, 'base64'));

    // Ctrl+Space shows the candidates again after Escape and does not type a space.
    await clickField('projects');
    await waitFor(async () => (await listTexts('projects')).length === 1, 'candidates after click');
    await key('Escape', 'Escape', 27);
    assert.equal(await evaluate("document.getElementById('projects').parentElement.querySelector('.combo-list').hidden"), true);
    await send('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: ' ', code: 'Space', windowsVirtualKeyCode: 32, modifiers: 2});
    await send('Input.dispatchKeyEvent', {type: 'keyUp', key: ' ', code: 'Space', windowsVirtualKeyCode: 32, modifiers: 2});
    await waitFor(async () => (await listTexts('projects')).length === 1, 'Ctrl+Space reopens candidates');
    assert.equal(await evaluate("document.getElementById('projects').value"), '', 'Ctrl+Space does not type a space');

    // A project that is not in Jira's catalog is reported instead of becoming a chip; Escape closes the hint.
    await type('NOPE'); await key('Enter', 'Enter', 13);
    assert.deepEqual(await chips('projects'), ['Hotel group (HTG)', 'Platform team (OTHER)'], 'unknown text is not a chip');
    assert.equal(await evaluate("document.getElementById('projects').value"), 'NOPE');
    await waitFor(() => evaluate("document.getElementById('query-status').textContent.includes('NOPE')"), 'unknown project message');
    await clickField('projects');
    await waitFor(async () => ['No matching Jira candidates', '일치하는 Jira 후보가 없습니다'].includes(await hint('projects')), 'no-match hint');
    await key('Escape', 'Escape', 27);
    assert.equal(await evaluate("document.getElementById('projects').parentElement.querySelector('.combo-list').hidden"), true);

    assert.deepEqual(exceptions, []);
    console.log('PASS: actual Chrome, click lists Jira candidates, typing queries Jira, skim-style matching, chips with name and ID for every selected project and reporter, Tab/Enter completion, Backspace/x removal, and Ctrl+Space.');
    try { await send('Browser.close'); } catch {}
  } finally { client?.close(); chrome?.kill(); fixture.kill(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
