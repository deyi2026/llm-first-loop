import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "toutiao.com" in t.get("url","") and "mp.toutiao" not in t.get("url",""): return t
    return None
JS=r"""(async()=>{
 const r=await fetch('https://www.toutiao.com/article/7696133427334070825/',{credentials:'include',redirect:'follow'});
 const h=await r.text(); const d=new DOMParser().parseFromString(h,'text/html');
 const art=d.querySelector('article')||d.body; const t=art.innerText||'';
 return JSON.stringify({status:r.status, finalUrl:r.url, chars:t.replace(/\s/g,'').length,
  imgs:[...art.querySelectorAll('img')].map(x=>(x.src||'').slice(0,60)).slice(0,6),
  h1:(d.querySelector('h1')||{}).innerText||'', hasBody:t.includes('不能塞进 if 分支'),
  hasFooter:t.includes('未经人工事实核验'), head:t.replace(/\s+/g,' ').slice(0,120)});})()"""
async def main():
    pg=page()
    if not pg: print("NO_PAGE"); return
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":JS,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(await ws.recv())
            if r.get("id")==1:
                res=r.get("result",{})
                print(json.dumps(res.get("exceptionDetails"),ensure_ascii=False)[:200] if "exceptionDetails" in res else res.get("result",{}).get("value"))
                return
asyncio.run(main())
