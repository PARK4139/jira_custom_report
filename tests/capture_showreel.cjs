// Captures the frames of the README showreel: run.cmd (terminal) -> dashboard -> query. Dummy data only.
//   node tests/capture_showreel.cjs            -> .local/showreel/frames/*.png + timeline.json
//   uv run --no-project --with pillow python tests/build_showreel.py   -> docs/showreel.gif (10 s)
// The terminal part is rendered from the real console strings of run.cmd (a Jira password prompt cannot be scripted);
// the browser part is the real dashboard served by the demo server.
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const work = path.join(root, '.local', 'showreel');
const frames = path.join(work, 'frames');
const demoInputs = path.join(root, '.local', 'demo-inputs.json');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const W = 1280, H = 720;

async function waitFor(action, label) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) { const result = await action(); if (result) return result; await delay(40); }
  throw Error('Timed out: ' + label);
}

const esc = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
function terminalHtml(lines, caption) {
  const body = lines.map(line => `<div class="${line.cls || ''}">${line.html ?? esc(line.text)}</div>`).join('');
  return `<!doctype html><meta charset="utf-8"><style>
  html,body{margin:0;width:${W}px;height:${H}px;background:radial-gradient(circle at 30% 20%,#2b4a78,#101a2d 70%);font-family:"Segoe UI","Malgun Gothic",sans-serif;overflow:hidden}
  .win{position:absolute;left:90px;top:70px;width:1100px;height:500px;background:#0c0f14;border-radius:12px;box-shadow:0 30px 80px rgba(0,0,0,.6);overflow:hidden}
  .bar{height:42px;background:#1b212c;display:flex;align-items:center;gap:9px;padding:0 16px;color:#9aa7ba;font-size:15px}
  .dot{width:13px;height:13px;border-radius:50%}.r{background:#ff5f56}.y{background:#ffbd2e}.g{background:#27c93f}
  .term{padding:22px 28px;font-family:"Cascadia Mono",Consolas,monospace;font-size:24px;line-height:1.55;color:#d6deeb;white-space:pre-wrap}
  .p{color:#7fdbca}.cmd{color:#fff}.dim{color:#8795a8}.url{color:#82aaff;font-weight:700}.ok{color:#addb67}
  .cur{display:inline-block;width:13px;height:26px;background:#d6deeb;vertical-align:-5px;margin-left:2px}
  .cap{position:absolute;left:90px;bottom:62px;background:#0b84ff;color:#fff;padding:14px 24px;border-radius:10px;font-size:27px;font-weight:700;box-shadow:0 8px 24px rgba(0,0,0,.4)}
  </style><div class="win"><div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>&nbsp; Command Prompt</div><div class="term">${body}</div></div>
  ${caption ? `<div class="cap">${esc(caption)}</div>` : ''}`;
}
const endCardHtml = `<!doctype html><meta charset="utf-8"><style>
  html,body{margin:0;width:${W}px;height:${H}px;background:radial-gradient(circle at 70% 30%,#2c5a96,#0d1830 75%);color:#fff;font-family:"Segoe UI","Malgun Gothic",sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;overflow:hidden}
  h1{margin:0;font-size:58px;letter-spacing:.02em}.sub{font-size:30px;color:#cfe0ff}
  code{font-family:"Cascadia Mono",Consolas,monospace;background:rgba(255,255,255,.12);padding:10px 22px;border-radius:10px;font-size:28px}
  .row{display:flex;gap:26px;align-items:center;font-size:26px;color:#cfe0ff}</style>
  <h1>ISSUE MEATER</h1><div class="sub">온프레미스 Jira · 생성 / 해결 누적 추이</div>
  <div class="row"><code>run.cmd --url {Jira-server-url} --id {Jira-user-id}</code></div>
  <div class="row"><span>Jira 없이 체험</span><code>demo.cmd</code></div>`;

async function main() {
  await fs.rm(work, {recursive: true, force: true});
  await fs.mkdir(frames, {recursive: true});
  await fs.rm(demoInputs, {force: true});
  const profile = await fs.mkdtemp(path.join(work, 'chrome-profile-'));
  const demo = spawn(path.join(root, '.venv', 'Scripts', 'python.exe'),
    ['-u', '-c', "import sys, jira_demo; sys.argv = ['jira-demo', '--no-open']; jira_demo.main()"], {cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']});
  let log = '', chrome, client;
  demo.stdout.on('data', chunk => log += chunk.toString());
  demo.stderr.on('data', chunk => process.stderr.write(chunk));
  const timeline = [];
  try {
    await waitFor(() => /http:\/\/127\.0\.0\.1:\d+\//.test(log), 'demo ready');
    const origin = log.match(/http:\/\/127\.0\.0\.1:\d+/)[0];
    chrome = spawn(process.env.CHROME_EXE || 'C:/Program Files/Google/Chrome/Application/chrome.exe', [
      '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', `--window-size=${W},${H}`, '--lang=ko-KR',
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
    const key = async (name, code, windowsVirtualKeyCode) => { for (const type of ['rawKeyDown', 'keyUp']) await send('Input.dispatchKeyEvent', {type, key: name, code, windowsVirtualKeyCode}); };
    const click = async selector => { const spot = await evaluate(`(()=>{const r=document.querySelector('${selector}').getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2]})()`); for (const kind of ['mousePressed', 'mouseReleased']) await send('Input.dispatchMouseEvent', {type: kind, x: spot[0], y: spot[1], button: 'left', clickCount: 1}); };
    const setSelect = (id, value) => evaluate(`(()=>{const node=document.getElementById('${id}');node.value='${value}';node.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    let count = 0;
    // One frame: screenshot now, shown for `ms` (hold = may be stretched so that the whole reel is 10 s).
    const snap = async (ms, hold = false) => {
      const shot = await send('Page.captureScreenshot', {format: 'png'});
      const file = String(++count).padStart(3, '0') + '.png';
      await fs.writeFile(path.join(frames, file), Buffer.from(shot.data, 'base64'));
      timeline.push({file, ms, hold});
    };
    const caption = (text, step) => evaluate(`(()=>{let c=document.getElementById('sr-caption');if(!c){c=document.createElement('div');c.id='sr-caption';c.style.cssText='position:fixed;left:28px;bottom:26px;z-index:99999;background:#0b84ff;color:#fff;padding:12px 22px;border-radius:10px;font:700 26px/1.3 "Segoe UI","Malgun Gothic",sans-serif;box-shadow:0 8px 24px rgba(0,0,0,.35);display:flex;gap:14px;align-items:center';document.body.append(c)}c.innerHTML='<span style="background:#fff;color:#0b84ff;border-radius:50%;width:34px;height:34px;display:inline-flex;align-items:center;justify-content:center">${step}</span><span>${text}</span>'})()`);
    const page = async html => { await send('Page.navigate', {url: 'data:text/html;charset=utf-8,' + encodeURIComponent(html)}); await delay(120); };
    await send('Page.enable'); await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: 1, mobile: false});

    // Warm-up (not recorded): Korean, light theme.
    await send('Page.navigate', {url: origin});
    await waitFor(() => evaluate("typeof hasResults!=='undefined' && hasResults===true"), 'warm-up');
    await evaluate("localStorage.setItem('jira-locale','ko');localStorage.setItem('jira-theme','light');localStorage.setItem('jira-period','monthly');localStorage.setItem('jira-projects','[\"ATLAS\"]')");

    // 1. run.cmd in a terminal: the command is typed, the password prompt appears, then the dashboard address.
    const command = 'run.cmd --url https://jira.example.com --id hong01';
    const prompt = {html: '<span class="p">C:\\Jira_custom_report&gt;</span> '};
    for (const upto of [0, 7, 15, 26, 35, 44, command.length]) {
      await page(terminalHtml([{html: prompt.html + `<span class="cmd">${esc(command.slice(0, upto))}</span><span class="cur"></span>`}], '① run.cmd 실행'));
      await snap(upto === command.length ? 380 : 150);
    }
    const typed = {html: prompt.html + `<span class="cmd">${esc(command)}</span>`};
    for (const [cursor, ms] of [[true, 330], [false, 250], [true, 330]]) {
      await page(terminalHtml([typed, {html: `<span class="dim">Jira password (hidden, not saved by default): </span>${cursor ? '<span class="cur"></span>' : ''}`}], '② 비밀번호만 입력'));
      await snap(ms);
    }
    const out = [typed, {html: '<span class="dim">Jira password (hidden, not saved by default): </span>'}];
    await page(terminalHtml([...out, {html: '<span class="url">Dashboard: http://127.0.0.1:52817/</span>'}], '③ 브라우저가 열립니다'));
    await snap(330);
    await page(terminalHtml([...out, {html: '<span class="url">Dashboard: http://127.0.0.1:52817/</span>'},
      {html: '<span class="ok">Select the year in your browser. Keep this terminal open; press Ctrl+C to stop.</span>'}], '③ 브라우저가 열립니다'));
    await snap(520, true);

    // 2. The dashboard opens and queries by itself: record from the first moment so the charts draw in on screen.
    await send('Page.navigate', {url: origin});
    const started = Date.now();
    let last = started, captioned = false;
    while (Date.now() - started < 900) {
      if (!captioned && Date.now() - started > 300) { try { await caption('조회가 자동으로 시작됩니다', 4); captioned = true; } catch {} }
      try { await snap(Math.min(200, Math.max(70, Date.now() - last))); } catch { await delay(30); } // no page to shoot for a few ms while it navigates
      last = Date.now();
    }
    await waitFor(() => evaluate("hasResults===true"), 'dashboard');
    await snap(250, true);

    // 3. Autocomplete: type, Tab -> a second project is queried; scroll down to its chart while it draws in.
    await click('#projects');
    await send('Input.insertText', {text: 'lum'});
    await waitFor(() => evaluate("document.querySelectorAll('#projects')[0].parentElement.querySelectorAll('.combo-list li').length>0"), 'candidates');
    await caption('입력 → Tab 으로 프로젝트·보고자 자동완성', 5);
    await delay(250);
    await snap(900, true);
    await key('Tab', 'Tab', 9);
    last = Date.now();
    await waitFor(() => evaluate("document.querySelectorAll('#project-graphs .project-report').length===2"), 'second chart');
    await snap(Math.min(220, Math.max(90, Date.now() - last)));
    const target = await evaluate("Math.round(document.querySelectorAll('#project-graphs .project-report')[1].getBoundingClientRect().top+window.scrollY-70)");
    for (let step = 1; step <= 6; step++) {
      await evaluate(`window.scrollTo(0,${Math.round(target * step / 6)})`);
      await delay(40);
      await snap(110);
    }
    await snap(350, true);

    // 4. Period switch: quarterly, with all periods one click away.
    await caption('일간 · 주간 · 월간 · 분기간 · 연간 전환', 6);
    await setSelect('period-select', 'quarterly');
    last = Date.now();
    for (let i = 0; i < 4; i++) { await snap(Math.min(200, Math.max(90, Date.now() - last))); last = Date.now(); }
    await snap(400, true);

    // 5. Hover tooltip on the new chart: cumulative created / resolved / resolved-to-created ratio.
    await caption('누적 생성 · 해결 · 해결율을 한눈에', 7);
    const chart = await evaluate("(()=>{const r=document.querySelectorAll('#project-graphs .project-report svg')[1].getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()");
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: chart.x + chart.width * 0.4, y: chart.y + chart.height * 0.5});
    await delay(450);
    await snap(450);
    await send('Input.dispatchMouseEvent', {type: 'mouseMoved', x: chart.x + chart.width * 0.72, y: chart.y + chart.height * 0.5});
    await delay(450);
    await snap(900, true);

    // 6. End card.
    await page(endCardHtml);
    await snap(1100, true);

    await fs.writeFile(path.join(work, 'timeline.json'), JSON.stringify(timeline, null, 1));
    console.log(`captured ${timeline.length} frames, ${timeline.reduce((sum, item) => sum + item.ms, 0)} ms before scaling`);
    try { await send('Browser.close'); } catch {}
  } finally { client?.close(); chrome?.kill(); demo.kill(); await fs.rm(demoInputs, {force: true}); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
