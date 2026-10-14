import asyncio, json, urllib.request, base64, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m_,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m_,"params":p or {}}))
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
        print("CLICK:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='预览并发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(6)
        print("URL:", await ev("location.href"))
        print("DIALOG_INPUTS:", await ev("""JSON.stringify([...document.querySelectorAll('input,textarea')].map((x,k)=>({k,
          ph:(x.placeholder||'').slice(0,20), val:(x.value||'').slice(0,24), type:x.type,
          cls:(x.className||'').slice(0,34), vis:!!(x.offsetParent||x.getClientRects().length)})).filter(o=>o.vis&&(o.k>3||o.ph)))"""))
        print("DIALOG_BTNS:", await ev("""JSON.stringify([...document.querySelectorAll('button')].map(b=>({txt:(b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,14),
          dis:b.disabled, cls:(b.className||'').slice(0,34), vis:!!(b.offsetParent||b.getClientRects().length)})).filter(o=>o.vis&&o.txt))"""))
        print("DIALOG_TEXT:", await ev("""(()=>{const dlgs=[...document.querySelectorAll('[class*=modal],[class*=dialog],[class*=popover]')].filter(d=>d.offsetParent||d.getClientRects().length);
          return JSON.stringify(dlgs.slice(0,4).map(d=>(d.innerText||'').replace(/\\s+/g,' ').slice(0,200)));})()"""))
        s=await cmd("Page.captureScreenshot",{"format":"png"})
        if "data" in s: open("/tmp/d14_pubdlg.png","wb").write(base64.b64decode(s["data"])); print("SHOT: /tmp/d14_pubdlg.png")
asyncio.run(main())
