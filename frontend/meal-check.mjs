import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const origin=process.env.MEAL_CHECK_URL||'http://127.0.0.1:8011';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-lab');
await fs.mkdir(root,{recursive:true});
const user=process.env.MEAL_CHECK_USER||'qa-meal-'+Date.now().toString(36);
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce',permissions:['clipboard-read','clipboard-write']});
const page=await context.newPage();const errors=[];const report={user,errors,runs:[],layouts:[]};
page.on('pageerror',e=>errors.push(e.message));
let mealUser;
async function getState(){return (await page.request.get(origin+'/api/meal/state?user='+mealUser)).json();}
async function clickRun(button,action){const before=new Set((await getState()).runs.map(r=>r.id));await button.click();const start=Date.now();while(Date.now()-start<18*60*1000){await new Promise(r=>setTimeout(r,1300));const s=await getState();const run=s.runs.find(r=>r.action===action&&!before.has(r.id));if(run?.status==='failed')throw Error(action+': '+run.error);if(run?.status==='complete'){report.runs.push({action,id:run.id});await page.waitForFunction(id=>document.querySelector('.meal-progress')?.textContent?.includes('进行中')!==true,run.id);return run;}}throw Error('timeout '+action);}
function assert(v,message){if(!v)throw Error(message);}
try{
 await page.goto(origin+'/?view=meal&user='+user,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'高级详情',exact:true}).click();
 mealUser='meal-'+user;
 await page.waitForFunction(()=>!!document.querySelector('textarea[aria-label="选餐偏好输入"]')||Array.from(document.querySelectorAll('button')).some(b=>b.textContent?.includes('初始化专用数据库')&&!b.disabled));
 if(await page.getByRole('button',{name:'初始化专用数据库',exact:true}).isVisible())await page.getByRole('button',{name:'初始化专用数据库',exact:true}).click();
 await page.getByLabel('选餐偏好输入').waitFor();
 await page.screenshot({path:path.join(root,'01-initial.png'),fullPage:true});
 const current=await getState();
 if(!process.argv.includes('--resume')||!current.runs.some(r=>r.action==='execute_sql'&&r.status==='complete')){
  await clickRun(page.getByRole('button',{name:'保存偏好并整理记忆',exact:true}),'remember');
  const plan=await clickRun(page.getByTestId('meal-generate'),'generate');
  assert(plan.result.params.kcal_min===600&&plan.result.params.kcal_max===700,'initial constraints');
  await page.screenshot({path:path.join(root,'02-generated.png'),fullPage:true});
  const result=await clickRun(page.getByTestId('meal-execute'),'execute_sql');
  assert(result.result.audited&&result.result.approved.length===3,'audited recommendations');
  assert(result.result.counts.unknown>=6,'missing values stay unknown');
  const s=await getState();const snapshot=s.objects.find(o=>o.id===result.result.result_id);
  for(const r of result.result.approved){const sum=snapshot.payload.details[r.offer_id].reduce((a,x)=>a+x.ingredient_kcal,0);assert(Math.abs(sum-r.base_kcal)<.02,'ingredient reconciliation');}
 }
 await page.locator('.meal-offer').first().waitFor();
 await page.screenshot({path:path.join(root,'03-results.png'),fullPage:true});
 await page.locator('.meal-offer').first().click();await page.getByRole('dialog',{name:'热量计算明细'}).waitFor();
 await page.screenshot({path:path.join(root,'04-calculation.png'),fullPage:true});
 await page.getByRole('button',{name:'关闭选餐详情'}).click();
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});const l=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.layouts.push(l);await page.screenshot({path:path.join(root,`work-${width}.png`),fullPage:true});assert(l.scrollWidth===width,'horizontal overflow '+JSON.stringify(l));}
 await page.setViewportSize({width:1440,height:1050});
 await page.getByRole('tab',{name:'四层记忆',exact:true}).click();await page.screenshot({path:path.join(root,'05-memory.png'),fullPage:true});
 const s=await getState();assert([1,2,3,4].every(l=>s.objects.some(o=>o.layer===l)),'all four layers');
 const note=s.objects.find(o=>o.kind==='note'&&o.payload.condition==='kcal_min');
 await page.getByRole('button',{name:new RegExp(note.title)}).first().click();await page.getByRole('dialog',{name:'选餐来源详情'}).waitFor();await page.keyboard.press('Escape');
 await page.getByRole('tab',{name:'数据库与口径',exact:true}).click();await page.getByRole('heading',{name:/menu_item/}).waitFor();
 await page.screenshot({path:path.join(root,'06-database.png'),fullPage:true});
 await page.getByRole('tab',{name:'选餐工作台',exact:true}).click();
 if(!process.argv.includes('--resume')){
  await page.getByRole('button',{name:'试试修改热量目标'}).click();await clickRun(page.getByRole('button',{name:'保存偏好并整理记忆',exact:true}),'remember');
  const updated=await clickRun(page.getByTestId('meal-generate'),'generate');assert(updated.result.params.kcal_min===500&&updated.result.params.kcal_max===600,'updated target');
  const changed=await clickRun(page.getByTestId('meal-execute'),'execute_sql');assert(changed.result.audited,'updated query');
  await page.getByRole('button',{name:'试试模糊菜名“鸡饭”'}).click();const ambiguous=await clickRun(page.getByTestId('meal-generate'),'generate');assert(ambiguous.result.ambiguous,'ambiguous name');
  await page.getByLabel('菜名消歧选择').waitFor();
  assert(await page.getByTestId('meal-execute').isDisabled(),'ambiguity prevents silent execution');
  await page.getByLabel('菜名消歧选择').selectOption('I000');await clickRun(page.getByTestId('meal-execute'),'execute_sql');
  await page.screenshot({path:path.join(root,'07-ambiguity.png'),fullPage:true});
  const editor=page.getByLabel('选餐SQL编辑器');const original=await editor.inputValue();
  await editor.fill('SELECT 1 AS exploratory_value');const exploratory=await clickRun(page.getByTestId('meal-execute'),'execute_sql');assert(!exploratory.result.audited&&!exploratory.result.approved.length,'exploration not used as recommendation');
  await editor.fill('DELETE FROM menu_item');const before=new Set((await getState()).runs.map(r=>r.id));await page.getByTestId('meal-execute').click();let failed;for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,900));failed=(await getState()).runs.find(r=>!before.has(r.id));if(failed?.status==='failed')break;}assert(failed?.status==='failed','mutation rejected');report.readonlyRejected=failed.error;
  await editor.fill(original);await page.getByLabel('选餐问题输入').fill('明天中午吃什么比较合适？');
  // Restore a standard final result for the review page.
  await clickRun(page.getByTestId('meal-generate'),'generate');await clickRun(page.getByTestId('meal-execute'),'execute_sql');
 }
 if(process.argv.includes('--compare')){
  await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();const compared=await clickRun(page.getByRole('button',{name:'开始真实对比',exact:true}),'meal_compare');
  report.comparison=compared.result.comparison.map(r=>({mode:r.mode,status:r.status,audited:r.audited,model_calls:r.model_calls,total_tokens:r.total_tokens,error:r.error}));
  assert(compared.result.comparison.every(r=>r.status==='complete'&&r.audited),'both real comparison branches');
  await page.screenshot({path:path.join(root,'08-comparison.png'),fullPage:true});
 }
 await page.reload();await page.getByLabel('选餐SQL编辑器').waitFor();assert((await page.getByLabel('选餐SQL编辑器').inputValue()).includes('WITH'),'plan restored');
 report.complete=true;report.refreshPersistence=true;report.url=origin+'/?view=meal&user='+user;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(root,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
if(errors.length)throw Error(errors.join('\n'));
