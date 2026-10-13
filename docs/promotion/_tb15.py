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
        print("BTNS:", await ev("""JSON.stringify([...document.querySelectorAll('.syl-toolbar-button')].map((b,k)=>({k, t:(b.getAttribute('data-tooltip')||b.title||b.getAttribute('aria-label')||'').slice(0,14), cls:b.className.slice(0,40)})))"""))
        print("TOOL_CLASSES:", await ev("""JSON.stringify([...new Set([...document.querySelectorAll('div')].map(d=>d.className).filter(c=>typeof c==='string'&&/tool|editor-bar|bar/.test(c)).slice(0,10))])"""))
        print("IMG_LIKE:", await ev("""JSON.stringify([...document.querySelectorAll('svg use')].map(u=>(u.getAttribute('href')||u.getAttribute('xlink:href')||'').slice(-24)).slice(0,30))"""))
asyncio.run(main())
