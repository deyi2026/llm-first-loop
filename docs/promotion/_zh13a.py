# -*- coding: utf-8 -*-
"""知乎 /write：填标题 + 整篇 HTML 合成 paste。"""
import asyncio, json, re, urllib.request, websockets
CDP="http://127.0.0.1:9229"; HTML_F="20261013-lfl-daily-13.html"
TITLE="让 AI 别再「等等看」：一条把机器人从聊天气泡里拽出来的心跳指令"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "zhuanlan.zhihu.com/write" in t.get("url",""): return t
    return None
async def main():
    pg=page()
    if not pg: print("NO_PAGE"); return
    async with websockets.connect(pg["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
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
        print("URL:", await ev("location.href"))
        print("EDITOR:", await ev("""(()=>{const e=document.querySelector('.DraftEditor-root')||document.querySelector('[contenteditable=true]');
          if(!e) return 'NONE';
          const ta=document.querySelector('textarea');
          return JSON.stringify({cls:e.className.slice(0,40), titleTA:!!ta, blocks:document.querySelectorAll('.public-DraftStyleDefault-block').length});})()"""))
        # 标题
        print("TITLE:", await ev("""(()=>{const ta=document.querySelector('textarea');
          if(!ta) return 'NO_TA';
          const proto = ta.tagName==='TEXTAREA'? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
          const s=Object.getOwnPropertyDescriptor(proto,'value').set;
          s.call(ta,%s); ta.dispatchEvent(new Event('input',{bubbles:true})); return ta.value.length;})()"""%json.dumps(TITLE)))
        await asyncio.sleep(1)
        body=open(HTML_F,encoding="utf-8").read()
        print("PASTE:", await ev("""(()=>{const e=document.querySelector('.DraftEditor-root');
          e.focus();
          const dt=new DataTransfer();
          dt.setData('text/html',%s); dt.setData('text/plain',%s);
          e.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
          return 'DISPATCHED';})()"""%(json.dumps(body), json.dumps(re.sub(r'<[^>]+>','\n',body)))))
        await asyncio.sleep(8)
        print("STATE:", await ev("""(()=>{const blocks=[...document.querySelectorAll('.public-DraftStyleDefault-block')];
          const txt=blocks.map(b=>b.innerText).join('');
          return JSON.stringify({blocks:blocks.length, chars:txt.replace(/\\s+/g,'').length,
            heads:blocks.filter(b=>/^[一二三四五六]、/.test(b.innerText.trim())).length,
            imgs:document.querySelectorAll('.DraftEditor-root img').length,
            resid:/fig\\d+/.test(txt)});})()"""))
asyncio.run(main())
