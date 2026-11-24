import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
const base='http://127.0.0.1:8011';
const dir=path.resolve('../artifacts/meal-lab');
const previous=JSON.parse(await fs.readFile(path.join(dir,'report.json'),'utf8'));
const user=previous.user;
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
const report={user,errors:[],runs:[]};page.on('pageerror',e=>report.errors.push(e.message));
async function state(){return (await page.request.get(base+'/api/meal/state?user=meal-'+user)).json();}
async function run(action,click){const before=new Set((await state()).runs.map(r=>r.id));await click();for(let i=0;i<800;i++){await new Promise(r=>setTimeout(r,1300));const s=await state();const r=s.runs.find(r=>r.action===action&&!before.has(r.id));if(r?.status==='failed')throw Error(r.error);if(r?.status==='complete'){report.runs.push({action,id:r.id});await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));return r;}}throw Error('timeout');}
try{
 await page.goto(base+'/?view=meal&user='+user);
 await page.getByRole('button',{name:'高级详情',exact:true}).click();
 await page.getByLabel('菜名消歧选择').waitFor();
 if(!await page.getByTestId('meal-execute').isDisabled())throw Error('ambiguity guard');
 await page.getByLabel('菜名消歧选择').selectOption('I000');
 await run('execute_sql',()=>page.getByTestId('meal-execute').click());
 await page.screenshot({path:path.join(dir,'07-ambiguity.png'),fullPage:true});
 const editor=page.getByLabel('选餐SQL编辑器');await editor.fill('SELECT 1 AS exploratory_value');
 const exploratory=await run('execute_sql',()=>page.getByTestId('meal-execute').click());
 if(exploratory.result.audited||exploratory.result.approved.length)throw Error('exploration certification');
 await editor.fill('DELETE FROM menu_item');const before=new Set((await state()).runs.map(r=>r.id));await page.getByTestId('meal-execute').click();
 let failed;for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,800));failed=(await state()).runs.find(r=>!before.has(r.id));if(failed?.status==='failed')break;}
 if(failed?.status!=='failed')throw Error('mutation not rejected');report.readonlyRejected=failed.error;
 await page.getByLabel('选餐问题输入').fill('明天中午吃什么比较合适？');
 await run('generate',()=>page.getByTestId('meal-generate').click());await page.getByLabel('菜名消歧选择').waitFor({state:'hidden'});
 await run('execute_sql',()=>page.getByTestId('meal-execute').click());
 await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();
 const compared=await run('meal_compare',()=>page.getByRole('button',{name:'开始真实对比',exact:true}).click());
 report.comparison=compared.result.comparison.map(r=>({mode:r.mode,status:r.status,audited:r.audited,model_calls:r.model_calls,total_tokens:r.total_tokens,error:r.error}));
 if(!compared.result.comparison.every(r=>r.status==='complete'&&r.audited))throw Error('comparison branch failed');
 await page.screenshot({path:path.join(dir,'08-comparison.png'),fullPage:true});
 await page.getByRole('tab',{name:'选餐工作台',exact:true}).click();await page.getByLabel('选餐问题输入').fill('明天想吃清淡一点，有哪些选择？');
 await page.reload();await page.getByLabel('选餐SQL编辑器').waitFor();
 if(await page.getByLabel('选餐问题输入').inputValue()!=='明天想吃清淡一点，有哪些选择？')throw Error('draft persistence');
 report.refreshPersistence=true;report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(dir,'edge-report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
