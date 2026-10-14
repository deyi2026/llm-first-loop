import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "toutiao.com" in t.get("url","") and "mp.toutiao" not in t.get("url",""): return t
JS=r"""(async()=>{
 const r=await fetch('https://www.toutiao.com/article/7696133427334070825/',{credentials:'include'});
 const h=await r.text(); const d=new DOMParser().parseFromString(h,'text/html');
 const art=d.querySelector('article')||d.body; const t=art.innerText||'';
 const imgs=[...art.querySelectorAll('img')].map(function(x){return {s:(x.getAttribute('src')||x.getAttribute('data-src')||'').slice(0,72), w:x.getAttribute('width'), h:x.getAttribute('height')};});
 return JSON.stringify({imgs:imgs, pCount:art.querySelectorAll('p').length,
  heads:(t.match(/(开场：一个让工程师难受的设计|一、先说清楚|二、五步循环|三、反直觉的核心|四、它敢让自己改自己|五、诚实的边界|六、未来趋势判断|七、需要攻克的技术方向|八、现在该怎么看它)/g)||[]),
  checks:{'3.3 图注':t.includes('分权：哪些判断程序绝不接手'),'4 节图注':t.includes('自主演进的三道锁'),
   'B3 背书说明':t.includes('不对这个数字背书'),'B2 P0*':t.includes('P0*'),'观点标注':t.includes('因果解读'),
   'AI 声明':t.includes('未经人工事实核验'),'复算命令':t.includes('git rev-list --count HEAD')},
  chars:t.replace(/\s/g,'').length});})()"""
async def main():
    pg=page()
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":JS,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(await ws.recv())
            if r.get("id")==1:
                res=r.get("result",{})
                print(json.dumps(res.get("exceptionDetails"),ensure_ascii=False)[:200] if "exceptionDetails" in res else res.get("result",{}).get("value"))
                return
asyncio.run(main())
