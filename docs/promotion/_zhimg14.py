import asyncio, json, base64, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and sub in t.get("url",""): return t
IMG="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const c=[...ed.querySelectorAll('[data-block=true]')].find(p=>(p.innerText||'').trim().startsWith(%s));
 if(!c) return 'NO_ANCHOR';
 const r=document.createRange(); r.setStartBefore(c); r.setEndBefore(c);
 const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); ed.focus();
 const bin=atob(%s); const arr=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
 const dt=new DataTransfer(); dt.items.add(new File([arr],%s,{type:'image/png'}));
 ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})); return 'PASTED';})()"""
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
        for cap,img in [("分权：哪些判断程序绝不接手","img/fig41-power-split.png"),
                        ("自主演进的三道锁","img/fig42-evolution-locks.png")]:
            b64=base64.b64encode(open(img,"rb").read()).decode()
            print("IMG", os.path.basename(img), await ev(IMG % (json.dumps(cap,ensure_ascii=False), json.dumps(b64), json.dumps(os.path.basename(img)))))
            await asyncio.sleep(12)
        print("STATE:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          const im=[...ed.querySelectorAll('img')]; const bl=[...ed.querySelectorAll('[data-block=true]')];
          const idxs=bl.map((d,n)=>d.querySelector('img')?n:-1).filter(n=>n>=0);
          return JSON.stringify({blocks:bl.length, imgs:im.length, loaded:im.filter(x=>x.naturalWidth>0).length,
            dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
            neighbors:idxs.map(n=>({after:(bl[n].nextElementSibling&&bl[n].nextElementSibling.innerText||'').replace(/\\s+/g,' ').slice(0,14),
              before:(bl[n].previousElementSibling&&bl[n].previousElementSibling.innerText||'').replace(/\\s+/g,' ').slice(-14)})),
            counter:(document.body.innerText.match(/字数[：:]\\s*\\d+/)||['none'])[0]});})()"""))
asyncio.run(main())
