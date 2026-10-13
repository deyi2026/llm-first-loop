import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    async with websockets.connect(pages()[0]["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    r=m.get("result",{})
                    if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
                    return r.get("result",{}).get("value")
        print("DIVOUT:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ch=[...pm.children].find(c=>c.querySelector&&c.querySelector('img'));
          return ch.outerHTML.slice(0,700);})()"""))
        print("RECT:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ch=[...pm.children].find(c=>c.querySelector&&c.querySelector('img'));
          const r=ch.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
            scrollY:window.scrollY, inView: r.top>0 && r.bottom<window.innerHeight, innerH:window.innerHeight});})()"""))
asyncio.run(main())
