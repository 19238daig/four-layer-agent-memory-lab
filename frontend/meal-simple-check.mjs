import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const origin=process.env.MEAL_CHECK_URL||'http://127.0.0.1:8011',user='meal-qa-sessions-mwkgi4xm';
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-simple');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const report={errors,runs:[],layouts:[]};const get=async(session='')=>(await page.request.get(origin+'/api/meal/state?user='+user+(session?'&session='+session:''))).json();
const assert=(v,m)=>{if(!v)throw Error(m);};
async function run(action,button){const old=new Set((await get()).runs.map(r=>r.id));await button.click();for(let i=0;i<700;i++){await new Promise(r=>setTimeout(r,1200));const r=(await get()).runs.find(r=>r.action===action&&!old.has(r.id));if(r?.status==='failed')throw Error(r.error);if(r?.status==='complete'){report.runs.push({action,id:r.id});await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));return r;}}throw Error('timeout');}
try{
 await page.goto(origin+'/?view=meal&user=qa-sessions-mwkgi4xm');await page.locator('.meal-demo-steps').waitFor();
 assert(!await page.getByLabel('选餐SQL编辑器').count(),'SQL not on default screen');
 await page.getByText('切换以前的会话或其他记忆空间',{exact:true}).click();await page.getByLabel('简明切换会话').selectOption('session-92048043b9');
 await page.getByRole('button',{name:'1 保存一份记忆'}).click();
 await page.getByLabel('简明记忆名称').fill('简洁演示记忆');await page.getByRole('button',{name:'填入演示示例'}).click();
 await run('remember',page.getByRole('button',{name:'保存这份记忆',exact:true}));
 await page.getByText('已保存：简洁演示记忆',{exact:true}).waitFor();await page.screenshot({path:path.join(out,'01-save.png'),fullPage:true});
 await page.getByRole('button',{name:'下一步：新会话测试',exact:true}).click();
 const before=(await get()).session_list.map(s=>s.id);await page.getByRole('button',{name:'新开会话并加载',exact:true}).click();
 let session;for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,500));const s=await get();if(!before.includes(s.current_session.id)){session=s.current_session.id;break;}}
 assert(session,'new session created');report.session=session;
 await page.getByLabel('简明测试问题').fill('明天中午吃什么比较合适？');
 const tested=await run('test_session',page.getByRole('button',{name:'测试它是否记得',exact:true}));
 assert(tested.result.memory_test.passed&&tested.result.params.budget===73&&tested.result.memory_test.current_session_history_count===0,'new session remembered selected nondefault memory without chat');
 await page.getByText('选定记忆已生效',{exact:true}).waitFor();await page.screenshot({path:path.join(out,'02-test.png'),fullPage:true});
 await page.getByRole('button',{name:'下一步：对比 Deep Agents',exact:true}).click();
 assert(await page.locator('.meal-compare-card').count()===2,'two default groups');
 const compared=await run('meal_compare',page.getByRole('button',{name:'开始跨会话对比',exact:true}));
 assert(compared.result.comparison.length===2&&compared.result.comparison.every(r=>r.status==='complete'&&r.verification.passed),'two actual verified groups');
 report.comparison=compared.result.comparison.map(r=>({mode:r.mode,elapsed_ms:r.elapsed_ms,tokens:r.total_tokens,learning:r.learning_model_calls,reused:r.persistent_memory_reused}));
 await page.screenshot({path:path.join(out,'03-compare.png'),fullPage:true});
 await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByRole('tab',{name:'数据库与口径',exact:true}).click();await page.getByRole('heading',{name:'计算公式与数据口径'}).waitFor();
 await page.getByRole('button',{name:'返回简明演示',exact:true}).click();await page.locator('.meal-demo-steps').waitFor();
 for(const width of [1440,1024,768,390]){await page.setViewportSize({width,height:950});const l=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));report.layouts.push(l);assert(l.width===l.scrollWidth,'no overflow');}
 await page.setViewportSize({width:2526,height:1400});const cdp=await page.context().newCDPSession(page);await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1.5});
 await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-visualViewport.width)<2);
 assert(await page.evaluate(()=>Array.from(document.querySelectorAll('.meal-compare-card')).every(e=>e.getBoundingClientRect().right<=visualViewport.width+1)),'pinch zoom keeps both cards visible');
 assert(!errors.length,'JS errors');report.complete=true;
}catch(e){report.failure=e.stack;throw e;}finally{await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));await browser.close();console.log(JSON.stringify(report));}
