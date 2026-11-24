import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const origin=process.env.MEAL_CHECK_URL||'http://127.0.0.1:8011',user='meal-qa-sessions-mwkgi4xm';
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-simple');const prior=JSON.parse(await fs.readFile(path.join(out,'report.json'),'utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(({user,sid})=>{localStorage.setItem('meal-active-session:'+user,sid);localStorage.setItem('meal-demo-step:'+user,'compare');},{user,sid:prior.session});
const report={...prior,priorAttemptFailure:prior.failure,errors,layouts:[]};delete report.failure;
const get=async()=>(await page.request.get(origin+'/api/meal/state?user='+user)).json();
try{
 await page.goto(origin+'/?view=meal&user=qa-sessions-mwkgi4xm');await page.getByRole('button',{name:'开始跨会话对比',exact:true}).waitFor();
 const before=new Set((await get()).runs.map(r=>r.id));await page.getByRole('button',{name:'开始跨会话对比',exact:true}).click();let run;
 for(let i=0;i<600;i++){await new Promise(r=>setTimeout(r,1200));run=(await get()).runs.find(r=>r.action==='meal_compare'&&!before.has(r.id));if(run?.status==='failed')throw Error(run.error);if(run?.status==='complete')break;}
 if(!run||run.status!=='complete'||!run.result.comparison.every(r=>r.status==='complete'&&r.verification.passed))throw Error(JSON.stringify(run?.result.comparison));
 report.runs.push({action:'meal_compare',id:run.id});report.comparison=run.result.comparison.map(r=>({mode:r.mode,elapsed_ms:r.elapsed_ms,tokens:r.total_tokens,learning:r.learning_model_calls,reused:r.persistent_memory_reused}));
 await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));
 await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});await page.screenshot({path:path.join(out,'03-compare.png'),fullPage:true});
 await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByRole('tab',{name:'数据库与口径',exact:true}).click();await page.getByRole('heading',{name:'计算公式与数据口径'}).waitFor();
 await page.getByRole('button',{name:'返回简明演示',exact:true}).click();await page.locator('.meal-demo-steps').waitFor();
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-innerWidth)<2);const l=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.layouts.push(l);if(l.width!==l.scrollWidth)throw Error('overflow');}
 await page.setViewportSize({width:2526,height:1400});const cdp=await page.context().newCDPSession(page);await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1.5});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-visualViewport.width)<2);
 if(!await page.evaluate(()=>Array.from(document.querySelectorAll('.meal-compare-card')).every(e=>e.getBoundingClientRect().right<=visualViewport.width+1)))throw Error('pinch clip');
 if(errors.length)throw Error(errors.join('\n'));report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
