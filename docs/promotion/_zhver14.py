import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
JS=r"""(async()=>{
 const r=await fetch('https://zhuanlan.zhihu.com/p/2093444801823760655',{credentials:'include'});
 const h=await r.text(); const d=new DOMParser().parseFromString(h,'text/html');
 const art=d.querySelector('article')||d.body; const t=art.innerText||'';
 const im=[...art.querySelectorAll('img')].map(x=>(x.src||'').slice(0,70));
 return JSON.stringify({status:r.status, title:(d.querySelector('h1')||{}).innerText||'',
  chars:t.replace(/\s/g,'').length, p:art.querySelectorAll('p').length, h1:art.querySelectorAll('h1').length,
  h2:art.querySelectorAll('h2').length, imgs:im.filter(s=>s.indexOf('zhimg')>=0||s.indexOf('pic')>=0).length, imsample:im.slice(0,4),
  hasTitle:t.includes('把程序从大脑')||t.includes('程序从大脑'), hasPower:t.includes('分权：哪些判断程序绝不接手'),
  hasLocks:t.includes('自主演进的三道锁'), hasFooter:t.includes('未经人工事实核验'),
  hasB3:t.includes('不对这个数字背书'), hasP0:t.includes('P0*'), hasPristine:t.includes('本节这张表的优先级'),
  wordCount:(t.match(/字数[：:]\s*\d+/)||['none'])[0], tail:t.replace(/\s+/g,' ').slice(-90)});})()"""
async def main():
    pg=page("zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":JS,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(await ws.recv())
            if r.get("id")==1:
                res=r.get("result",{})
                if "exceptionDetails" in res: print("ERR:", json.dumps(res["exceptionDetails"],ensure_ascii=False)[:300])
                else: print(res.get("result",{}).get("value"))
                return
asyncio.run(main())
