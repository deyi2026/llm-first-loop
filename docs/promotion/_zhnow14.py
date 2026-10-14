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
        print("URL:", await ev("location.href"))
        print("TITLE:", await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');return t?t.value.slice(0,60):'NONE';})()"""))
        print("BODY:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          if(!ed) return 'NO_ED';
          const im=[...ed.querySelectorAll('img')];
          return JSON.stringify({len:ed.innerText.replace(/\\s/g,'').length, imgs:im.length,
            h2:ed.querySelectorAll('h2').length, head:ed.innerText.replace(/\\s+/g,' ').slice(0,80),
            hasPower:ed.innerText.includes('分权：哪些判断程序绝不接手')});})()"""))
        print("CAPTION_PS:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          if(!ed) return 'NO_ED';
          return JSON.stringify([...ed.querySelectorAll('p')].map((p,n)=>n+':'+(p.textContent||'').slice(0,20)).filter(x=>/分权|三道锁/.test(x)));})()"""))
asyncio.run(main())
