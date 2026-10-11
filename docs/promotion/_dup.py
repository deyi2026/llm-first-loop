import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "toutiao" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        # 全页文本，找所有"程序不是大脑"出现次数
        print("COUNT:", await ev("""(()=>{const t=document.body.innerText;
          const m=t.match(/程序不是大脑/g); return m?m.length:0;})()"""))
        print("TABS:", await ev("""JSON.stringify([...document.querySelectorAll('[class*=tab]')].map(e=>e.innerText.trim()).filter(Boolean).slice(0,10))"""))
        # 抓所有含标题的行
        print("ROWS:", await ev("""(()=>{const out=[];
          document.querySelectorAll('*').forEach(e=>{
            if(e.children.length===0 && /程序不是大脑|改进了一下|记住了自己/.test(e.textContent||'')){
              let p=e, hops=0; while(p&&hops<6&&!p.innerText.includes('展现')){p=p.parentElement;hops++;}
              const txt=(p?p.innerText:'').replace(/\\n+/g,' | ').slice(0,200);
              if(txt&&!out.includes(txt)) out.push(txt);
            }});
          return JSON.stringify(out.slice(0,6),null,1);})()"""))
asyncio.run(main())
