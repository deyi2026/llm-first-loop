import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    async with websockets.connect(pages()[0]["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    r=m.get("result",{})
                    if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
                    return r.get("result",{}).get("value")
        print("DEL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          let n=0;
          [...pm.children].forEach(ch=>{ if(ch.querySelector&&ch.querySelector('img')){
            const sel=window.getSelection(); const r=document.createRange();
            r.selectNode(ch); sel.removeAllRanges(); sel.addRange(r);
            document.execCommand('delete'); n++; }});
          return 'deleted '+n+' remain='+pm.querySelectorAll('img').length+' textLen='+pm.innerText.length;})()"""))
        await asyncio.sleep(2)
        print("AFTER:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({imgs:pm.querySelectorAll('img').length, words:wc?wc[1]:null,
            blocks:pm.children.length, first:(pm.children[0]||{}).innerText});})()"""))
asyncio.run(main())
