import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
async def main():
    pg=page("zhuanlan.zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                r=json.loads(await ws.recv())
                if r.get("id")==i[0]:
                    if "exceptionDetails" in r.get("result",{}): return "ERR:"+str(r["result"]["exceptionDetails"].get("text"))
                    return r.get("result",{}).get("result",{}).get("value")
        print("BLOCKS:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          const bl=[...ed.querySelectorAll('[data-block=true]')];
          const out=bl.map((d,n)=>n+':'+d.tagName+':'+(d.innerText||'').replace(/\\s+/g,' ').slice(0,18));
          return JSON.stringify({total:bl.length, cap:out.filter(x=>/分权|三道锁|看明白|第 3 条/.test(x))});})()"""))
asyncio.run(main())
