import {chromium} from 'playwright-core';
import {mkdir, writeFile} from 'node:fs/promises';

const origin = process.env.CHAT_CHECK_URL || 'http://127.0.0.1:8010';
const workspace = 'qa-heat-'+Date.now().toString(36);
const user = 'meal-'+workspace;
const dir = new URL('../artifacts/chat-heat/'+workspace+'/',import.meta.url);
await mkdir(dir,{recursive:true});
const browser = await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport:{width:1440,height:900},reducedMotion:'reduce'});
const report = {workspace,runs:[],errors:[]};
page.on('pageerror',e=>report.errors.push(e.message));
const assert = (ok,reason)=>{if(!ok)throw Error(reason);};

async function say(text) {
  const submitted = page.waitForResponse(r=>r.url().endsWith('/api/chat/turns')&&r.request().method()==='POST');
  await page.getByLabel('输入消息').fill(text);
  await page.getByRole('button',{name:'发送',exact:true}).click();
  const response = await submitted;
  const {session} = response.request().postDataJSON();
  const {run_id} = await response.json();
  assert(response.ok(), '提交失败');
  for(let i=0;i<210;i++) {
    const data = await (await page.request.get(origin+'/api/chat/sessions/'+session+'?user='+user)).json();
    const run = data.turns.find(item=>item.id===run_id);
    if(run?.status==='complete') {
      await page.locator('.chat-answer-pending').first().waitFor({state:'hidden'});
      report.runs.push({id:run_id,session,branches:run.result.branches.map(b=>({mode:b.mode,status:b.status,params:b.params,changes:b.changes,approved:b.approved,answer:b.answer}))});
      assert(run.result.branches.length===2&&run.result.branches.every(b=>b.status==='complete'),'两组都完成');
      console.log(run_id+' '+session+' complete');
      return report.runs.at(-1);
    }
    if(run?.status==='failed')throw Error(run.error);
    await new Promise(resolve=>setTimeout(resolve,900));
  }
  throw Error('等待会话超时');
}

try {
  await page.goto(origin+'/?view=meal&user='+workspace);
  await page.getByLabel('对话引擎').selectOption('parallel');
  const first = await say('以后晚饭我喜欢吃辣，预算200块，热量不超过400千卡。');
  assert(first.branches.every(b=>b.changes.some(c=>c.key==='meal:dinner:kcal_max'&&c.value===400)),'初始上限保存');
  await page.getByRole('button',{name:'新会话',exact:true}).click();
  const updated = await say('以后晚饭我喜欢吃辣，预算1000块，热量超过500千卡。');
  for(const b of updated.branches) {
    assert(b.changes.some(c=>c.key==='meal:dinner:kcal_min'&&c.value===500),'严格下限保存');
    assert(b.changes.some(c=>c.key==='meal:dinner:kcal_min_exclusive'&&c.value===1),'端点规则保存');
    assert(b.changes.some(c=>c.key==='meal:dinner:kcal_max'&&c.value===null),'旧上限清除');
  }
  const deletedUrl = origin+'/api/chat/sessions/'+updated.session+'?user='+user;
  const inaccessible = await page.request.delete(origin+'/api/chat/sessions/'+updated.session+'?user=other');
  assert(inaccessible.status()===404,'其他空间不可删除');
  await page.locator('.chat-session-row:has([aria-current=page]) .chat-session-delete').click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  assert((await page.request.get(deletedUrl)).ok(),'取消保持原对话');
  await page.locator('.chat-session-row:has([aria-current=page]) .chat-session-delete').click();
  const deleted = page.waitForResponse(r=>r.request().method()==='DELETE'&&r.url()===deletedUrl);
  await page.getByRole('button',{name:'删除对话',exact:true}).click();
  assert((await deleted).ok(),'删除成功');
  await page.locator('.chat-delete-dialog').waitFor({state:'hidden'});
  assert((await page.request.get(deletedUrl)).status()===404,'删除后不能继续打开');
  await page.reload();
  await page.locator('.chat-session-row').first().waitFor();
  assert(await page.locator('.chat-session-row').count()===1,'刷新后不会恢复已删除对话');
  await page.getByLabel('对话引擎').selectOption('parallel');
  const result = await say('晚上吃什么？');
  for(const b of result.branches) {
    assert(b.params?.budget===1000&&b.params.kcal_min===500&&b.params.kcal_min_exclusive===1&&b.params.kcal_max===10000,
      '实际参数使用1000与严格下限500且不恢复旧400');
    assert(b.approved?.length>0&&b.approved.every(offer=>offer.kcal_lo>500&&offer.hot_lv>0),'真实核验菜品');
  }
  assert(await page.locator('.chat-query-line').filter({hasText:'>500千卡'}).count()===2,'两组界面显示严格下限');
  await page.locator('.chat-answer-footer button').first().click();
  await page.locator('.evidence-source-link').filter({hasText:'超过500千卡'}).waitFor();
  assert(!report.errors.length,'没有浏览器错误');
  report.complete = true;
} catch(error) {
  report.failure = error.stack;
  throw error;
} finally {
  await writeFile(new URL('report.json',dir),JSON.stringify(report,null,2));
  await browser.close();
}
