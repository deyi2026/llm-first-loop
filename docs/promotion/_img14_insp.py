import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "exceptionDetails" in m.get("result",{}): return "ERR:"+str(m["result"]["exceptionDetails"].get("text"))
                    return m.get("result",{}).get("result",{}).get("value")
        print("BLOCK_DUMP:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const blocks=[...pm.children]; const out=[];
          blocks.forEach((n,k)=>{ if(n.querySelector&&n.querySelector('img')) out.push({k, html:n.outerHTML.slice(0,420)}); });
          return JSON.stringify(out);})()"""))
        print("SEQ:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const blocks=[...pm.children];
          return JSON.stringify(blocks.map((n,k)=>k+':'+(n.tagName+':'+(n.innerText||'').replace(/\\s+/g,' ').slice(0,24)+(n.querySelector('img')?'[IMG]':''))).filter(x=>x.includes('IMG')||true).slice(0,0));})()"""))
        print("AROUND2:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const blocks=[...pm.children];
          const idxs=blocks.map((n,k)=>n.querySelector&&n.querySelector('img')?k:-1).filter(k=>k>=0);
          return JSON.stringify(idxs.map(k=>blocks.slice(Math.max(0,k-2),k+3).map((n,j)=>(k-2+j)+':'+n.tagName+':'+(n.innerText||'').replace(/\\s+/g,' ').slice(0,18)+(n.querySelector('img')?'[IMG]':''))));})()"""))
asyncio.run(main())
