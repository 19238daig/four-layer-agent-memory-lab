import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const out='../artifacts/meal-criteria',report=JSON.parse(await fs.readFile(out+'/production-report.json','utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1050}});
 const state=await (await page.request.get('http://127.0.0.1:8010/api/meal/state?user='+report.user)).json();
 const session=state.runs.find(r=>r.id===report.sessionTest.id).session;
 await page.goto('http://127.0.0.1:8010/?view=meal&user='+report.workspace);
 await page.evaluate(({user,session})=>{localStorage.setItem('meal-active-session:'+user,session);localStorage.setItem('meal-demo-step:'+user,'compare');},{user:report.user,session});
 await page.reload();await page.getByText(/条件传参拦截 1 次/).waitFor({timeout:15000});
 await page.screenshot({path:out+'/04-restored-comparison.png',fullPage:true});
 console.log(JSON.stringify({restored:true,correctionNotice:await page.getByText(/条件传参拦截 1 次/).innerText(),bundle:await page.locator('script[src]').getAttribute('src')}));
}finally{await browser.close();}
