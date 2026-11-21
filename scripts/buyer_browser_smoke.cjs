// Run against a disposable, synthetic workspace. Creates and edits a purchase case.
const {pathToFileURL} = require("node:url");
const assert = require("node:assert/strict");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");

(async () => {
  const data = process.env.RISK_SMOKE_DATA;
  const url = new URL(process.env.RISK_SMOKE_URL);
  assert(data && url.hostname === "127.0.0.1", "Specify a disposable local workspace");
  const browser = await chromium.launch({headless: true, executablePath:process.env.CHROMIUM_PATH});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    if (process.env.RISK_SMOKE_LAUNCH) {
      await page.goto(pathToFileURL(process.env.RISK_SMOKE_LAUNCH).href);
      await page.waitForURL(url.origin + "/");
    }
    await page.goto(url.href);
    await page.locator("#buyer-signals [data-group=finance] h5").first().waitFor();
    assert.equal(await page.locator('input[type="password"]').count(), 0);
    assert.equal(await page.locator(".signal-group").count(), 4);
    await page.locator("#location-tools>summary").click();
    await page.getByText("Enter a known address point", {exact:true}).click();
    const manual = page.locator("#manual-address");
    for (const [name, value] of Object.entries({label:"11/14 Currie Crescent", suburb:"Kingston", latitude:"-35.315392", longitude:"149.139011"}))
      await manual.locator(`[name=${name}]`).fill(value);
    await manual.getByRole("checkbox").check();
    await manual.getByRole("button").click();
    await page.getByText("The financial scenarios use the inputs saved for this case.", {exact:false}).waitFor();
    assert.match(await page.locator("[data-group=spatial]").innerText(), /RZ5/);
    const editor = page.locator("#buyer-finance-editor");
    await editor.locator("summary").click();
    assert.equal(await editor.locator("[name=principal]").inputValue(), "");
    for (const [name, value] of Object.entries({principal:"300000",annual_rate_decimal:"0.06",term_months:"360"}))
      await editor.locator(`[name=${name}]`).fill(value);
    await editor.getByRole("button").click();
    await page.getByText("Saved buyer inputs and assessed case version 2.").waitFor();
    assert.match(await page.locator("[data-group=finance]").innerText(), /1,798\.65/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    assert.deepEqual(errors, []);
    console.log("PASS · new address, four groups, blank buyer inputs, revised repayment, mobile layout, no browser errors");
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
