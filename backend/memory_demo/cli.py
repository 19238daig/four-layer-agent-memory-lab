import argparse
import json
import sys
import time
import httpx
from .config import API_URL


def main():
    if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Memory Lab 日常记忆演示命令')
    p.add_argument('action',choices=['record','distill','dream','context','ask','compare','replay','status'])
    p.add_argument('--user',default='demo')
    p.add_argument('--session',default='day1')
    p.add_argument('--text',default='')
    p.add_argument('--scenario',default='lunch',choices=['lunch'])
    p.add_argument('--preview',action='store_true',help='context 始终仅预览，不调用模型')
    p.add_argument('--source-run',default='')
    p.add_argument('--no-wait',action='store_true')
    p.add_argument('--url',default=API_URL)
    args=p.parse_args()
    try:
        with httpx.Client(base_url=args.url,timeout=15,trust_env=False) as client:
            if args.action=='status':
                r=client.get('/api/state',params={'user':args.user});r.raise_for_status()
                s=r.json()
                print(json.dumps(dict(objects=len(s['objects']),sessions=s['sessions'],latest_runs=s['runs'][:5]),ensure_ascii=False,indent=2))
                return
            data={k:getattr(args,k) for k in ['action','user','session','text','scenario','source_run']}
            r=client.post('/api/operations',json=data);r.raise_for_status()
            run=r.json()['run_id']
            print(f'运行：{run}\n页面：{args.url}/?run={run}&user={args.user}',flush=True)
            if args.no_wait: return
            seen=set()
            while True:
                response=client.get('/api/runs/'+run,params={'user':args.user});response.raise_for_status()
                result=response.json()
                for e in result['events']:
                    if e['seq'] in seen: continue
                    seen.add(e['seq'])
                    if e['type']=='step': print('  '+e['data']['title'],flush=True)
                    if e['type']=='model_request': print('  模型处理中：'+e['data']['purpose'],flush=True)
                    if e['type']=='comparison_result': print('  对比分支：'+e['data']['mode']+' / '+e['data']['status'],flush=True)
                if result['status']!='running':
                    if result['status']=='failed':
                        print('执行失败：'+result['error'],file=sys.stderr);sys.exit(1)
                    print(json.dumps(result['result'],ensure_ascii=False,indent=2))
                    return
                time.sleep(0.8)
    except httpx.ConnectError:
        print('无法连接后端，请先运行 .\\scripts\\start.ps1。',file=sys.stderr);sys.exit(1)
    except httpx.HTTPStatusError as exc:
        print('请求失败：'+exc.response.text,file=sys.stderr);sys.exit(1)


if __name__=='__main__': main()
