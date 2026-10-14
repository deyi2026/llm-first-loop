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
        async def key(k,vk):
            b={"key":k,"code":k,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk}
            await s("Input.dispatchKeyEvent",dict(b,type="keyDown")); await asyncio.sleep(0.06)
            await s("Input.dispatchKeyEvent",dict(b,type="keyUp"))
        await s("Page.bringToFront",{})
        print("FOCUS:", await ev("""(()=>{const i=[...document.querySelectorAll('input')].find(x=>(x.placeholder||'').includes('搜索话题'));
          if(!i) return 'NO'; i.focus(); return 'FOCUSED:'+i.value;})()"""))
        await s("Input.insertText",{"text":"AI Agent"}); await asyncio.sleep(4)
        print("VAL:", await ev("""(()=>{const i=[...document.querySelectorAll('input')].find(x=>(x.placeholder||'').includes('搜索话题'));return i?i.value:'NO';})()"""))
        print("RESULTS:", await ev(r"""(()=>{const c=[...document.querySelectorAll('div')].filter(function(x){
            const t=(x.innerText||'').replace(/\s+/g,' ').trim();
            return (x.offsetParent||x.getClientRects().length)&&t&&t.length<60&&/话题|关注|粉丝|简介/.test(t)&&x.children.length<6;});
          return JSON.stringify([...new Set(c.map(function(x){return (x.innerText||'').replace(/\s+/g,' ').trim();}))].slice(0,10));})()"""))
asyncio.run(main())
