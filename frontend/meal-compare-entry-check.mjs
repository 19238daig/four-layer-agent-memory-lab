import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const base='http://127.0.0.1:8010',workspace='qa-start-mwsvyi76',user='meal-'+workspace;
const out=new URL('../artifacts/meal-compare-entry/'+Date.now()+'/',import.meta.url);await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const report={errors:[],operations:[],layouts:[]};
page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/meal/operations'))report.operations.push(r.postDataJSON());});
const state=async(session='')=>(await page.request.get(base+'/api/meal/state?user='+user+(session?'&session='+session:''))).json();
const assert=(v,message)=>{if(!v)throw Error(message);};
const shot=async name=>page.screenshot({path:decodeURIComponent(new URL(name+'.png',out).pathname).replace(/^\/(\w:)/,'$1'),fullPage:true});
try{
 const original=await state();const control=original.session_list.find(s=>!s.memory_id);const saved=original.memory_snapshots.find(m=>m.title==='启动验收晚饭偏好');assert(control&&saved,'control and saved memory exist');
 await page.goto(base+'/?view=meal&user='+workspace);
 await page.evaluate(({user,session})=>{localStorage.setItem('meal-demo-step:'+user,'compare');localStorage.setItem('meal-active-session:'+user,session);},{user,session:control.id});await page.reload();
 const button=page.getByRole('button',{name:'开始跨会话对比',exact:true});await button.waitFor();assert(await button.isDisabled(),'empty selection blocked with explanation');
 await page.getByText('请先选择一份已保存的记忆；无记忆会话无法进行个人记忆对比。',{exact:true}).waitFor();await shot('01-control-entry');
 await page.getByLabel('简明对比记忆').selectOption(saved.id);await page.getByLabel('简明对比问题').fill('晚上吃什么好？');assert(await button.isEnabled(),'selecting saved memory enables comparison without going back');
 await page.route('**/api/meal/sessions',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'验收模拟：新建失败'})}),{times:1});
 await button.click();await page.getByText(/验收模拟：新建失败/).waitFor();assert(report.operations.length===0,'cannot run comparison in old control after creation failure');assert(await page.getByLabel('简明对比记忆').inputValue()===saved.id,'selection survives failure');
 await page.route('**/api/meal/sessions',async route=>{await new Promise(r=>setTimeout(r,800));await route.continue();});
 const before=new Set((await state()).runs.map(r=>r.id));await button.click();assert(await button.isDisabled(),'duplicate start blocked');
 let run;for(let i=0;i<240;i++){await new Promise(r=>setTimeout(r,1000));run=(await state()).runs.find(r=>r.action==='meal_compare'&&!before.has(r.id));if(run&&run.status!=='running')break;}
 assert(run?.status==='complete',run?.error||'comparison timeout');
 assert(report.operations.length===1&&report.operations[0].session===run.session&&run.session!==control.id,'actual comparison uses new loaded session');
 const selected=await state(run.session);assert(selected.current_session.memory_id===saved.id,'new session bound selected snapshot');
 const untouched=await state(control.id);assert(untouched.current_session.memory_id===null,'original control session remains memory-free');
 assert(run.result.comparison.length===2&&run.result.comparison.every(r=>r.status==='complete'&&r.verification.passed&&r.params.budget===500&&r.params.min_spice===1),'both actual frameworks match saved dinner');
 report.run=run.id;report.comparison=run.result.comparison.map(r=>({mode:r.mode,passed:r.verification.passed,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms}));
 await page.waitForFunction(()=>document.querySelectorAll('.meal-memory-verdict').length===2);await shot('02-completed');
 await page.getByLabel('简明对比记忆').selectOption('');assert(await page.locator('.meal-memory-verdict').count()===0,'old comparison hidden when target changes');assert(await button.isDisabled(),'empty selection cannot start');
 await page.getByLabel('简明对比记忆').selectOption(saved.id);await page.reload();await page.waitForFunction(()=>document.querySelectorAll('.meal-memory-verdict').length===2);assert(await page.getByLabel('简明对比记忆').inputValue()===saved.id,'loaded memory and saved comparison restore after refresh');
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-innerWidth)<2);const l=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(l.width===l.scroll,'no overflow');report.layouts.push(l);}
 const blank='qa-empty-compare-'+Date.now().toString(36);await page.goto(base+'/?view=meal&user='+blank);await page.getByRole('button',{name:'3 Deep Agents 对比'}).click();await page.getByRole('button',{name:'去保存一份记忆',exact:true}).click();await page.getByLabel('简明偏好输入').waitFor();report.emptySpaceRecovery=true;
 assert(!report.errors.length,'no browser errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(new URL('report.json',out),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
