# -*- coding: utf-8 -*-
"""第3期头条填充：标题 + 正文 HTML paste。依EXPERIENCE-20261010-cdp-prosemirror-paste。"""
import asyncio, json, re, urllib.request, websockets

CDP = "http://127.0.0.1:9229"
HTML_F = "20261010-lfl-daily-03.html"
TITLE = "程序不是大脑，但程序也不该是哑巴"

def targets():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "toutiao" in t.get("url", "")]

async def main():
    ts = targets()
    if not ts:
        print("NO_TOUTIAO_PAGE"); return
    t = ts[0]
    print("PAGE:", t["url"][:80])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i = [0]
        async def cmd(method, params=None):
            i[0] += 1
            await ws.send(json.dumps({"id": i[0], "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == i[0]:
                    if "error" in m: raise RuntimeError(method + " -> " + str(m["error"]))
                    return m.get("result", {})
        async def ev(expr):
            r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
            return r.get("result", {}).get("value")

        body = open(HTML_F, encoding="utf-8").read()

        # 1) 标题：textarea[placeholder*="标题"]
        ok = await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');
          if(!t) return 'NO_TITLE_TA';
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(t, %s);
          t.dispatchEvent(new Event('input',{bubbles:true}));
          return 'TITLE_SET:'+t.value.length;})()""" % json.dumps(TITLE))
        print(ok)

        # 2) 正文：ProseMirror paste（Cmd+V 无效，必须构造 ClipboardEvent）
        html = json.dumps(body)
        res = await ev("""(()=>{
          const pm=document.querySelector('.ProseMirror[contenteditable]');
          if(!pm) return 'NO_PM';
          const dt=new DataTransfer();
          dt.setData('text/html', %s);
          dt.setData('text/plain', %s);
          pm.focus();
          const sel=window.getSelection();
          const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          const ev=new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true});
          pm.dispatchEvent(ev);
          return 'PASTE_DISPATCHED';
        })()""" % (html, json.dumps(re.sub(r'<[^>]+>', '', body)[:4000])))
        print(res)
        await asyncio.sleep(3)

        # 3) 收口校验
        st = await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          return JSON.stringify({words: wc?wc[1]:null,
            imgs: pm?pm.querySelectorAll('img').length:-1,
            emptyH1: pm?[...pm.querySelectorAll('h1')].filter(h=>h.textContent.trim()==='').length:-1,
            titleLen: ti?ti.value.length:-1});})()""")
        print("STATE:", st)

asyncio.run(main())
