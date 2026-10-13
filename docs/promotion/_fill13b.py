# -*- coding: utf-8 -*-
"""D13 头条填充 v2：清空 -> 标题 -> 正文 HTML paste -> 校验。"""
import asyncio, json, re, urllib.request, websockets
CDP="http://127.0.0.1:9229"; HTML_F="20261013-lfl-daily-13.html"
TITLE="让 AI 别再「等等看」：一条把机器人从聊天气泡里拽出来的心跳指令"
def pages():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
async def main():
    pg=pages()
    if not pg: print("NO_PAGE"); return
    async with websockets.connect(pg[0]["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
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
        print("CLEAR:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          if(!pm) return 'NO_PM'; pm.focus();
          const sel=window.getSelection(); const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          document.execCommand('delete');
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(ta,''); ta.dispatchEvent(new Event('input',{bubbles:true}));
          return 'CLEARED len='+pm.innerText.length;})()"""))
        await asyncio.sleep(1)
        print("TITLE:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
          const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
          s.call(ta,%s); ta.dispatchEvent(new Event('input',{bubbles:true})); return ta.value.length;})()"""%json.dumps(TITLE)))
        body=open(HTML_F,encoding="utf-8").read()
        print("PASTE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const dt=new DataTransfer(); dt.setData('text/html',%s); dt.setData('text/plain',%s);
          pm.focus(); const sel=window.getSelection(); const r=document.createRange();
          r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
          pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
          return 'DISPATCHED';})()"""%(json.dumps(body), json.dumps(re.sub(r'<[^>]+>',' ',body)[:6000]))))
        await asyncio.sleep(5)
        print("STATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const txt=(pm.innerText||'').replace(/\\s+/g,'');
          return JSON.stringify({words:wc?wc[1]:null, textLen:txt.length, titleLen:ta?ta.value.length:-1,
            h2:pm.querySelectorAll('h2').length, table:pm.querySelectorAll('table').length,
            imgs:pm.querySelectorAll('img').length, resid:(txt.match(/fig\\d+/)||[])[0]||null,
            head:txt.slice(0,60), tail:txt.slice(-60)});})()"""))
asyncio.run(main())
