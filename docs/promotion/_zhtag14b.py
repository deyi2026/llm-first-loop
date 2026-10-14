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
        r=await ev("""(()=>{const i=[...document.querySelectorAll('input')].find(x=>(x.placeholder||'').includes('搜索话题'));
          if(!i) return 'NO_INPUT'; i.focus(); const b=i.getBoundingClientRect();
          return JSON.stringify({x:Math.round(b.left+40),y:Math.round(b.top+b.height/2)});})()""")
        print("RECT:", r)
        z=json.loads(r)
        for ty in ("mouseMoved","mousePressed","mouseReleased"):
            await s("Input.dispatchMouseEvent",{"type":ty,"x":z["x"],"y":z["y"],"button":"left","clickCount":1})
            await asyncio.sleep(0.25)
        await s("Input.insertText",{"text":"开源"}); await asyncio.sleep(4)
        print("OPTIONS:", await ev(r"""(()=>{const c=[...document.querySelectorAll('div,li,a')].filter(function(x){
            return (x.offsetParent||x.getClientRects().length)&&/话题/.test(x.innerText||'')&&(x.innerText||'').length<80;});
          return JSON.stringify(c.slice(0,8).map(function(x){return (x.innerText||'').replace(/\s+/g,' ').slice(0,50)+' @'+(x.className||'').slice(0,24);}));})()"""))
asyncio.run(main())
