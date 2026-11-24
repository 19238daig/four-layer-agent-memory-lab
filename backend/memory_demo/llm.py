import json
import os
import time
import re
import httpx
from openai import OpenAI
from .config import BASE_URL, MODEL, MODEL_EXTRA_BODY


def safe_error(exc):
    text=str(exc)
    key=os.getenv('OPENAI_API_KEY','')
    if key:
        text=text.replace(key,'[REDACTED]')
    text=re.sub(r'sk-[A-Za-z0-9_\\-]+','[REDACTED]',text)
    return text[:1200]


def parse_json(text):
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start,end=text.find('{'),text.rfind('}')
        if start>=0 and end>start:
            return json.loads(text[start:end+1])
        raise ValueError('模型未返回有效 JSON，请重试；原始响应已保留在运行详情。')


class Model:
    def __init__(self,store,run_id):
        self.store,self.run_id=store,run_id

    def call(self,system,prompt,*,json_mode=False,purpose='回答',max_tokens=6000):
        messages=[dict(role='system',content=system),dict(role='user',content=prompt)]
        self.store.event(self.run_id,'model_request',dict(purpose=purpose,model=MODEL,messages=messages,
                         max_tokens=max_tokens,extra_body=MODEL_EXTRA_BODY))
        start=time.perf_counter()
        client=OpenAI(base_url=BASE_URL,api_key=os.getenv('OPENAI_API_KEY'),timeout=90,max_retries=1,
                      http_client=httpx.Client(trust_env=False))
        kwargs=dict(model=MODEL,messages=messages,max_tokens=max_tokens,temperature=0.1,extra_body=MODEL_EXTRA_BODY)
        if json_mode:
            kwargs['response_format']={'type':'json_object'}
        try:
            result=client.chat.completions.create(**kwargs)
        finally:
            client.close()
        content=result.choices[0].message.content or ''
        usage=result.usage.model_dump() if result.usage else None
        self.store.event(self.run_id,'model_response',dict(purpose=purpose,model=MODEL,content=content,
                         usage=usage,finish_reason=result.choices[0].finish_reason,elapsed_ms=round((time.perf_counter()-start)*1000)))
        if result.choices[0].finish_reason=='length':
            raise ValueError('模型达到输出 token 上限，返回内容不完整。请增加输出预算后重试，或更换模型。')
        return parse_json(content) if json_mode else content
