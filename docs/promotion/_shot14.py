import asyncio, json, urllib.request, base64, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "mp.toutiao.com/profile_v4/graphic" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m_,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m_,"params":p or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            return r.get("result",{}).get("result",{}).get("value")
        await asyncio.sleep(2)
        print("URL:", await ev("location.href"))
        print("TEXTSNIP:", await ev("""(()=>{const t=document.body.innerText.replace(/\\s+/g,' ');
          const i=t.indexOf('把程序'); return i>=0? t.slice(Math.max(0,i-120), i+160) : t.slice(0,300);})()"""))
        s=await cmd("Page.captureScreenshot",{"format":"png","captureBeyondViewport":False})
        if "data" in s: open("/tmp/d14_list.png","wb").write(base64.b64decode(s["data"])); print("SHOT: /tmp/d14_list.png")
asyncio.run(main())
