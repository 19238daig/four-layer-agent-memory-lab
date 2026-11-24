import {chromium} from 'playwright-core';
const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
const page=await browser.newPage();await page.addInitScript(()=>localStorage.setItem('meal-space:demo','meal-mwk58p94'));
for(const width of [1440,1684,1920,2526]){
 await page.setViewportSize({width,height:950});await page.goto('http://127.0.0.1:8010/?view=meal');await page.getByRole('button',{name:'高级详情',exact:true}).click();await page.getByLabel('选择选餐会话').waitFor();
 await page.waitForFunction(()=>document.querySelector('[aria-label="选择选餐会话"]')?.value.startsWith('session-'));
 console.log(JSON.stringify(await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,rects:['.app-shell','.main-shell','#main-content','.meal-lab','.meal-session-panel','.meal-session-controls','.meal-work-grid'].map(selector=>{const e=document.querySelector(selector),r=e.getBoundingClientRect(),c=getComputedStyle(e);return {selector,x:r.x,width:r.width,right:r.right,cssWidth:c.width,margin:c.margin,overflow:c.overflow,minWidth:c.minWidth,display:c.display};})}))));
}
await browser.close();
