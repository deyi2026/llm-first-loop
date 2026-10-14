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
        print("SET_AI:", await ev("""(()=>{const labels=[...document.querySelectorAll('label.byte-checkbox')];
          const lab=labels.find(l=>(l.innerText||'').trim()==='引用AI');
          if(!lab) return 'NO_LABEL';
          const inp=lab.querySelector('input[type=checkbox]');
          if(!inp) return 'NO_INPUT';
          if(!inp.checked) inp.click();
          return JSON.stringify({checked:inp.checked, value:inp.value, labCls:(lab.className||'').slice(0,60)});})()"""))
        await asyncio.sleep(2)
        print("VERIFY:", await ev("""(()=>{const labels=[...document.querySelectorAll('label.byte-checkbox')];
          const lab=labels.find(l=>(l.innerText||'').trim()==='引用AI');
          const inp=lab&&lab.querySelector('input[type=checkbox]');
          return JSON.stringify({checked:inp?inp.checked:null, cls:(lab&&lab.className||'').slice(0,60),
            all:[...labels].map(l=>(l.innerText||'').trim()+':'+((l.querySelector('input')||{}).checked?'ON':'OFF')).slice(0,10)});})()"""))
        print("CAPS_STILL:", await ev("""JSON.stringify([...document.querySelectorAll('textarea.pgc-img-caption-ipt')].map(t=>t.value.length))"""))
asyncio.run(main())
