import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "toutiao.com/article/7696133427334070825" in t.get("url","")]
async def main():
    ts=tg()
    if not ts: print("NO_PAGE"); return
    t=ts[0]
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
        r=await ev("""(()=>{const t=document.body.innerText.replace(/\\s+/g,' ');
          const art=document.querySelector('article')||document.querySelector('#article-content')||document.body;
          const imgs=[...art.querySelectorAll('img')].map(x=>(x.src||'').slice(0,60));
          return JSON.stringify({url:location.href, title:(document.title||'').slice(0,60),
            chars:t.length, hasTitle:t.includes('把程序从大脑降级为手脚'),
            hasBody:t.includes('程序越笨')&&t.includes('不能塞进 if 分支'),
            hasFooter:t.includes('未经人工事实核验'),
            hasLock:t.includes('自主演进')&&t.includes('钥匙在人手里'),
            imgs, status:/审核中|内容审核|暂不可见|已发布/.exec(t)?.[0]||null});})()""")
        print(r)
asyncio.run(main())
