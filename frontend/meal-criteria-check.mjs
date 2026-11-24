import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const base='http://127.0.0.1:8011';const workspace='qa-criteria-'+Date.now().toString(36),user='meal-'+workspace;
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-criteria');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));const report={workspace,user,errors,runs:[],layouts:[]};
const state=async()=>(await page.request.get(base+'/api/meal/state?user='+user)).json();
const assert=(v,m)=>{if(!v)throw Error(m);};
async function waitRun(action,before){for(let i=0;i<700;i++){await new Promise(r=>setTimeout(r,1000));const s=await state();const r=s.runs.find(r=>r.action===action&&!before.has(r.id));if(r&&r.status!=='running'){report.runs.push({action,id:r.id,status:r.status,error:r.error});return r;}}throw Error('timeout');}
async function run(action,button){const old=new Set((await state()).runs.map(r=>r.id));await button.click();const r=await waitRun(action,old);if(r.status==='failed')throw Error(r.error);await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));return r;}
try{
 const repaired=await (await page.request.get(base+'/api/meal/state?user=meal-mwkfszqg')).json();
 assert(repaired.selected_memory.payload.criteria_version===2&&repaired.selected_memory.payload.repaired_from,'existing dinner migrated');
 assert(repaired.conditions.kcal_min===0&&repaired.conditions.min_spice>=1&&repaired.conditions.budget===500,'existing real user preferences corrected');report.repairedMemory=repaired.selected_memory.id;
 await page.goto(base+'/?view=meal&user='+workspace);await page.getByLabel('简明偏好输入').waitFor();
 await page.getByLabel('简明记忆名称').fill('晚饭偏好');await page.getByLabel('简明偏好输入').fill('我特别喜欢吃辣，晚饭预算500块，热量尽量控制在1000千卡。简单推荐三种就行。');
 const saved=await run('remember',page.getByRole('button',{name:'保存这份记忆',exact:true}));
 const loaded=await state();const c=loaded.selected_memory.payload.conditions;assert(c.min_spice>=1&&c.max_spice===2&&c.budget===500&&c.kcal_max===1000&&!('kcal_min'in c)&&c.meal_period==='dinner','correct memory semantics');
 await page.getByRole('button',{name:'下一步：新会话测试',exact:true}).click();await page.getByRole('button',{name:'新开会话并加载',exact:true}).click();
 await page.getByLabel('简明测试问题').fill('晚上吃什么好');
 const result=await run('test_session',page.getByRole('button',{name:'测试它是否记得',exact:true}));
 assert(result.result.approved.length===3&&result.result.approved.every(r=>r.hot_lv>=1&&r.kcal_hi<=1000&&r.price<=500),'all actual recommendations respect spicy dinner');
 assert(result.result.params.kcal_min===0&&result.result.memory_test.current_session_history_count===0,'no inherited 470 lower or old chat');
 await page.getByText('条件读取与推荐均已核验',{exact:true}).waitFor();assert((await page.locator('.meal-demo-condition-pills').innerText()).includes('未设下限'),'UI distinguishes unset lower bound');
 await page.screenshot({path:path.join(out,'01-dinner.png'),fullPage:true});
 await page.getByLabel('简明测试问题').fill('明天中午吃什么好');const before=new Set((await state()).runs.map(r=>r.id));await page.getByRole('button',{name:'测试它是否记得',exact:true}).click();const mismatch=await waitRun('test_session',before);assert(mismatch.status==='failed'&&mismatch.error.includes('餐次'),'meal mismatch blocked');report.mealMismatch=true;
 await page.getByLabel('简明测试问题').fill('晚上吃什么好');await page.getByRole('button',{name:'3 Deep Agents 对比'}).click();
 const compared=await run('meal_compare',page.getByRole('button',{name:'开始跨会话对比',exact:true}));report.comparison=compared.result.comparison.map(r=>({mode:r.mode,status:r.status,error:r.error,passed:r.verification?.passed,params:r.params,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms}));
 assert(compared.result.comparison.every(r=>r.status==='complete'&&r.verification.passed&&r.approved.every(a=>a.hot_lv>=1)&&r.params.kcal_min===0),'both independent frameworks match dinner');
 await page.screenshot({path:path.join(out,'02-comparison.png'),fullPage:true});
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-innerWidth)<2);const l=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));report.layouts.push(l);assert(l.width===l.scroll,'no overflow');}
 assert(!errors.length,'no JS errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
