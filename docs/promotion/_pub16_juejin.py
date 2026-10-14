# -*- coding: utf-8 -*-
"""D16 Juejin (prefix-cache, markdown): CM5 setValue + title + publish dialog + verify."""
import asyncio, json, sys, urllib.request, websockets
from pathlib import Path

HERE = Path(__file__).resolve().parent
CDP = "http://127.0.0.1:9229"
TITLE = "AI 每次回答都重读整个对话——为什么你的账单没爆"
MD = HERE / "20261013-prefix-cache-kepu.md"
KEYS = ["前缀缓存（prefix caching）", "缓存命中 0.006 美元", "5 分钟", "绝不跨组织", "核实日期 2026 年 10 月 13 日"]
PHASE = sys.argv[1] if len(sys.argv) > 1 else "fill"
assert PHASE in ("fill", "dialog", "confirm", "verify")

arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
ts = [x for x in arr if x.get("type") == "page" and "juejin.cn/editor" in x.get("url", "")]
if not ts: print("NO_JUEJIN_TAB"); sys.exit(0)
t = ts[-1]
print("JJ_TAB", t["url"] if PHASE != "verify" else "")

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
                    if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:300])
                    return r.get("result", {}).get("value")
        async def state():
            j = await ev("""(()=>{const cm=document.querySelector('.CodeMirror');
              const ti=document.querySelector('input.title-input');
              return JSON.stringify({url:location.href.slice(-40),cm:!!(cm&&cm.CodeMirror),
                title:ti?ti.value:'',len:cm&&cm.CodeMirror?cm.CodeMirror.getValue().replace(/\\s/g,'').length:-1,
                head:cm&&cm.CodeMirror?cm.CodeMirror.getValue().slice(0,60).replace(/\\n/g,'⏎'):''});})()""")
            print("STATE", j, flush=True)
            return json.loads(j)

        if PHASE == "fill":
            s = await state()
            if s["title"] and s["title"] != TITLE: print("FOREIGN_DRAFT_STOP"); return
            body = MD.read_text().split("\n", 1)[1]
            print("SET_BODY", await ev("""(()=>{const cm=document.querySelector('.CodeMirror');if(!cm||!cm.CodeMirror)return 'NO_CM';
              cm.CodeMirror.setValue(%s);cm.CodeMirror.getInputField().dispatchEvent(new Event('input',{bubbles:true}));
              return 'SET:'+cm.CodeMirror.getValue().length;})()""" % json.dumps(body, ensure_ascii=False)))
            await asyncio.sleep(1)
            print("SET_TITLE", await ev("""(()=>{const t=document.querySelector('input.title-input');if(!t)return 'NO_TITLE';
              const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
              set.call(t,%s);t.dispatchEvent(new Event('input',{bubbles:true}));return t.value;})()""" %
              json.dumps(TITLE, ensure_ascii=False)))
            await asyncio.sleep(3)
            await state(); return
        if PHASE == "dialog":
            s = await state()
            if s["title"] != TITLE or s["len"] < 1000: print("DIALOG_GATE_STOP"); return
            print("OPEN", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(b=>b.offsetParent&&b.textContent.trim()==='发布');if(!b)return 'NO_PUB';b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(4)
            print("DLG_TEXT", await ev("""(()=>{const d=[...document.querySelectorAll('[class*=modal],[class*=dialog],[class*=container]')]
              .filter(x=>x.offsetParent&&(x.innerText||'').includes('分类'));
              return d.length?(d[0].innerText||'').replace(/\\s+/g,' ').slice(0,600):'NO_DLG';})()"""))
            print("DLG_BTNS", await ev("""JSON.stringify([...document.querySelectorAll('button')].filter(b=>b.offsetParent)
              .map(b=>(b.innerText||'').replace(/\\s+/g,' ').trim().slice(0,14)).filter(Boolean))"""))
            return
        if PHASE == "confirm":
            # choose category 人工智能 if list present, then tags, then 确定并发布
            print("CAT", await ev("""(()=>{const opts=[...document.querySelectorAll('div,span,label,li')]
              .filter(x=>x.offsetParent&&x.children.length===0&&x.textContent.trim()==='人工智能');
              if(!opts.length)return 'NO_CAT_OPTION';opts[0].click();return 'CLICKED';})()"""))
            await asyncio.sleep(1)
            for tag in ("人工智能", "LLM"):
                print("TAG:"+tag, await ev("""(()=>{const sel=document.querySelectorAll('.byte-select');
                const s=[...sel].find(x=>x.offsetParent&&(x.closest('div')?.innerText||'').includes('添加标签'));
                if(!s)return 'NO_TAG_SELECT';s.click();return 'OPENED';})()"""))
                await asyncio.sleep(1)
                print("TAG_INPUT", await ev("""(()=>{const inp=[...document.querySelectorAll('.byte-select__input')]
                  .filter(i=>i.offsetParent);if(!inp.length)return 'NO_INPUT';
                  const i=inp[inp.length-1];const proto=i.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
                  const set=Object.getOwnPropertyDescriptor(proto,'value').set;
                  set.call(i,%s);i.dispatchEvent(new Event('input',{bubbles:true}));return 'TYPED';})()""" % json.dumps(tag, ensure_ascii=False)))
                await asyncio.sleep(2)
                print("TAG_PICK", await ev("""(()=>{const li=[...document.querySelectorAll('li,[class*=option],[class*=dropdown] *')]
                  .filter(x=>x.offsetParent&&(x.innerText||'').replace(/\\s+/g,'').includes(%s));
                  if(!li.length)return 'NO_OPTION';li[0].click();return 'PICKED';})()""" % json.dumps(tag, ensure_ascii=False)))
                await asyncio.sleep(1)
            print("DLG_STATE", await ev("""(()=>{const d=[...document.querySelectorAll('[class*=modal],[class*=dialog],[class*=container]')]
              .filter(x=>x.offsetParent&&(x.innerText||'').includes('分类'));
              return d.length?(d[0].innerText||'').replace(/\\s+/g,' ').slice(0,300):'NO_DLG';})()"""))
            print("FINAL", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(b=>b.offsetParent&&b.textContent.trim()==='确定并发布'&&!b.disabled);
              if(!b)return 'NO_FINAL';b.click();return 'CLICKED';})()"""))
            for _ in range(8):
                await asyncio.sleep(3)
                u = await ev("location.href")
                print("URL", u)
                if "/post/" in u or "editor/drafts/new" not in u: break
            print("BODY_HEAD", str(await ev("document.body.innerText"))[:300])
            return
        if PHASE == "verify":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            if "/post/" not in url: print("NEED_URL"); return
            j = await ev("""fetch(%s,{credentials:'include'}).then(r=>r.text()).then(t=>{const d=new DOMParser().parseFromString(t,'text/html');
              const art=d.querySelector('article')||d.body;
              return JSON.stringify({len:t.length,title:(d.querySelector('h1')||{}).innerText||'',
               keys:%s.map(k=>({k:k.slice(0,12),hit:art.innerText.replace(/\\s/g,'').includes(k.replace(/\\s/g,''))})),
               err:d.title.slice(0,60)});})""" % (json.dumps(url, ensure_ascii=False), json.dumps(KEYS, ensure_ascii=False)))
            print("VERIFY", j)

asyncio.run(main())
