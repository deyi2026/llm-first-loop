# -*- coding: utf-8 -*-
"""D13 配图 v2：File+DataTransfer+合成 paste 注入 .ProseMirror（依 EXPERIENCE-20261011 已验证路径）。
setFileInputFiles 路径已实证失败（上传失败/0 张），本脚本不走图片面板。"""
import asyncio, base64, json, os, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
FIGS = ["img/fig39-heartbeat-protocol.png", "img/fig40-heartbeat-cost.png"]

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

        base = await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const imgs=pm?[...pm.querySelectorAll('img')].filter(x=>x.offsetParent!==null).length:-1;
          return JSON.stringify({words: wc?wc[1]:null, imgs, textLen: pm?pm.innerText.length:-1});})()""")
        print("BASELINE:", base)
        b = json.loads(base)
        if not b.get("words") or b["words"] in (None,"0"):
            print("ABORT: 正文不在编辑器中，先恢复正文再插图"); return

        for p in FIGS:
            ap = os.path.abspath(p)
            if not os.path.exists(ap):
                print("MISSING_FILE:", ap); continue
            b64 = base64.b64encode(open(ap,"rb").read()).decode()
            js = """(()=>{
              const b64=%s, name=%s;
              const bin=atob(b64); const buf=new Uint8Array(bin.length);
              for(let k=0;k<bin.length;k++) buf[k]=bin.charCodeAt(k);
              const file=new File([buf], name, {type:'image/png'});
              const dt=new DataTransfer(); dt.items.add(file);
              const pm=document.querySelector('.ProseMirror[contenteditable]');
              pm.focus();
              const sel=window.getSelection(); const r=document.createRange();
              r.selectNodeContents(pm); r.collapse(false); sel.removeAllRanges(); sel.addRange(r);
              pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
              return 'PASTED '+name;})()""" % (json.dumps(b64), json.dumps(os.path.basename(ap)))
            print("INJECT:", await ev(js))
            await asyncio.sleep(8)
            st = await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
              const vis=[...pm.querySelectorAll('img')].filter(x=>x.offsetParent!==null);
              const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
              return JSON.stringify({imgs: vis.length,
                last: vis.length? {w: vis[vis.length-1].naturalWidth, src:(vis[vis.length-1].src||'').slice(0,60)} : null,
                words: wc?wc[1]:null});})()""")
            print("AFTER:", st)

        print("FINAL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const vis=[...pm.querySelectorAll('img')].filter(x=>x.offsetParent!==null);
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const ta=document.querySelector('textarea[placeholder*="标题"]');
          return JSON.stringify({imgs: vis.length,
            dims: vis.map(x=>x.naturalWidth+'x'+x.naturalHeight),
            words: wc?wc[1]:null, titleLen: ta?ta.value.length:-1});})()"""))

asyncio.run(main())
