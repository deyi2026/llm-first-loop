import asyncio, json, urllib.request, base64, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m_,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m_,"params":p or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: return {"ERR":m["error"]}
                    return m.get("result",{})
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "ERR" in r: return "CDPERR:"+str(r["ERR"])
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        GATE="""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const im=[...new Set([...document.querySelectorAll('.ProseMirror img')].filter(x=>x.naturalWidth>0&&!x.closest('template')).map(x=>x.src))];
          const labs=[...document.querySelectorAll('label.byte-checkbox')].map(l=>(l.innerText||'').trim()+':'+((l.querySelector('input')||{}).checked?'ON':'OFF'));
          const cov=document.querySelector('.article-cover-img-wrap img');
          return JSON.stringify({title:ti.value, titleLen:ti.value.length, words:wc?wc[1]:null,
            uniqImgs:im.length, caps:[...document.querySelectorAll('textarea.pgc-img-caption-ipt')].map(t=>t.value.length),
            coverW:cov?cov.naturalWidth:0, emptyH1:[...pm.querySelectorAll('h1')].filter(h=>!h.textContent.trim()).length,
            aiDecl:labs.filter(x=>x.startsWith('引用AI')), words_ok:(wc?+wc[1]:0)>=1500});})()"""
        print("PRE-GATE:", await ev(GATE))
        print("CLICK1:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='预览并发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(6)
        print("DIALOG:", await ev("""JSON.stringify([...document.querySelectorAll('button')].filter(b=>(b.offsetParent||b.getClientRects().length)).map(b=>(b.innerText||'').trim()+'|'+b.disabled).filter(x=>x!='|'))"""))
        print("CLICK2:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='确认发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(10)
        print("URL:", await ev("location.href"))
        print("TOAST:", await ev("""(()=>{const t=[...document.querySelectorAll('[class*=toast],[class*=message],[class*=notice]')].filter(x=>(x.offsetParent||x.getClientRects().length)).map(x=>(x.innerText||'').replace(/\\s+/g,' ').slice(0,80)).filter(Boolean);
          return JSON.stringify(t.slice(0,5));})()"""))
        s=await cmd("Page.captureScreenshot",{"format":"png"})
        if "data" in s: open("/tmp/d14_after.png","wb").write(base64.b64decode(s["data"])); print("SHOT: /tmp/d14_after.png")
asyncio.run(main())
