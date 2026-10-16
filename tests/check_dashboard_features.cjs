// Isolated Chromium session against serve_dashboard_fixture.py.
// node tests/check_dashboard_features.cjs URL [path-to-playwright-package]
const {chromium} = require(process.argv[3] || 'playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

async function main() {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const context = await browser.newContext({locale:'ko-KR', colorScheme:'dark'});
    const page = await context.newPage();
    const errors = [], requests = [];
    page.on('pageerror', error=>errors.push(error.message));
    page.on('request', request=>{if(request.url().endsWith('/api/report'))requests.push(request)});
    const output = path.resolve('.local/ui-verification/fixture-outputs');
    await fs.mkdir(output, {recursive:true});
    await page.goto(process.argv[2] || 'http://127.0.0.1:8766');
    assert.equal(await page.locator('html').getAttribute('lang'), 'ko');
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'light');
    await page.locator('#report-panel').waitFor();
    assert.equal(await page.locator('#query-button').count(), 0);
    const selectedYear = await page.locator('#year').inputValue();
    assert.equal(requests.length, 1);
    assert.equal(await page.locator('#period-tabs').isVisible(), false);
    for (const [period,count] of Object.entries({'1week':53,monthly:12,yearly:1})) {
      await page.locator('#period-select').selectOption(period);
      assert.equal(await page.locator('#period-rows tr').count(), count);
    }
    await page.locator('#period-select').selectOption('monthly');
    assert.match(await page.locator('#summary').innerText(), /90/);
    await page.locator('#theme').click();
    await page.screenshot({path:path.join(output,'ko-dark.png'),fullPage:true});
    for (const [locale,theme] of [['ko','dark'],['en','light']]) {
      await page.locator('#locale').selectOption(locale);
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.locator('#theme').click();
      assert.equal(await page.locator('html').getAttribute('lang'),locale);
      assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
      await page.locator('#download-jpg').click();
      await page.waitForFunction(()=>document.querySelector('#query-status').textContent.includes('outputs/'));
      const savedPath = await page.locator('#query-status').innerText();
      const filename = path.join(output,path.basename(savedPath));
      const jpeg = await fs.readFile(filename);
      assert.match(path.basename(filename),new RegExp(`^jira_\\d{8}-\\d{6}_${selectedYear}_monthly_${locale}_${theme}\\.jpg$`));
      assert.equal(jpeg.subarray(0,3).toString('hex'),'ffd8ff');
      const dimensions = await page.evaluate(async data=>{
        const bitmap=await createImageBitmap(new Blob([Uint8Array.from(atob(data),c=>c.charCodeAt(0))],{type:'image/jpeg'}));
        return [bitmap.width,bitmap.height];
      },jpeg.toString('base64'));
      assert.equal(dimensions[0],1800);assert.ok(dimensions[1]>=1100);
      assert.equal(await page.locator('#download-jpg').isEnabled(),true);
    }
    assert.equal(requests.length,1,'period, locale, theme and JPG must reuse results');
    await page.locator('#download-csv').click();
    await page.waitForFunction(()=>document.querySelector('#query-status').textContent.includes('outputs/'));
    assert.ok((await fs.readdir(output)).some(name=>name.endsWith('_issues.csv')));
    assert.match(await page.locator('#project-graphs p').first().innerText(),/Created:/);
    assert.equal(await page.locator('.project-report').first().evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(243, 246, 250)');
    assert.equal(await page.locator('body').evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(255, 255, 255)');
    await page.screenshot({path:path.join(output,'en-light.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.screenshot({path:path.join(output,'mobile-light.png'),fullPage:true});
    await page.reload();
    assert.equal(await page.locator('#locale').inputValue(),'en');
    assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
    await page.locator('#report-panel').waitFor();
    await page.locator('#year').selectOption('2025');
    await page.waitForFunction(()=>document.querySelector('#report-title').textContent.includes('2025'));
    assert.equal(JSON.parse(requests.at(-1).postData()).year,2025);
    await page.locator('#reporters').fill('fail');await page.locator('#reporters').press('Tab');
    assert.equal(await page.locator('#report-panel').isVisible(),false);
    await page.waitForFunction(()=>document.querySelector('#query-status').classList.contains('error'));
    assert.equal(await page.locator('#report-panel').isVisible(),false);
    assert.equal(await page.locator('#period-controls').isVisible(),false);
    assert.equal(await page.locator('#reporters').isEnabled(),true);
    assert.deepEqual(errors,[]);
    await context.close();
    console.log('PASS: ko/en, four periods, default-light theme toggle, JPG/CSV output storage, persistence, mobile, year refresh, failure recovery.');
  } finally {await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
