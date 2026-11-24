import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const base='http://127.0.0.1:8010',workspace='qa-start-'+Date.now().toString(36),user='meal-'+workspace;
const folder=new URL('../artifacts/project-start/'+workspace+'/',import.meta.url);
await fs.mkdir(folder,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const report={workspace,user,url:base,errors:[],runs:[]};
page.on('pageerror',e=>report.errors.push(e.message));
const assert=(value,reason)=>{if(!value)throw Error(reason);};
const state=async()=>(await page.request.get(base+'/api/meal/state?user='+user)).json();
async function operate(action,name){
 const prior=new Set((await state()).runs.map(r=>r.id));
 await page.getByRole('button',{name,exact:true}).click();
 for(let i=0;i<240;i++){
  await new Promise(r=>setTimeout(r,1000));
  const run=(await state()).runs.find(r=>r.action===action&&!prior.has(r.id));
  if(run&&run.status!=='running'){
   report.runs.push({action,id:run.id,status:run.status,error:run.error});
   assert(run.status==='complete',run.error||action+' failed');
   console.log(JSON.stringify({action,run:run.id,status:run.status}));return run;
  }
 }
 throw Error(action+' timeout');
}
try{
 const health=await (await page.request.get(base+'/api/health')).json();assert(health.ok,'health');report.health=health;
 await page.goto(base+'/?view=studio&user='+workspace);await page.getByRole('heading',{name:'从一句日常对话开始',exact:true}).waitFor();report.studio=true;
 await page.goto(base+'/?view=meal&user='+workspace);await page.getByLabel('简明偏好输入').waitFor();
 await page.getByLabel('简明记忆名称').fill('启动验收晚饭偏好');
 await page.getByLabel('简明偏好输入').fill('我特别喜欢吃辣，晚饭预算500块，热量尽量控制在1000千卡。简单推荐三种就行。');
 await operate('remember','保存这份记忆');
 await page.getByRole('button',{name:'下一步：新会话测试',exact:true}).click();
 await page.getByRole('button',{name:'新开会话并加载',exact:true}).click();
 await page.getByLabel('简明测试问题').fill('晚上吃什么好');
 const test=await operate('test_session','测试它是否记得');
 assert(test.result.memory_test.passed&&test.result.memory_test.current_session_history_count===0,'fresh session memory');
 assert(test.result.params.kcal_min===0&&test.result.params.min_spice>=1,'condition semantics');
 assert(test.result.approved.length===3&&test.result.approved.every(r=>r.hot_lv>=1&&r.kcal_hi<=1000&&r.price<=500),'actual dish constraints');
 await page.getByText('条件读取与推荐均已核验',{exact:true}).waitFor();
 await page.screenshot({path:new URL('session.png',folder).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
 await page.getByRole('button',{name:'3 Deep Agents 对比'}).click();
 const compare=await operate('meal_compare','开始跨会话对比');
 report.comparison=compare.result.comparison.map(r=>({mode:r.mode,status:r.status,error:r.error,passed:r.verification?.passed,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms,learning:r.learning_model_calls,corrections:r.corrected_attempts,query_retries:r.query_retries}));
 assert(compare.result.comparison.length===2&&compare.result.comparison.every(r=>r.status==='complete'&&r.verification.passed&&r.approved.length===3),'both frameworks');
 await page.waitForFunction(()=>document.querySelectorAll('.meal-memory-verdict').length===2);
 await page.screenshot({path:new URL('compare.png',folder).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
 await page.reload();await page.locator('.meal-memory-verdict').first().waitFor();report.restore=true;
 report.layers=[...new Set((await state()).objects.map(o=>o.layer))].sort();assert([1,2,3,4].every(n=>report.layers.includes(n)),'four persisted layers');
 assert(!report.errors.length,'browser errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(new URL('report.json',folder),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
