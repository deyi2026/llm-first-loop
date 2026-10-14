import asyncio, json, base64, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
BTNS=r"""(()=>{const out=[];
 document.querySelectorAll('button,a[class*=Button],div[class*=Publish] button').forEach(function(b){
  const t=(b.innerText||'').replace(/\s+/g,' ').trim();
  if(t&&t.length<20&&(b.offsetParent||b.getClientRects().length)) out.push(t+'|dis='+b.disabled+'|'+((b.className||'').slice(0,28)));});
 return JSON.stringify([...new Set(out)]);})()"""
async def main():
    pg=page("zhuanlan.zhihu.com")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def s(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),90))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await s("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+json.dumps(r["exceptionDetails"],ensure_ascii=False)[:200]
            return r.get("result",{}).get("value")
        print("BTNS_BEFORE:", await ev(BTNS))
        print("CLICK1:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(5)
        print("URL:", await ev("location.href"))
        print("BTNS_DLG:", await ev(BTNS))
        print("DLG_TEXT:", await ev(r"""(()=>{const d=[...document.querySelectorAll('div')].filter(function(x){
            return (x.offsetParent||x.getClientRects().length)&&/发布设置|发布知乎|定时发布|最终发布/.test(x.innerText||'')&&x.innerText.length<400;});
          return JSON.stringify(d.slice(0,3).map(function(x){return (x.innerText||'').replace(/\s+/g,' ').slice(0,200);}));})()"""))
        s=await s("Page.captureScreenshot",{"format":"png"}) if False else await s("Page.captureScreenshot",{"format":"png"})
        if "data" in s: open("/tmp/d14_zhdlg.png","wb").write(base64.b64decode(s["data"])); print("SHOT: /tmp/d14_zhdlg.png")
asyncio.run(main())
