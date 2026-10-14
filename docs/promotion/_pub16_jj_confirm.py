# -*- coding: utf-8 -*-
"""D16 Juejin confirm: category + tags + 确定并发布, monitor URL."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn/editor" in x.get("url", "")][-1]

async def main():
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=50 * 1024 * 1024) as ws:
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
        print("PANEL", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
          return b?'PANEL_OPEN':'PANEL_CLOSED';})()"""))
        if await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='发布');if(!b)return 'NO';b.click();return 'OPEN';})()"""):
            await asyncio.sleep(3)
        print("CAT", await ev("""(()=>{const o=[...document.querySelectorAll('div,span,label,li')]
          .filter(x=>x.offsetParent&&x.children.length===0&&x.textContent.trim()==='人工智能');
          if(!o.length)return 'NO_CAT';o[0].click();return 'CLICKED';})()"""))
        await asyncio.sleep(1)
        for tag in ("人工智能", "LLM"):
            print(tag, "OPEN", await ev("""(()=>{const root=[...document.querySelectorAll('div')]
              .find(x=>x.offsetParent&&(x.innerText||'').includes('请搜索添加标签')&&(x.innerText||'').trim().length<30);
              if(!root)return 'NO_ROOT';root.click();return 'CLICKED';})()"""))
            await asyncio.sleep(1)
            print(tag, "TYPE", await ev("""(()=>{const root=[...document.querySelectorAll('div')]
              .filter(x=>x.offsetParent&&(x.innerText||'').includes('添加标签'))
              .sort((a,b)=>(a.innerText||'').length-(b.innerText||'').length)[0];
              if(!root)return 'NO_ROOT2';const i=root.querySelector('input,textarea');if(!i)return 'NO_INPUT';
              const proto=i.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
              Object.getOwnPropertyDescriptor(proto,'value').set.call(i,%s);
              i.dispatchEvent(new Event('input',{bubbles:true}));i.focus();
              return 'TYPED:'+i.value;})()""" % json.dumps(tag, ensure_ascii=False)))
            await asyncio.sleep(2.5)
            print(tag, "PICK", await ev("""(()=>{const opts=[...document.querySelectorAll('li,[class*=option],[class*=dropdown] *')]
              .filter(x=>x.offsetParent&&x.children.length===0&&x.tagName!=='INPUT'
                &&(x.innerText||'').replace(/\\s+/g,'').startsWith(%s)===false&&(x.innerText||'').replace(/\\s+/g,'').includes(%s));
              if(!opts.length)return 'NO_OPTION';opts[0].click();return 'PICKED:'+(opts[0].innerText||'').trim().slice(0,20);})()"""
              % (json.dumps(tag, ensure_ascii=False), json.dumps(tag, ensure_ascii=False))))
            await asyncio.sleep(1.5)
        print("DLG_STATE", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
          if(!b)return 'PANEL_GONE';let p=b;for(let i=0;i<10&&p;i++){p=p.parentElement;
            if(p&&(p.innerText||'').includes('分类'))return (p.innerText||'').replace(/\\n+/g,'|').slice(0,300);}return 'NO_PANEL_TEXT';})()"""))
        print("FINAL", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .find(b=>b.offsetParent&&b.textContent.trim()==='确定并发布'&&!b.disabled);
          if(!b)return 'NO_FINAL';b.click();return 'CLICKED';})()"""))
        for _ in range(10):
            await asyncio.sleep(3)
            u = await ev("location.href")
            print("URL", u)
            if "/post/" in u or "/editor/drafts/new" not in u: break
        print("BODY_HEAD", str(await ev("document.body.innerText"))[:300])

asyncio.run(main())
