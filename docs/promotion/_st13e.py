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
        print("TAGS:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const m={}; [...pm.children].forEach(n=>{m[n.tagName]=(m[n.tagName]||0)+1;}); return JSON.stringify(m);})()"""))
        print("SEC:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const s=[...pm.children].filter(n=>/^[一二三四五六]、/.test(n.innerText||''));
          return JSON.stringify(s.map(n=>n.tagName+'|fs='+getComputedStyle(n).fontSize+'|'+(n.innerText||'').slice(0,25)));})()"""))
        print("IMGS:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          return JSON.stringify([...pm.querySelectorAll('img')].map(i=>({vis:i.offsetParent!==null,w:i.naturalWidth,src:(i.src||'').slice(-30),par:i.closest('figure,p')?.tagName})));})()"""))
asyncio.run(main())
