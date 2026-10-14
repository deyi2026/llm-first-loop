import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "toutiao.com" in t.get("url","") and "mp.toutiao" not in t.get("url",""): return t
async def main():
    pg=page()
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def cmd(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),90))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR"
            return r.get("result",{}).get("value")
        await cmd("Page.bringToFront",{})
        await cmd("Page.navigate",{"url":"https://www.toutiao.com/article/7696133427334070825/"})
        await asyncio.sleep(12)
        for k in range(14):
            await ev("window.scrollBy(0, 900)"); await asyncio.sleep(1.1)
        await asyncio.sleep(4)
        print("URL:", await ev("location.href"))
        print("IMGS:", await ev(r"""(()=>{const im=[...document.querySelectorAll('article img, .article-content img, img')];
          const art=im.filter(x=>x.naturalWidth>20||/tos-|p3-/i.test(x.src||''));
          return JSON.stringify({total:im.length, real:art.length,
            list:art.map(x=>(x.naturalWidth+'x'+x.naturalHeight)+' '+(x.src||x.getAttribute('data-src')||'').slice(0,64)),
            capt:[...document.querySelectorAll('p')].map(p=>p.innerText||'').filter(x=>/^分权：|^自主演进的三道锁/.test(x)).slice(0,4)});})()"""))
        print("TITLE:", await ev("(document.querySelector('h1')||{}).innerText||document.title"))
        print("WORDS:", await ev(r"""(()=>{const t=document.body.innerText.replace(/\s+/g,' ');
          const m=t.match(/字数[：:]\s*\d+/); return m?m[0]:'none';})()"""))
asyncio.run(main())
