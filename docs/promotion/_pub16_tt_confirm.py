# -*- coding: utf-8 -*-
"""D16 Toutiao final confirm: pick 无封面, click panel 预览并发布, capture article id."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "profile_v4/graphic/publish" in x.get("url", "")][-1]

async def main():
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024) as ws:
        i = [0]
        async def ev(e):
            i[0] += 1
            await ws.send(json.dumps({"id": i[0], "method": "Runtime.evaluate",
                "params": {"expression": e, "returnByValue": True, "awaitPromise": True}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == i[0]:
                    if "exceptionDetails" in m.get("result", {}): raise RuntimeError(str(m["result"]["exceptionDetails"])[:400])
                    v = m.get("result", {}).get("result", {}).get("value")
                    if v is None: v = m.get("result", {}).get("value")
                    return v
        print("NO_COVER", await ev("""(()=>{const el=[...document.querySelectorAll('label,span,div,button')]
            .find(x=>x.offsetParent&&x.children.length===0&&x.textContent.trim()==='无封面');
            if(!el)return 'NOT_FOUND';el.click();return 'CLICKED';})()"""))
        await asyncio.sleep(2)
        print("COVER_STATE", await ev("""(()=>{const sels=[...document.querySelectorAll('label,span,div')]
            .filter(x=>x.offsetParent&&x.children.length===0&&/^(单图|三图|无封面)$/.test(x.textContent.trim()))
            .map(x=>{const r=x.closest('[class*=cover],[class*=radio],[class*=item],[class*=checked]');
              return x.textContent.trim()+':' +(r?((r.className||'').toString().match(/checked|selected|active/)?'on':'?'):'?')});
            return JSON.stringify(sels);})()"""))
        print("FINAL_CLICK", await ev("""(()=>{const bs=[...document.querySelectorAll('button')]
            .filter(b=>b.offsetParent&&b.textContent.trim()==='预览并发布'&&!b.disabled);
            if(!bs.length)return 'NO_BTN';bs[bs.length-1].click();return 'CLICKED_'+bs.length;})()"""))
        for _ in range(10):
            await asyncio.sleep(3)
            u = await ev("location.href")
            print("URL", u)
            if "graphic/publish" not in u: break
        print("BODY_TAIL", str(await ev("document.body.innerText"))[-600:])

asyncio.run(main())
