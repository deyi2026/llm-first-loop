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
                    if "exceptionDetails" in r.get("result",{}): return "ERR:"+json.dumps(r["result"]["exceptionDetails"],ensure_ascii=False)[:300]
                    return r.get("result",{}).get("result",{}).get("value")
        print("URL:", await ev("location.href"))
        print("ED:", await ev("!!document.querySelector('.public-DraftEditor-content')"))
        print("IMGS:", await ev("document.querySelectorAll('.public-DraftEditor-content img').length"))
        print("BLOCKS:", await ev("document.querySelectorAll('.public-DraftEditor-content [data-block=true]').length"))
        print("TAIL:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          const bl=[...ed.querySelectorAll('[data-block=true]')];
          return JSON.stringify(bl.slice(-3).map(d=>d.tagName+'|'+(d.innerText||'').replace(/\\s+/g,' ').slice(0,18)+'|img='+!!d.querySelector('img')));})()"""))
asyncio.run(main())
