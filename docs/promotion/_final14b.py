import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def find(pred):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and pred(t.get("url","")): return t
async def run(pg, js):
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":js,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(await asyncio.wait_for(ws.recv(),90))
            if r.get("id")==1:
                res=r.get("result",{})
                if "exceptionDetails" in res: return "ERR:"+json.dumps(res["exceptionDetails"],ensure_ascii=False)[:200]
                return res.get("result",{}).get("value")
MK=r"""(async()=>{const r=await fetch(%s,{credentials:'include'});
 const h=await r.text(); const d=new DOMParser().parseFromString(h,'text/html');
 const art=d.querySelector('article')||d.body; const t=art.innerText||'';
 const heads=(t.match(/(开场：一个让工程师难受的设计|一、先说清楚|二、五步循环|三、反直觉的核心|四、它敢让自己改自己|五、诚实的边界|六、未来趋势判断|七、需要攻克的技术方向|八、现在该怎么看它)/g)||[]).length;
 const o={status:r.status,title:(d.querySelector('h1')||{}).innerText||'',chars:t.replace(/\s/g,'').length,heads:heads,
  cap1:t.includes('分权：哪些判断程序绝不接手'),cap2:t.includes('自主演进的三道锁'),b3:t.includes('不对这个数字背书'),
  p0:t.includes('P0*'),ai:t.includes('未经人工事实核验'),imgs:art.querySelectorAll('img').length};
 o.verdict=(o.status===200&&o.heads>=9&&o.cap1&&o.cap2&&o.b3&&o.p0&&o.ai)?'PASS':'FAIL'; return JSON.stringify(o);})()"""
async def main():
    tt=find(lambda u:"toutiao.com" in u and "mp.toutiao" not in u)
    zh=find(lambda u:"zhihu.com" in u)
    print("TOUTIAO:", await run(tt, MK % json.dumps("https://www.toutiao.com/article/7696133427334070825/")))
    print("ZHIHU:  ", await run(zh, MK % json.dumps("https://zhuanlan.zhihu.com/p/2093444801823760655")))
asyncio.run(main())
