import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const origin='http://127.0.0.1:8010';const user='meal-qa-meal-mwk3vsxm';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const get=async()=>(await page.request.get(origin+'/api/meal/state?user='+user)).json();
try{
 await page.goto(origin+'/?view=meal&user=qa-meal-mwk3vsxm');await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选餐SQL编辑器').waitFor();
 const before=new Set((await get()).runs.map(r=>r.id));await page.getByTestId('meal-execute').click();let run;
 for(let i=0;i<140;i++){await new Promise(r=>setTimeout(r,1500));run=(await get()).runs.find(r=>r.action==='execute_sql'&&!before.has(r.id));if(run?.status==='failed')throw Error(run.error);if(run?.status==='complete')break;}
 if(run?.status!=='complete'||!run.result.audited)throw Error('Production execution failed');
 await page.waitForFunction(()=>!document.querySelector('.meal-progress')?.textContent?.includes('进行中'));
 const s=await get();const answer=s.objects.find(o=>o.id===run.result.answer_id);
 if(answer.payload.refs.length<3)throw Error('Recommendation citations missing');
 await page.screenshot({path:new URL('../artifacts/meal-lab/production-results.png',import.meta.url).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
 const proof={origin,user,run_id:run.id,audited:run.result.audited,counts:run.result.counts,cited:answer.payload.refs,errors,complete:true};
 await fs.writeFile(new URL('../artifacts/meal-lab/production-report.json',import.meta.url),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await browser.close();}
