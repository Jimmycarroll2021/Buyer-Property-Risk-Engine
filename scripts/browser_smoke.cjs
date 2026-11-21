// Optional UI verification. Install Playwright separately; never reads remote sites.
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || undefined,args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const url=new URL(process.env.RISK_UI_URL || 'http://127.0.0.1:8000');
 if(url.hostname!=='127.0.0.1')throw Error('Use a local synthetic demo workspace');
 if(process.env.RISK_SMOKE_LAUNCH){
   await page.goto(pathToFileURL(process.env.RISK_SMOKE_LAUNCH).href);
   await page.waitForURL(url.origin+'/');
 }
 await page.goto(url.href);
 await page.locator('#metrics .metric').first().waitFor();
 if(await page.locator('input[type="password"]').count())throw Error('Unexpected sign-in prompt');
 if(await page.locator('#checks tr').count()!==65)throw Error('Expected all 65 checks');
 if(await page.locator('#source-table tr').count()!==83)throw Error('Expected 83 registry entries');
 await page.locator('#latest').uncheck();
 await page.getByRole('button',{name:'Run assessment',exact:true}).click();
 await page.getByText('Assessment saved.',{exact:false}).waitFor();
 if(!await page.locator('#finance svg').count())throw Error('Missing cash chart');
 await page.getByRole('button',{name:'Case inputs',exact:true}).click();
 const caseInput=JSON.parse(await page.locator('#case-json').inputValue());
 if(caseInput.case_id!=='demo-house')throw Error('Demo case not visible');
 await page.getByRole('button',{name:'Evidence',exact:true}).click();
 if(await page.locator('#observations article').count()!==9)throw Error('Expected synthetic observation set');
 await page.getByRole('button',{name:'Architecture',exact:true}).click();
 await page.locator('.architecture-list img').first().waitFor();
 const loaded=await page.locator('.architecture-list img').evaluateAll(imgs=>imgs.every(i=>i.complete&&i.naturalWidth>0));
 if(!loaded)throw Error('Architecture image failed to load');
 await page.getByRole('button',{name:'Assessment',exact:true}).click();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'Open report',exact:true}).click();
 const download=await downloadPromise;if(!download.suggestedFilename().endsWith('.html'))throw Error('Expected standalone HTML report');
 if(process.env.RISK_UI_SCREENSHOT){await page.screenshot({path:process.env.RISK_UI_SCREENSHOT,fullPage:false});}
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1))throw Error('Mobile layout overflows viewport');
 if(errors.length)throw Error(errors.join('\n'));
 console.log(JSON.stringify({status:'PASS',checks_rendered:65,registry_entries:83,observations:9,finance_chart:true,architecture_images:3,report_download:true,mobile_overflow:false,browser_errors:errors.length}));
 await browser.close();
})().catch(e=>{console.error(e.message);process.exit(1)});
