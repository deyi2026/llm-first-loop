import asyncio, json, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method,params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: return {"ERR":m["error"]}
                    return m.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "ERR" in r: return "CDPERR:"+str(r["ERR"])
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        # 1) open dialog
        print("BTN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(4)
        print("FILE_INPUTS:", await ev("""JSON.stringify([...document.querySelectorAll('input[type=file]')].map((f,k)=>({k,
          accept:f.accept, cls:f.className, vis:!!(f.offsetParent||f.getClientRects().length),
          parent:(f.parentElement&&f.parentElement.className||'').slice(0,40)})))"""))
        print("DIALOG_TEXT:", await ev("""(()=>{const d=[...document.querySelectorAll('div')].filter(x=>x.className&&String(x.className).includes('modal'));
          return d.length? d.map(x=>x.innerText.replace(/\\s+/g,' ').slice(0,120)).join(' || ') : 'NO_MODAL';})()"""))
        shot=await cmd("Page.captureScreenshot",{"format":"png"})
        import base64
        if "data" in shot: open("/tmp/d14_dialog.png","wb").write(base64.b64decode(shot["data"])); print("SHOT: /tmp/d14_dialog.png")
asyncio.run(main())
