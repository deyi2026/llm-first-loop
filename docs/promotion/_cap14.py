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
        caps=["分权：哪些判断程序绝不接手——不可让渡的归程序，能自己判断的归模型",
              "自主演进的三道锁：建议通道、执行权限、完成登记，钥匙始终在人手里"]
        print("SET_CAPS:", await ev("""(()=>{const ts=[...document.querySelectorAll('textarea.pgc-img-caption-ipt')];
          const vals=%s;
          const set=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          ts.forEach((ta,k)=>{ if(vals[k]){ set.call(ta, vals[k]); ta.dispatchEvent(new Event('input',{bubbles:true}));
            ta.dispatchEvent(new Event('change',{bubbles:true})); }});
          return JSON.stringify(ts.map(t=>t.value));})()""" % json.dumps(caps)))
        await asyncio.sleep(2)
        print("PRE-GATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const imgs=[...document.querySelectorAll('.ProseMirror img')].filter(x=>x.naturalWidth>0&&!x.closest('template'));
          const uniq=[...new Set(imgs.map(x=>x.src))];
          return JSON.stringify({title:ti.value, titleLen:ti.value.length, words:wc?wc[1]:null,
            imgsLoaded:imgs.length, uniqSrc:uniq.length, emptyH1:[...pm.querySelectorAll('h1')].filter(h=>!h.textContent.trim()).length,
            h2:pm.querySelectorAll('h2').length, caps:[...document.querySelectorAll('textarea.pgc-img-caption-ipt')].map(t=>t.value.length),
            tail:(pm.innerText||'').replace(/\\s+/g,' ').slice(-60)});})()"""))
asyncio.run(main())
