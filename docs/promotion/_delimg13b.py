import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    async with websockets.connect(pages()[0]["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(m_,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m_,"params":p or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    r=m.get("result",{})
                    if "error" in r: return "ERR:"+str(r["error"])
                    return r
        async def ev(e):
            r=await cmd("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if isinstance(r,str): return r
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")
        # 1) 选中图片块
        print("SEL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ch=[...pm.children].find(c=>c.querySelector&&c.querySelector('img'));
          ch.scrollIntoView({block:'center'});
          const sel=window.getSelection(); const r=document.createRange();
          r.selectNode(ch); sel.removeAllRanges(); sel.addRange(r);
          return 'sel on '+ch.tagName+' text='+(window.getSelection().toString()||'').slice(0,20);})()"""))
        await asyncio.sleep(1)
        # 2) 真实键盘 Backspace
        for t in ("keyDown","keyUp"):
            await cmd("Input.dispatchKeyEvent",{"type":t,"key":"Backspace","code":"Backspace","windowsVirtualKeyCode":8,"nativeVirtualKeyCode":8})
        await asyncio.sleep(2)
        print("AFTER_BS:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null,
            blocks:pm.children.length, head:pm.innerText.replace(/\\s+/g,' ').slice(0,50)});})()"""))
asyncio.run(main())
