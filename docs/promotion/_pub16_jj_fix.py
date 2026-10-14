# -*- coding: utf-8 -*-
"""D16 Juejin fix: add 2nd tag via panel-scoped byte-select, then confirm publish."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn/editor" in x.get("url", "")][-1]

async def main():
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=50*1024*1024) as ws:
        n = [0]
        async def ev(e):
            n[0] += 1
            await ws.send(json.dumps({"id": n[0], "method": "Runtime.evaluate",
                "params": {"expression": e, "returnByValue": True, "awaitPromise": True}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n[0]:
                    r = m.get("result", {})
                    if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:250])
                    return r.get("result", {}).get("value")
        panel_open = await ev("(()=>{return !![...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');})()")
        print("PANEL_OPEN", panel_open, flush=True)
        if not panel_open:
            print("OPEN_PANEL", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.offsetParent&&x.textContent.trim()==='发布');if(!b)return 'NO_PUB';b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(3.5)
        # panel root: walk up from 确定并发布 until text contains 分类
        print("PANEL_TEXT", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .filter(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
          if(!b.length)return 'PANEL_CLOSED';let p=b[0];
          for(let i=0;i<12&&p;i++){p=p.parentElement;
            if(p&&(p.innerText||'').includes('分类')&&(p.innerText||'').includes('标签'))break;}
          return p?(p.innerText||'').replace(/\\n+/g,'|').slice(0,500):'NO_PANEL';})()"""), flush=True)
        # 2nd tag: panel-scoped first .byte-select (placeholder gone after 1st pick)
        print("TAG2_OPEN", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .filter(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
          if(!b.length)return 'PANEL_CLOSED';let p=b[0];
          for(let i=0;i<12&&p;i++){p=p.parentElement;
            if(p&&(p.innerText||'').includes('分类')&&(p.innerText||'').includes('标签'))break;}
          if(!p)return 'NO_PANEL';
          const s=[...p.querySelectorAll('.byte-select')].find(x=>x.offsetParent);
          if(!s)return 'NO_SEL';s.click();return 'OPENED';})()"""))
        await asyncio.sleep(1.5)
        print("TAG2_TYPE", await ev("""(()=>{const sels=[...document.querySelectorAll('.byte-select')];
          const s=sels.find(x=>x.offsetParent&&x.querySelector('input,textarea')&&(x.innerText||'').indexOf('请选择')<0);
          if(!s)return 'NO_SEL';const i=s.querySelector('input,textarea');if(!i)return 'NO_INPUT';
          const proto=i.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(i,'LLM');
          i.dispatchEvent(new Event('input',{bubbles:true}));i.focus();
          return 'TYPED:'+i.value;})()"""))
        await asyncio.sleep(2.5)
        print("TAG2_PICK", await ev("""(()=>{const cand=[...document.querySelectorAll('li,[class*=option],[class*=dropdown] *')]
          .filter(x=>x.offsetParent&&x.children.length===0&&x.tagName!=='INPUT'
            &&(x.innerText||'').replace(/\\s+/g,'').includes('LLM'));
          if(!cand.length)return 'NO_OPTION';cand[0].click();
          return 'PICKED:'+(cand[0].innerText||'').replace(/\\s+/g,'').slice(0,20);})()"""))
        await asyncio.sleep(1.5)
        print("PANEL_TEXT2", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .filter(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
          if(!b.length)return 'PANEL_CLOSED';let p=b[0];
          for(let i=0;i<12&&p;i++){p=p.parentElement;
            if(p&&(p.innerText||'').includes('分类')&&(p.innerText||'').includes('标签'))break;}
          return p?(p.innerText||'').replace(/\\n+/g,'|').slice(0,500):'NO_PANEL';})()"""), flush=True)
        import sys
        if "--dry" in sys.argv:
            print("DRY_STOP"); return
        print("FINAL", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布'&&!x.disabled);
          if(!b)return 'NO_FINAL';b.click();return 'CLICKED';})()"""))
        for _ in range(12):
            await asyncio.sleep(3)
            u = await ev("location.href")
            print("URL", u, flush=True)
            if "/post/" in u or "/editor/drafts/new" not in u: break
        print("BODY_HEAD", str(await ev("document.body.innerText"))[:300])

asyncio.run(main())
