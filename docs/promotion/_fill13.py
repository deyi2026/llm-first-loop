# -*- coding: utf-8 -*-
"""D13 头条填充：标题 + 正文 HTML paste。"""
import asyncio, json, re, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
HTML_F = "20261013-lfl-daily-13.html"
TITLE = "让 AI 别再「等等看」：一条把机器人从聊天气泡里拽出来的心跳指令"

def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url","")]

async def main():
    pg = pages()
    if not pg:
        print("NO_PUBLISH_PAGE"); return
    t = pg[0]
    print("PAGE:", t["url"][:80])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        i=[0]
        async def cmd(method, params=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":method,"params":params or {}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "error" in m: raise RuntimeError(method+" -> "+str(m["error"]))
                    return m.get("result",{})
        async def ev(e):
            r = await cmd("Runtime.evaluate", {"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+str(r["exceptionDetails"].get("text"))
            return r.get("result",{}).get("value")

        body = open(HTML_F, encoding="utf-8").read()
        html = json.dumps(body)
        plain = json.dumps(re.sub(r'<[^>]+>',' ', body)[:6000])

        # 0) 清空旧标题与旧正文
        print("CLEAR:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(ta,''); ta.dispatchEvent(new Event('input',{bubbles:true}));
          const pm=document.querySelector('.ProseMirror[contenteditable]');
          if(pm){pm.focus(); const sel=window.getSelection(); const r=document.createRange();
            r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
            document.execCommand('delete');}
          return 'CLEARED';})()"""))
        await asyncio.sleep(1)

        # 1) 标题
        print("TITLE:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(ta, %s); ta.dispatchEvent(new Event('input',{bubbles:true}));
          return 'SET len='+ta.value.length;})()""" % json.dumps(TITLE)))

        # 2) 正文 paste
        print("PASTE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          if(!pm) return 'NO_PM';
          const dt=new DataTransfer(); dt.setData('text/html',%s); dt.setData('text/plain',%s);
          pm.focus(); const sel=window.getSelection(); const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
          return 'DISPATCHED';})()""" % (html, plain)))
        await asyncio.sleep(4)

        # 3) 收口校验
        st = await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          return JSON.stringify({words: wc?wc[1]:null,
            imgs: pm?pm.querySelectorAll('img').length:-1,
            titleLen: ta?ta.value.length:-1,
            head:(pm&&pm.innerText||'').replace(/\\s+/g,' ').slice(0,80),
            tail:(pm&&pm.innerText||'').replace(/\\s+/g,' ').slice(-80)});})()""")
        print("STATE:", st)

asyncio.run(main())
