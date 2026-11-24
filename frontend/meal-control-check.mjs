import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const base='http://127.0.0.1:8010',workspace='qa-start-mwsvyi76',user='meal-'+workspace;
const out=new URL('../artifacts/meal-control/'+Date.now()+'/',import.meta.url);await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
const report={errors:[],operations:[],sessions:[],runs:[],layouts:[]};
page.on('pageerror',e=>report.errors.push(e.message));
page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/meal/operations'))report.operations.push(r.postDataJSON());});
page.on('response',async r=>{if(r.request().method()==='POST'&&r.url().endsWith('/api/meal/sessions')&&r.ok())report.sessions.push(await r.json());});
const state=async(session='')=>(await page.request.get(base+'/api/meal/state?user='+user+(session?'&session='+session:''))).json();
const assert=(v,message)=>{if(!v)throw Error(message);};
const shot=async name=>page.screenshot({path:decodeURIComponent(new URL(name+'.png',out).pathname).replace(/^\/(\w:)/,'$1'),fullPage:true});
async function waitRun(before){for(let i=0;i<180;i++){await new Promise(r=>setTimeout(r,1000));const run=(await state()).runs.find(r=>r.action==='test_session'&&!before.has(r.id));if(run&&run.status!=='running'){assert(run.status==='complete',run.error);report.runs.push({id:run.id,session:run.session,params:run.result.params,memory:run.result.memory_test});return run;}}throw Error('run timeout');}
async function test(name){const before=new Set((await state()).runs.map(r=>r.id));await page.getByRole('button',{name,exact:true}).click();return waitRun(before);}
function checkControl(run){const r=run.result;assert(!r.memory_test.memory_loaded&&r.memory_test.memory_id===null,'no personal memory');assert(r.params.budget===120&&r.params.min_spice===0&&r.params.max_spice===0&&r.params.kcal_min===600&&r.params.kcal_max===700,'control defaults independent from dinner');assert(r.memory_test.current_session_history_count===0,'old chat not carried over');assert(r.approved.every(r=>r.hot_lv===0&&r.price<=120&&r.kcal_lo>=600&&r.kcal_hi<=700),'control recommendations match defaults');}
try{
 const original=await state();const saved=original.memory_snapshots.find(m=>m.title==='启动验收晚饭偏好');assert(saved,'saved dinner fixture exists');
 const prior=original.runs.find(r=>r.action==='test_session'&&r.status==='complete'&&r.result.memory_test.memory_id===saved.id);
 await page.goto(base+'/?view=meal&user='+workspace);
 await page.evaluate(({user,session})=>{localStorage.setItem('meal-demo-step:'+user,'test');localStorage.setItem('meal-active-session:'+user,session);},{user,session:prior.session});await page.reload();
 await page.getByText('条件读取与推荐均已核验',{exact:true}).waitFor();
 await page.getByLabel('简明测试问题').fill('晚上吃什么好？');
 await page.getByLabel('简明新会话记忆').selectOption('');
 await page.getByText(/已选择“不加载记忆”，尚未应用/).waitFor();assert(await page.locator('.meal-demo-result').count()===0,'old 500/spicy result hidden immediately');await shot('01-pending');
 const opCount=report.operations.length;
 await page.route('**/api/meal/sessions',route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'验收模拟：新建失败，请重试'})}),{times:1});
 await page.getByRole('button',{name:'新开无记忆会话并测试',exact:true}).click();await page.getByText(/验收模拟：新建失败/).waitFor();
 assert(report.operations.length===opCount,'failed create cannot run against previous loaded session');assert(await page.getByLabel('简明新会话记忆').inputValue()==='','failed selection preserved');
 await page.route('**/api/meal/sessions',async route=>{await new Promise(r=>setTimeout(r,800));await route.continue();});
 const control=await test('新开无记忆会话并测试');checkControl(control);
 await page.getByText('未加载记忆的对照',{exact:true}).waitFor();assert((await page.locator('.meal-demo-condition-pills').innerText()).includes('演示默认'),'default labels visible');assert(!(await page.locator('.meal-demo-proof').innerText()).includes('仅使用本会话选定的记忆'),'control not labeled as memory');
 const ctx=await (await page.request.get(base+'/api/meal/artifacts/'+control.result.memory_test.context_id+'?user='+user)).json();const injected=JSON.parse(ctx.content);assert(!injected.memory_loaded&&injected.condition_sources.length===0&&injected.current_session_history.length===0,'actual L4 excludes saved personal sources');await shot('02-control');
 await page.reload();await page.getByText('未加载记忆的对照',{exact:true}).waitFor();assert(await page.getByLabel('简明新会话记忆').inputValue()==='','refresh stays no-memory');
 await page.getByLabel('简明新会话记忆').selectOption(saved.id);assert(await page.locator('.meal-demo-result').count()===0,'control result hidden before loading memory');
 const loaded=await test('加载所选记忆并测试');assert(loaded.result.memory_test.memory_id===saved.id&&loaded.result.params.budget===500&&loaded.result.params.min_spice===1,'switch back loads selected memory');assert(loaded.result.memory_test.current_session_history_count===0,'switch back creates fresh session');
 await page.getByText('条件读取与推荐均已核验',{exact:true}).waitFor();
 await page.getByLabel('简明新会话记忆').selectOption('');const beforeSessions=report.sessions.length;
 await page.getByRole('button',{name:'新开无记忆会话',exact:true}).click();await page.locator('.meal-demo-current').filter({hasText:'本会话未加载个人记忆；不带入已保存的饮食条件。'}).waitFor();
 assert(report.sessions.length===beforeSessions+1&&report.sessions.at(-1).memory_id===null,'manual no-memory session remains unbound');assert(await page.locator('.meal-demo-result').count()===0,'manual new session does not show old result');
 const manual=await test('测试无记忆对照');checkControl(manual);await page.getByText('未加载记忆的对照',{exact:true}).waitFor();
 assert(new Set(report.runs.map(r=>r.session)).size===3,'three independent test sessions');assert(report.operations.every((op,i)=>op.session===report.runs[i].session),'all operations use newly created session IDs');
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-innerWidth)<2);const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert(layout.width===layout.scroll,'no horizontal overflow');report.layouts.push(layout);}
 assert(!report.errors.length,'no JS errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(new URL('report.json',out),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
