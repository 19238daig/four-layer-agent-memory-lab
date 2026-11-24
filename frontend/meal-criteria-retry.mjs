import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const base=process.env.MEAL_QA_BASE||'http://127.0.0.1:8011',out='../artifacts/meal-criteria';
const old=JSON.parse(await fs.readFile(out+'/report.json','utf8'));
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
const report={workspace:old.workspace,user:old.user,priorAttempt:old,errors:[],layouts:[]};
page.on('pageerror',e=>report.errors.push(e.message));
const state=async()=>(await page.request.get(base+'/api/meal/state?user='+old.user)).json();
const assert=(v,m)=>{if(!v)throw Error(m);};
try{
 const s=await state();
 const test=s.runs.find(r=>r.action==='test_session'&&r.status==='complete');
 await page.goto(base+'/?view=meal&user='+old.workspace);
 await page.evaluate(({u,session})=>{localStorage.setItem('meal-active-session:'+u,session);localStorage.setItem('meal-demo-step:'+u,'compare');}, {u:old.user,session:test.session});
 await page.reload();
 if(process.env.MEAL_QA_BASE){
  await page.getByRole('button',{name:'2 新会话测试'}).click();
  await page.getByRole('button',{name:'新开会话并加载',exact:true}).click();
  await page.getByLabel('简明测试问题').fill('晚上吃什么好');
  const previous=new Set((await state()).runs.map(r=>r.id));
  await page.getByRole('button',{name:'测试它是否记得',exact:true}).click();
  let check;
  for(let i=0;i<180;i++){await new Promise(r=>setTimeout(r,1000));check=(await state()).runs.find(r=>r.action==='test_session'&&!previous.has(r.id));if(check&&check.status!=='running')break;}
  assert(check?.status==='complete',check?.error||'test timeout');
  assert(check.result.memory_test.passed&&check.result.memory_test.current_session_history_count===0,'fresh session remembers without old chat');
  assert(new Set(check.result.approved.map(r=>r.offer_name.split(' · ')[0])).size===3,'three distinct dishes');
  report.sessionTest={id:check.id,params:check.result.params,approved:check.result.approved};
  await page.getByText('条件读取与推荐均已核验',{exact:true}).waitFor();
  await page.screenshot({path:out+'/03-production-dinner.png',fullPage:true});
  await page.getByRole('button',{name:'3 Deep Agents 对比'}).click();
 }
 await page.getByLabel('简明对比问题').fill('晚上吃什么好');
 const before=new Set((await state()).runs.map(r=>r.id));
 await page.getByRole('button',{name:'开始跨会话对比',exact:true}).click();
 let run;
 for(let i=0;i<480;i++){await new Promise(r=>setTimeout(r,1000));run=(await state()).runs.find(r=>r.action==='meal_compare'&&!before.has(r.id));if(run&&run.status!=='running')break;}
 assert(run?.status==='complete',run?.error||'comparison timeout');report.run=run.id;
 report.comparison=run.result.comparison.map(r=>({mode:r.mode,status:r.status,error:r.error,passed:r.verification?.passed,params:r.params,tokens:r.total_tokens,elapsed_ms:r.elapsed_ms,corrected_attempts:r.corrected_attempts,source_retrievals:r.source_retrievals,cached:r.persistent_memory_reused,approved:r.approved}));
 assert(run.result.comparison.every(r=>r.status==='complete'&&r.verification.passed&&r.approved.length===3&&r.approved.every(a=>a.hot_lv>=1&&a.kcal_hi<=1000&&a.price<=500)&&r.params.kcal_min===0&&r.params.recommend_count===3),'both independent frameworks match dinner');
 await page.waitForFunction(()=>document.querySelectorAll('.meal-memory-verdict').length===2);
 await page.screenshot({path:out+'/02-comparison.png',fullPage:true});
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-innerWidth)<2);const l=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));report.layouts.push(l);assert(l.width===l.scroll,'no overflow');}
 assert(!report.errors.length,'no browser errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(out+(process.env.MEAL_QA_BASE?'/production-report.json':'/retry-report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
