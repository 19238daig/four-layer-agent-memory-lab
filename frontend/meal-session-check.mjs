import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const origin=process.env.MEAL_CHECK_URL||'http://127.0.0.1:8011';
const workspace=process.env.MEAL_SESSION_USER||'qa-sessions-'+Date.now().toString(36);const user='meal-'+workspace;
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-sessions');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={workspace,user,errors,runs:[],liveSamples:[],layouts:[]};
const assert=(v,m)=>{if(!v)throw Error(m);};
async function state(session=''){return (await page.request.get(origin+'/api/meal/state?user='+user+(session?'&session='+session:''))).json();}
async function run(action,button){const before=new Set((await state()).runs.map(r=>r.id));await button.click();for(let i=0;i<1100;i++){await new Promise(r=>setTimeout(r,1000));const data=await state();const r=data.runs.find(r=>!before.has(r.id)&&r.action===action);if(action==='meal_compare'&&r?.status==='running'){const sample=await page.locator('.meal-compare-card').evaluateAll(cards=>cards.map(c=>({mode:c.dataset.mode,time:c.querySelector('[data-metric=elapsed]')?.textContent,tokens:c.querySelector('[data-metric=tokens]')?.textContent,phase:c.querySelector('.meal-live-stats p')?.textContent})));report.liveSamples.push(sample);}if(r?.status==='failed')throw Error(action+': '+r.error);if(r?.status==='complete'){report.runs.push({id:r.id,action,session:r.session});await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));return r;}}throw Error('Timeout '+action);}
async function create(memoryId){const before=(await state()).session_list.map(s=>s.id);await page.getByLabel('新会话记忆选择').selectOption(memoryId);await page.getByRole('button',{name:'新建会话',exact:true}).click();await page.waitForFunction(ids=>{const el=document.querySelector('[aria-label="选择选餐会话"]');return el&&el.value.startsWith('session-')&&!ids.includes(el.value);},before);const sid=await page.getByLabel('选择选餐会话').inputValue();return state(sid);}
try{
 await page.goto(origin+'/?view=meal&user='+workspace);await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选择选餐会话').waitFor();await page.waitForFunction(()=>document.querySelector('[aria-label="选择选餐会话"]')?.value);
 const first=await state();report.firstSession=first.current_session.id;
 if(!process.argv.includes('--resume')){
  await page.getByLabel('选餐偏好输入').fill('我不吃辣，午饭预算73块，热量470到610千卡。');
  await run('remember',page.getByRole('button',{name:'保存偏好并整理记忆',exact:true}));
  await page.getByLabel('保存记忆名称').fill('清淡午饭 · 73元');await page.getByRole('button',{name:'保存当前记忆版本',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.meal-loaded-memory strong')?.textContent?.includes('清淡午饭 · 73元'));
  let s=await state(first.current_session.id);const chosen=s.selected_memory.id;report.chosenMemory=chosen;
  s=await create(chosen);const inherited=s.current_session.id;report.inheritedSession=inherited;
  assert(s.selected_memory.id===chosen&&s.conditions.budget===73,'saved version carried to a new session');
  const plan=await run('generate',page.getByTestId('meal-generate'));assert(plan.result.params.budget===73&&plan.result.params.kcal_min===470&&plan.result.params.kcal_max===610,'new session recalls nondefault parameters');
  const context=(await state(inherited)).objects.find(o=>o.id===plan.result.context_id);assert(context.payload.history_ids.length===0,'no previous conversation messages');
  await run('execute_sql',page.getByTestId('meal-execute'));
  await page.screenshot({path:path.join(out,'01-inherited-session.png'),fullPage:true});
  await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();
  const comparison=await run('meal_compare',page.getByRole('button',{name:'开始跨会话对比',exact:true}));
  report.firstComparison=comparison.result.comparison.map(r=>({mode:r.mode,status:r.status,error:r.error,verified:r.verification?.passed,reused:r.persistent_memory_reused,learning:r.learning_model_calls,answer:r.answer_model_calls,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms}));
  assert(comparison.result.comparison.every(r=>r.status==='complete'),'first comparison completes');
  assert(comparison.result.comparison.filter(r=>r.mode!=='stateless').every(r=>r.verification.passed&&r.audited),'inherited memory verified');
  const baseline=comparison.result.comparison.find(r=>r.mode==='stateless');assert(!baseline.memory_loaded&&!baseline.verification.passed,'no-memory differs from selected nondefault preferences');
  assert(report.liveSamples.some(sample=>sample.some(x=>x.tokens&&/\d/.test(x.tokens))),'provider tokens visible before overall completion');
  await page.screenshot({path:path.join(out,'02-first-comparison.png'),fullPage:true});
  s=await create(chosen);report.reuseSession=s.current_session.id;
  await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();await page.getByText('更多对比设置',{exact:true}).click();await page.getByLabel('加入“不加载记忆”对照组').uncheck();
  const again=await run('meal_compare',page.getByRole('button',{name:'开始跨会话对比',exact:true}));
  const deep=again.result.comparison.find(r=>r.mode==='deepagents');report.reuseComparison=again.result.comparison.map(r=>({mode:r.mode,status:r.status,error:r.error,verified:r.verification?.passed,reused:r.persistent_memory_reused,learning:r.learning_model_calls,answer:r.answer_model_calls,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms}));
  assert(deep.status==='complete'&&deep.persistent_memory_reused&&deep.learning_model_calls===0&&deep.verification.passed,'Deep Agents really reuses saved file without relearning');
  await page.screenshot({path:path.join(out,'03-reused-comparison.png'),fullPage:true});
  const empty=await create('');assert(!empty.selected_memory,'no-memory session');
  const control=await run('generate',page.getByTestId('meal-generate'));assert(!control.result.memory_loaded&&control.result.params.budget===120,'explicit no-memory control uses labeled defaults');
  await page.getByLabel('选择选餐会话').selectOption(inherited);await page.getByLabel('选餐SQL编辑器').waitFor();
  await page.reload();await page.getByLabel('选餐SQL编辑器').waitFor();assert(await page.getByLabel('选择选餐会话').inputValue()===inherited,'selected session persists on refresh');
  report.refreshPersistence=true;report.oldRecordsPreserved=(await state(inherited)).memory_snapshots.length>=2;
 }
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});for(const tab of ['选餐工作台','四层记忆','Deep Agents 对比']){await page.getByRole('tab',{name:tab,exact:true}).click();const l=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.layouts.push({...l,tab});assert(l.width===l.scrollWidth,'layout overflow '+JSON.stringify(l));}await page.screenshot({path:path.join(out,`layout-${width}.png`),fullPage:true});}
 assert(!errors.length,'JS errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
