import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
async def main():
    pg=page("zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def s(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),90))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await s("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+json.dumps(r["exceptionDetails"],ensure_ascii=False)[:200]
            return r.get("result",{}).get("value")
        await s("Page.bringToFront",{})
        await s("Page.navigate",{"url":"https://zhuanlan.zhihu.com/p/2093444801823760655/edit"}); await asyncio.sleep(9)
        print("URL:", await ev("location.href"))
        print("CLICK_TOPIC:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='添加话题');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(3)
        print("TOPIC_INPUTS:", await ev(r"""JSON.stringify([...document.querySelectorAll('input')].map((x,k)=>({k,ph:(x.placeholder||'').slice(0,18),
          val:(x.value||'').slice(0,16), cls:(x.className||'').slice(0,28), vis:!!(x.offsetParent||x.getClientRects().length)})).filter(o=>o.vis))"""))
        print("DROPDOWN:", await ev(r"""(()=>{const d=[...document.querySelectorAll('[class*=Popper],[class*=Dropdown],[class*=search-result]')].filter(x=>x.offsetParent||x.getClientRects().length);
          return JSON.stringify(d.slice(0,3).map(x=>(x.innerText||'').replace(/\s+/g,' ').slice(0,120)));})()"""))
asyncio.run(main())
