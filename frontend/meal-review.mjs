import {chromium} from 'playwright-core';
import fs from 'node:fs/promises';
const origin=process.env.MEAL_CHECK_URL||'http://127.0.0.1:8011';
const user='qa-meal-mwk3vsxm';
const out=new URL('../artifacts/meal-lab/',import.meta.url);await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1050},reducedMotion:'reduce'});
const errors=[];page.on('pageerror',e=>errors.push(e.message));const layouts=[];
try{
 await page.goto(origin+'/?view=meal&user='+user);await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选餐SQL编辑器').waitFor();
 for(const width of [1440,1024,768,390]){
  await page.setViewportSize({width,height:950});
  for(const tab of ['选餐工作台','四层记忆','数据库与口径','Deep Agents 对比','运行轨迹']){
   await page.getByRole('tab',{name:tab,exact:true}).click();
   const l=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}));layouts.push({...l,tab});
   if(l.scrollWidth>width)throw Error('overflow '+JSON.stringify(layouts.at(-1)));
   if(width===1440||width===390)await page.screenshot({path:new URL(`review-${width}-${tab}.png`,out).pathname.replace(/^\/(\w:)/,'$1'),fullPage:true});
  }
 }
 await page.setViewportSize({width:1440,height:1050});await page.getByRole('tab',{name:'Deep Agents 对比',exact:true}).click();
 const source=page.locator('.meal-compare-card').first().locator('.meal-ref').first();await source.click();await page.getByRole('dialog',{name:'选餐来源详情'}).waitFor();
 await page.keyboard.press('Escape');
 if(errors.length)throw Error(errors.join('\n'));
 await fs.writeFile(new URL('review-report.json',out),JSON.stringify({errors,layouts,comparisonSourceTrace:true,complete:true},null,2));
 console.log(JSON.stringify({errors,layouts,comparisonSourceTrace:true,complete:true}));
}finally{await browser.close();}
