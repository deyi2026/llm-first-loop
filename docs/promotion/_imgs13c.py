# -*- coding: utf-8 -*-
"""D13 配图 v3：只补一张。不设 DOM Range 选区（D13b 因此清空正文）。
依 STATUS-20261012.md:58 — scrollIntoView 后真实点击锚点块行尾，再由平台 handler 替换选区为图块。"""
import asyncio, base64, json, os, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
FIG = "img/fig40-heartbeat-cost.png"

def pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "profile_v4/graphic/publish" in t.get("url","")]

async def main():
    pg = pages()
    if not pg: print("NO_PUBLISH_PAGE"); return
    t = pg[0]
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

        print("BASE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const v=[...pm.querySelectorAll('img')].filter(x=>x.offsetParent!==null);
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          return JSON.stringify({imgs:v.length, words:wc?wc[1]:null});})()"""))

        # 1) 光标落到正文最后一个块行尾：用真实点击而非 DOM Range
        pos = await ev("""(()=>{
          const pm=document.querySelector('.ProseMirror[contenteditable]');
          const blocks=[...pm.children].filter(n=>n.nodeType===1);
          const last=blocks[blocks.length-1];
          last.scrollIntoView({block:'center'});
          last.focus();
          return 'blocks='+blocks.length+' lastTag='+last.tagName+' lastText='+(last.innerText||'').slice(0,30);
        })()""")
        print("ANCHOR:", pos)

        # 2) paste 注入第二张
        ap = os.path.abspath(FIG)
        b64 = base64.b64encode(open(ap,"rb").read()).decode()
        js = """(()=>{
          const b64=%s, name=%s;
          const bin=atob(b64); const buf=new Uint8Array(bin.length);
          for(let k=0;k<bin.length;k++) buf[k]=bin.charCodeAt(k);
          const file=new File([buf], name, {type:'image/png'});
          const dt=new DataTransfer(); dt.items.add(file);
          const pm=document.querySelector('.ProseMirror[contenteditable]');
          pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
          return 'PASTED '+name;})()""" % (json.dumps(b64), json.dumps(os.path.basename(ap)))
        print("INJECT:", await ev(js))
        await asyncio.sleep(8)

        print("FINAL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const v=[...pm.querySelectorAll('img')].filter(x=>x.offsetParent!==null);
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          return JSON.stringify({imgs:v.length, dims:v.map(x=>x.naturalWidth+'x'+x.naturalHeight),
            words:wc?wc[1]:null, titleLen:ta?ta.value.length:-1,
            textLen:pm.innerText.length});})()"""))

asyncio.run(main())
