import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto('http://127.0.0.1:8010/?view=meal&user=qa-sessions-mwkgi4xm');await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选择选餐会话').waitFor();
 await page.waitForFunction(()=>document.querySelector('[aria-label="选择选餐会话"]')?.value.startsWith('session-'));
 await page.getByLabel('选择选餐会话').selectOption('session-92048043b9');await page.getByLabel('选餐SQL编辑器').waitFor();
 await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();
 await page.locator('[data-mode=deepagents] [data-metric=tokens]').filter({hasText:'37,725'}).waitFor();
 await page.getByLabel('选择选餐会话').selectOption('session-dcf74d671a');
 await page.locator('[data-mode=deepagents] .meal-reuse-proof').filter({hasText:'未重新学习'}).waitFor();
 await page.locator('[data-mode=deepagents] [data-metric=tokens]').filter({hasText:'24,410'}).waitFor();
 await page.locator('[data-mode=deepagents]').getByRole('button',{name:'新会话实际加载的记忆'}).click();
 await page.getByRole('dialog',{name:'选餐来源详情'}).waitFor();await page.keyboard.press('Escape');
 await page.evaluate(()=>{document.activeElement?.blur();window.scrollTo(0,0);});
 await page.screenshot({path:new URL('../artifacts/meal-sessions/production-comparison.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
 const report={errors,origin:'http://127.0.0.1:8010',savedSessionsRestored:true,sourceTrace:true,firstTokens:37725,reusedTokens:24410,complete:true};
 await fs.writeFile(new URL('../artifacts/meal-sessions/production-report.json',import.meta.url),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await browser.close();}
