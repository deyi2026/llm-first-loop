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
        print("DECL_BEFORE:", await ev("""(()=>{const e=[...document.querySelectorAll('div,span,label,p')].find(x=>(x.innerText||'').trim()==='引用AI');
          if(!e) return 'NOT_FOUND';
          const box=e.closest('label')||e.parentElement;
          return JSON.stringify({tag:e.tagName, cls:(e.className||'').slice(0,40), boxCls:(box.className||'').slice(0,50),
            boxHtml:box.outerHTML.replace(/\\s+/g,' ').slice(0,200)});})()"""))
        print("CLICK:", await ev("""(()=>{const e=[...document.querySelectorAll('div,span,label,p')].find(x=>(x.innerText||'').trim()==='引用AI'&&(x.offsetParent||x.getClientRects().length));
          if(!e) return 'NOT_FOUND'; const box=e.closest('label')||e.parentElement; box.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(2)
        print("DECL_AFTER:", await ev("""(()=>{const e=[...document.querySelectorAll('div,span,label,p')].find(x=>(x.innerText||'').trim()==='引用AI');
          if(!e) return 'NOT_FOUND'; const box=e.closest('label')||e.parentElement;
          const cb=box.querySelector('input[type=checkbox],[role=checkbox],[class*=checkbox]');
          return JSON.stringify({boxCls:(box.className||'').slice(0,60), checked:cb?(cb.checked!==undefined?cb.checked:cb.getAttribute('aria-checked')):null,
            hasChecked:/checked|active|selected/.test(box.className||'')});})()"""))
        caps=["分权：哪些判断程序绝不接手——不可让渡的归程序，能自己判断的归模型","自主演进的三道锁：建议通道、执行权限、完成登记，钥匙始终在人手里"]
        print("CAPS:", await ev("""(()=>{const ts=[...document.querySelectorAll('textarea.pgc-img-caption-ipt')];
          const vals=%s; const set=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          ts.forEach((ta,k)=>{ if(vals[k]){ set.call(ta, vals[k]); ta.dispatchEvent(new Event('input',{bubbles:true})); ta.dispatchEvent(new Event('change',{bubbles:true})); }});
          return JSON.stringify(ts.map(t=>t.value.length));})()""" % json.dumps(caps)))
        await asyncio.sleep(2)
        print("STATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const im=[...new Set([...document.querySelectorAll('.ProseMirror img')].filter(x=>x.naturalWidth>0&&!x.closest('template')).map(x=>x.src))];
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          return JSON.stringify({words:wc?wc[1]:null, uniqImgs:im.length, titleLen:ti.value.length,
            caps:[...document.querySelectorAll('textarea.pgc-img-caption-ipt')].map(t=>t.value.length)});})()"""))
asyncio.run(main())
