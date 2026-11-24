import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../artifacts/meal-zoom');await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.addInitScript(()=>localStorage.setItem('meal-space:demo','meal-mwk58p94'));
const cdp=await page.context().newCDPSession(page);const results=[];
try{
 for(const [width,scale] of [[2526,1],[2526,1.25],[2526,1.5],[2526,2],[2526,3],[1920,1.5],[1920,2],[1440,1],[1024,1],[768,1],[390,1]]){
  await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1});await page.setViewportSize({width,height:1400});
  await page.goto('http://127.0.0.1:8010/?view=meal');await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选择选餐会话').waitFor();await page.waitForFunction(()=>document.querySelector('[aria-label="选择选餐会话"]')?.value.startsWith('session-'));
  await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:scale});
  await page.waitForFunction(()=>Math.abs(document.querySelector('.app-shell').getBoundingClientRect().width-visualViewport.width)<2);
  for(const tab of ['选餐工作台','四层记忆','Deep Agents 对比']){
   await page.getByRole('tab',{name:tab,exact:true}).click();
   const result=await page.evaluate(()=>{const visible=visualViewport.width;const selectors=['.meal-session-controls > button','.meal-session-controls select','.meal-save-memory button','.meal-sql','.meal-compare-intro > button','.meal-live-stats'];const rects=selectors.flatMap(s=>Array.from(document.querySelectorAll(s))).filter(e=>e.getClientRects().length).map(e=>{const r=e.getBoundingClientRect();return {name:e.getAttribute('aria-label')||e.className,left:r.left,right:r.right,width:r.width};});return {layout:innerWidth,visible,scale:visualViewport.scale,rects,clipped:rects.filter(r=>r.right>visible+1||r.left<-.5)};});
   results.push({tab,...result});if(result.clipped.length)throw Error('Controls outside visible viewport: '+JSON.stringify(results.at(-1)));
  }
  if((width===2526&&[1,1.5,2].includes(scale))||width===390){await page.getByRole('tab',{name:'选餐工作台',exact:true}).click();await page.evaluate(()=>{document.activeElement?.blur();scrollTo(0,0);});await page.screenshot({path:path.join(out,`fixed-${width}-${scale}.png`)});}
 }
 console.log(JSON.stringify({errors,scenarios:results.length,complete:true}));
 await fs.writeFile(path.join(out,'report.json'),JSON.stringify({errors,results,complete:true},null,2));
 if(errors.length)throw Error(errors.join('\n'));
}finally{await browser.close();}
