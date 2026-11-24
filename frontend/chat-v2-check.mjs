import { chromium } from 'playwright-core';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const origin = process.env.CHAT_CHECK_URL || 'http://127.0.0.1:8010';
const workspace = 'qa-chat-' + Date.now().toString(36);
const user = 'meal-' + workspace;
const output = new URL('../artifacts/chat-v2/' + workspace + '/', import.meta.url);
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport:{width:1440,height:900}});
const report = {workspace, runs:[], errors:[], widths:[]};
page.on('pageerror', error=>report.errors.push(error.message));
const assert = (value, message)=>{if(!value)throw Error(message);};

async function say(text) {
  const response = page.waitForResponse(r=>r.url().endsWith('/api/chat/turns') && r.request().method()==='POST');
  await page.getByLabel('输入消息').fill(text);
  await page.getByRole('button',{name:'发送',exact:true}).click();
  const sent = await response;
  const reply = await sent.json();
  assert(sent.ok(),JSON.stringify(reply));
  const session = sent.request().postDataJSON().session;
  for(let i=0;i<180;i++) {
    const s = await (await page.request.get(origin+'/api/chat/sessions/'+session+'?user='+user)).json();
    const run = s.turns.find(r=>r.id===reply.run_id);
    if(run && run.status!=='running') {
      assert(run.status==='complete',run.error);
      report.runs.push({id:run.id,session,branches:run.result.branches.map(
        ({mode,status,answer,memory_status,params,used_refs,history_count,total_tokens,elapsed_ms,changes})=>
          ({mode,status,answer,memory_status,params,used_refs,history_count,total_tokens,elapsed_ms,changes}))});
      console.log(JSON.stringify(report.runs.at(-1)));
      assert(run.result.branches.every(b=>b.status==='complete'),JSON.stringify(run.result.branches));
      await page.getByRole('button',{name:'查看记忆与来源'}).last().waitFor();
      await page.locator('.chat-answer-pending').first().waitFor({state:'hidden'});
      return run;
    }
    await new Promise(resolve=>setTimeout(resolve,1200));
  }
  throw Error('本轮超过验收等待时间');
}

async function catalogRows(prompt) {
  const run = await say(prompt);
  assert(run.result.branches.length===2 && run.result.branches.every(b=>!b.params && b.total_tokens===0),
    '查库不应用选餐偏好，两组均使用确定的 SQL');
  const response = await page.request.get(origin+'/api/chat/runs/'+run.id+'?user='+user);
  assert(response.ok(),'查询证据接口可读');
  const details = await response.json();
  return run.result.branches.map(branch=>{
    const evidence = details.branches[branch.mode].artifacts.find(record=>record.id===branch.evidence_id);
    assert(evidence?.kind==='sql_result','每组都有本轮查询结果和来源');
    return evidence.payload.result.rows;
  });
}

try {
  await page.goto(origin+'/?view=meal&user='+workspace);
  await page.getByLabel('对话引擎').selectOption('parallel');
  const saved = await say('以后晚饭我喜欢吃辣，预算500块，热量不超过1000千卡。');
  assert(saved.result.branches.length===2 && saved.result.branches.every(b=>b.memory_status==='updated'),'两套引擎都自动形成晚饭记忆');
  const fact = await say('我家猫叫年糕。');
  assert(fact.result.branches.every(b=>b.memory_status==='updated'),'同会话继续聊天并记住事实');
  await page.getByRole('button',{name:'新会话',exact:true}).click();
  const loaded = await say('晚上吃什么好？');
  assert(loaded.result.branches.every(b=>b.history_count===0&&b.params?.budget===500&&b.params?.kcal_min===0&&b.params?.kcal_max===1000&&b.params?.min_spice===1&&b.approved.length===3),'两套引擎跨会话使用已记住条件');
  assert(loaded.result.branches.every(b=>b.total_tokens>0&&b.elapsed_ms>0),'两组真实用量');
  await page.screenshot({path:fileURLToPath(new URL('parallel.png',output))});
  await page.getByRole('button',{name:'查看记忆与来源'}).last().click();
  await page.getByRole('button',{name:'技术详情',exact:true}).click();
  await page.getByText('模型、工具与 SQL 运行轨迹',{exact:true}).waitFor();
  await page.getByRole('button',{name:'关闭',exact:true}).click();
  const menus = await catalogRows('menu_item（菜单）当中 S01 店有哪些菜品，前 3 条');
  assert(menus.every(rows=>rows.length===3 && rows.every(row=>row.shop_cd==='S01')), '门店条件与条数保留');
  const onSale = await catalogRows('S02店出售的菜品有哪些');
  assert(onSale.every(rows=>rows.length===24 && rows.every(row=>row.shop_cd==='S02')
    && !rows.some(row=>row.item_cd==='I049')), '按照给定门店返回在售菜单');
  await say('以后把S02叫做KFC');
  await page.getByRole('button',{name:'新会话',exact:true}).click();
  const aliasMenu = await catalogRows('查看KFC门店的菜单');
  const aliasSale = await catalogRows('KFC出售的菜品有哪些');
  assert(aliasMenu.every(rows=>rows.length===25 && rows.every(row=>row.shop_cd==='S02')),
    '完整菜单通过别名绑定同一门店');
  assert(JSON.stringify(aliasSale)===JSON.stringify(onSale),
    '省略门店后缀也能绑定同一门店，并保留在售条件');
  const locations = await catalogRows('清汤牛肉面和西兰花牛肉饭哪些店有卖？');
  assert(locations.every(rows=>rows.length===2 && rows.some(row=>row.dish==='清汤牛肉面')
    && rows.some(row=>row.dish==='西兰花牛肉饭')), '区分事实查询、选餐偏好和多个菜名');
  await page.getByRole('button',{name:'查看来源 1',exact:true}).last().click();
  const evidence = page.getByRole('dialog',{name:'记忆与来源'});
  await evidence.getByText('菜品所属门店',{exact:true}).waitFor();
  await evidence.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByLabel('对话引擎').selectOption('deepagents');
  const recalled = await say('我家猫叫什么？');
  assert(recalled.result.branches[0].mode==='deepagents'&&recalled.result.branches[0].answer.includes('年糕'),'Deep Agents 单独会话从文件读回事实');
  await page.reload();
  await page.getByLabel('聊天记录').getByText('我家猫叫什么？',{exact:true}).waitFor();
  await page.getByLabel('对话引擎').selectOption('parallel');
  await page.getByLabel('更多新会话选项').click();
  await page.getByRole('button',{name:'新建无记忆对照',exact:true}).click();
  const control = await say('晚上吃什么好？');
  assert(control.result.branches.every(b=>b.memory_status==='disabled'&&!b.memory_read&&b.used_refs.length===0&&b.params?.budget===120&&b.params?.max_spice===0),'无记忆对照不使用已保存偏好');
  for(let width of [1440,1024,768,390]) {
    await page.setViewportSize({width,height:900});
    await page.waitForFunction(()=>Math.abs(document.querySelector('.chat-lab').getBoundingClientRect().width-innerWidth)<2);
    const measured=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(measured.width===measured.scroll,'页面不裁切');report.widths.push(measured);
  }
  await page.screenshot({path:fileURLToPath(new URL('mobile.png',output))});
  await page.setViewportSize({width:1440,height:900});
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Emulation.setPageScaleFactor',{pageScaleFactor:1.5});
  await page.waitForFunction(()=>Math.abs(document.querySelector('.chat-lab').getBoundingClientRect().width-visualViewport.width)<2);
  assert(await page.evaluate(()=>document.querySelector('.chat-composer button').getBoundingClientRect().right<=visualViewport.width+1),'放大时发送按钮留在可见范围');
  report.zoom=true;
  assert(report.errors.length===0,'无浏览器错误');
  report.complete=true;
} catch(error) {
  report.failure=error.stack;
  throw error;
} finally {
  await writeFile(new URL('report.json',output),JSON.stringify(report,null,2));
  await browser.close();
}
