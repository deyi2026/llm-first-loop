import asyncio, json, os, urllib.request, base64, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method,params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
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
        async def dlg():
            return await ev("""(()=>{const t=document.body.innerText;
              const m=t.match(/已上传\\s*(\\d+)\\s*张/); const f=t.match(/上传失败/g);
              const ok=[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='确定').map(b=>b.disabled?'DISABLED':'ENABLED');
              return JSON.stringify({uploaded:m?m[1]:null, fails:f?f.length:0, confirm:ok});})()""")
        # 关掉当前弹窗
        print("CANCEL:", await ev("""(()=>{for(const b of document.querySelectorAll('button')){if(b.textContent.trim()==='取消'){b.click(); return 'CLICKED';}} return 'NO';})()"""))
        await asyncio.sleep(2)
        print("REOPEN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button'); if(!b) return 'NO'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(3)
        doc=await cmd("DOM.getDocument")
        q=await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],"selector":"input[type=file].btn-upload-handle input[type=file], .btn-upload-handle input[type=file]"})
        nid=q.get("nodeId") or (await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],"selector":"input[type=file]"}))["nodeId"]
        ap=os.path.abspath("img/fig41-power-split.png")
        print("SET:", await cmd("DOM.setFileInputFiles",{"nodeId":nid,"files":[ap]}))
        for w in (3,5,8,12):
            await asyncio.sleep(w)
            print(f"T+{w}:", await dlg())
        shot=await cmd("Page.captureScreenshot",{"format":"png"})
        if "data" in shot: open("/tmp/d14_retry.png","wb").write(base64.b64decode(shot["data"])); print("SHOT ok")
asyncio.run(main())
