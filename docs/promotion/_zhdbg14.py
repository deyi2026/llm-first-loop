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
                    if "exceptionDetails" in r.get("result",{}): return "ERR:"+json.dumps(r["result"]["exceptionDetails"],ensure_ascii=False)[:200]
                    return r.get("result",{}).get("result",{}).get("value")
        print("H2S:", await ev(r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          const bl=[...ed.querySelectorAll('[data-block=true]')];
          const out=[];
          bl.forEach(function(d,n){ if(d.tagName==='H2') out.push(n+':['+(d.innerText||'').slice(0,22)+'] prev='+bl[n-1].tagName+':'+(bl[n-1].innerText||'').replace(/\s+/g,' ').slice(0,20)+' hasTextNode='+(function(){const w=document.createTreeWalker(bl[n-1],NodeFilter.SHOW_TEXT);let c=0;while(w.nextNode())c++;return c;})()); });
          return JSON.stringify(out);})()"""))
asyncio.run(main())
