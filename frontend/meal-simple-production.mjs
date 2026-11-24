import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>{localStorage.setItem('meal-active-session:meal-qa-sessions-mwkgi4xm','session-03c53632bb');localStorage.setItem('meal-demo-step:meal-qa-sessions-mwkgi4xm','test');});
try{
 await page.goto('http://127.0.0.1:8010/?view=meal&user=qa-sessions-mwkgi4xm');await page.getByText('选定记忆已生效',{exact:true}).waitFor();
 if(await page.getByLabel('选餐SQL编辑器').count())throw Error('SQL leaked into simple view');
 await page.getByRole('button',{name:'查看本次实际注入',exact:true}).click();await page.getByRole('dialog',{name:'选餐来源详情'}).waitFor();await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'下一步：对比 Deep Agents',exact:true}).click();await page.locator('[data-mode=deepagents] [data-metric=tokens]').filter({hasText:'15,856'}).waitFor();
 await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});await page.screenshot({path:new URL('../artifacts/meal-simple/production.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
 console.log(JSON.stringify({errors,heading:await page.locator('h1').innerText(),groups:await page.locator('.meal-compare-card').count(),sourceTrace:true,complete:true}));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await browser.close();}
