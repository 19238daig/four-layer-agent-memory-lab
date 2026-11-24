import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/browser-demo');
await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
const page=await context.newPage();
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
const previous=process.argv.includes('--resume')?JSON.parse(await fs.readFile(path.join(out,'report.json'),'utf8')):null;
const user=previous?.user||'browser-demo-'+Date.now().toString(36);
const report=previous?{...previous,errors,layouts:[]}: {user,steps:[],errors,layouts:[]};
async function state(){return await (await page.request.get('http://127.0.0.1:8010/api/state?user='+user)).json();}
async function save(){await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));}
async function execute(index){
 await page.locator(`[data-step="${index}"]`).click();
 await page.getByTestId('execute-step').waitFor();
 await page.waitForFunction(()=>!document.querySelector('[data-testid="execute-step"]').disabled);
 await page.getByTestId('execute-step').click();
 await page.locator('.studio-execution-status').filter({hasText:'本步执行完成'}).waitFor({timeout:900000});
 const data=await state();
 assert.equal(data.runs[0].status,'complete',JSON.stringify(data.runs[0]));
 report.steps.push({index,action:data.runs[0].action,run_id:data.runs[0].id});
 await save();
 console.log(`Browser step ${index+1} passed: ${data.runs[0].action}`);
 return data;
}

try{
 if(previous){
  const data=await state();
  const chronological=[...data.runs].reverse().filter(r=>r.action!=='replay');
  const saved={step:8,runs:{},drafts:{},questions:{},expected:{}};
  let offset=0;
  for(const [index,count] of [2,1,1,1,1,4,2,1,1].entries()){
   saved.runs[index]=chronological.slice(offset,offset+count).map(r=>r.id);
   saved.expected[index]=count;offset+=count;
  }
  await context.addInitScript(({user,saved})=>{if(!localStorage.getItem('memory-lab-studio:'+user))localStorage.setItem('memory-lab-studio:'+user,JSON.stringify(saved));},{user,saved});
 }
 await page.goto('http://127.0.0.1:8010/?user='+user+'&view=studio',{waitUntil:'domcontentloaded'});
 await page.locator('.connection').filter({hasText:'实时同步'}).waitFor();
 assert.equal(await page.getByRole('button',{name:'交互演示',exact:true}).count(),1);
 assert.ok(!(await page.locator('body').innerText()).includes('PowerShell'));
 await page.screenshot({path:path.join(out,'studio-initial.png'),fullPage:true});
 if(!previous){
 await execute(0);
 assert.equal((await state()).objects.filter(o=>o.layer===1).length,2);
 await execute(1);
 await page.getByRole('button',{name:'引用来源',exact:true}).click();
 await page.locator('.studio-source-row .inline-ref').first().click();
 await page.getByRole('dialog').waitFor();
 assert.ok((await page.getByRole('dialog').innerText()).includes('用户消息'));
 await page.keyboard.press('Escape');
 await execute(2);
 await execute(3);
 const first=await execute(4);
 assert.ok(first.runs[0].result.cited_ids.length>0);
 const answer=first.objects.find(o=>o.id===first.runs[0].result.answer_id);
 assert.ok(answer.session.startsWith('day2-'));
 await page.screenshot({path:path.join(out,'studio-answer.png'),fullPage:true});
 const corrected=await execute(5);
 assert.ok(corrected.objects.some(o=>o.active&&o.kind==='note'&&o.payload.key==='diet.lunch_budget'&&o.content.includes('120')));
 await page.screenshot({path:path.join(out,'studio-correction.png'),fullPage:true});
 const raw=await execute(6);
 assert.ok(raw.runs[0].result.answer.includes('年糕'));
 assert.ok(raw.runs[0].result.cited_ids.some(id=>id.startsWith('T-')));
 const irrelevant=await execute(7);
 assert.deepEqual(irrelevant.runs[0].result.read_ids,[]);
 const comparison=await execute(8);
 assert.equal(comparison.runs[0].result.comparison.length,3);
 assert.ok(comparison.runs[0].result.comparison.every(row=>row.status==='complete'));
 await page.screenshot({path:path.join(out,'studio-comparison.png'),fullPage:true});
 }
 await page.reload({waitUntil:'domcontentloaded'});
 await page.locator('.studio-comparison article').first().waitFor();
 assert.equal(await page.locator('.studio-step[aria-current="step"]').getAttribute('data-step'),'8');
 report.refreshPersistence=true;
 await page.locator('[data-step="4"]').click();
 await page.getByLabel('演示输入',{exact:true}).fill('周末想吃点清淡的，帮我想两种。');
 await page.reload({waitUntil:'domcontentloaded'});
 await page.locator('.studio-step[aria-current="step"][data-step="4"]').waitFor();
 assert.equal(await page.getByLabel('演示输入',{exact:true}).inputValue(),'周末想吃点清淡的，帮我想两种。');
 report.inputPersistence=true;
 await page.getByLabel('演示输入',{exact:true}).fill('周末午饭吃点什么比较合适？');
 await page.getByRole('button',{name:'自由操作',exact:true}).click();
 await page.getByLabel('自由操作类型').selectOption('context');
 await page.getByTestId('execute-step').click();
 await page.locator('.studio-execution-status').filter({hasText:'本步执行完成'}).waitFor();
 report.freeOperation=true;
 await page.getByRole('button',{name:'分步演示',exact:true}).click();
 await page.locator('[data-step="4"]').click();
 for(const width of [1440,1024,768,390]){
  await page.setViewportSize({width,height:950});
  const layout=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));
  report.layouts.push(layout);
  assert.equal(layout.scrollWidth,width,`Horizontal overflow at ${width}`);
  await page.screenshot({path:path.join(out,`studio-${width}.png`),fullPage:true});
 }
 assert.deepEqual(errors,[]);
 report.complete=true;
 await save();
 console.log(JSON.stringify(report));
}finally{await save();await browser.close();}
