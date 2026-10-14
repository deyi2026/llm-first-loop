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
        print("BACK:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='返回编辑');
          if(!b) return 'NO'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(4)
        print("COVER:", await ev("""(()=>{const c=document.querySelector('.article-cover-img-wrap, .article-cover');
          if(!c) return 'NO_COVER_EL';
          const im=c.querySelector('img');
          return JSON.stringify({txt:(c.innerText||'').replace(/\\s+/g,' ').slice(0,40),
            src:im?(im.src||'').slice(0,90):null, w:im?im.naturalWidth:0,
            radio:[...document.querySelectorAll('.byte-radio-group [class*=checked],.byte-radio-group [class*=active]')].map(x=>(x.innerText||'').slice(0,6))});})()"""))
        print("AI_CONTROLS:", await ev("""(()=>{const out=[];
          document.querySelectorAll('label,span,div,p').forEach(e=>{const t=(e.innerText||'').trim();
            if(t&&t.length<24&&/AI|人工智能|声明|原创/.test(t)&&(e.offsetParent||e.getClientRects().length)) out.push(t);});
          return JSON.stringify([...new Set(out)].slice(0,20));})()"""))
        print("CHECKBOXES:", await ev("""JSON.stringify([...document.querySelectorAll('input[type=checkbox],[role=checkbox],[class*=checkbox]')].map(x=>({
          cls:(x.className||'').slice(0,30), checked:x.checked, vis:!!(x.offsetParent||x.getClientRects().length),
          near:(x.closest('label')||x.parentElement||{}).innerText?String((x.closest('label')||x.parentElement).innerText).replace(/\\s+/g,' ').slice(0,20):''})).filter(o=>o.vis).slice(0,12))"""))
        print("CAPS_NOW:", await ev("""JSON.stringify([...document.querySelectorAll('textarea.pgc-img-caption-ipt')].map(t=>t.value.slice(0,10)))"""))
asyncio.run(main())
