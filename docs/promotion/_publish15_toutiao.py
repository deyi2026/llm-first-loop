# -*- coding: utf-8 -*-
"""D15 Toutiao: explicit PREPARE and PUBLISH phases, based on D14 verified path."""
import asyncio
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path
from md2html import convert
import websockets

HERE = Path(__file__).resolve().parent
CDP = "http://127.0.0.1:9229"
TITLE = "问一句，后台跑了几次？Agent 的隐形账本"
ARTICLE = HERE / "20261013-lfl-daily-15.md"
IMAGES = [
    (43, "fig43-one-prompt-many-calls.png"),
    (44, "fig44-logical-vs-physical.png"),
    (45, "fig45-cache-not-free.png"),
    (46, "fig46-four-denominators.png"),
    (47, "fig47-receipt-evidence-states.png"),
    (48, "fig48-six-questions.png"),
]
MARK = "profile_v4/graphic/publish"
URL = "https://mp.toutiao.com/" + MARK
PHASE = sys.argv[1] if len(sys.argv) > 1 else "inspect"
assert PHASE in ("inspect", "prepare", "mark", "publish")

def targets():
    return json.load(urllib.request.urlopen(CDP + "/json"))

def target():
    matches = [t for t in targets() if t.get("type") == "page" and MARK in t.get("url", "")]
    if matches: return matches[-1]
    if PHASE == "inspect": return None
    req = urllib.request.Request(CDP + "/json/new?" + urllib.parse.quote(URL, safe=""), method="PUT")
    t = json.load(urllib.request.urlopen(req, timeout=10))
    assert t["type"] == "page"
    return t

def article_html():
    a = ARTICLE.read_text()
    assert a.splitlines()[0] == "# " + TITLE
    # Reuse platform-trusted formatting, but upload actual images through the site's picker.
    body = a.split("\n", 1)[1]
    body = re.sub(r"(?m)^!\[[^\n]*\]\(img/[^)]*\.png\)[ \t]*\n?", "", body)
    assert "![" not in body
    h = convert(body)
    assert all(f"图 {n}｜" in h for n, _ in IMAGES)
    (HERE / "20261013-lfl-daily-15.html").write_text(h)
    return h

async def main():
    t = target()
    if not t:
        print("NO_TOUTIAO_EDITOR"); return
    print("CDP_EDITOR", t["url"])
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=90_000_000) as ws:
        seq = 0
        async def cmd(method, params=None):
            nonlocal seq
            seq += 1
            await ws.send(json.dumps({"id":seq,"method":method,"params":params or {}}, ensure_ascii=False))
            while True:
                r = json.loads(await asyncio.wait_for(ws.recv(), 90))
                if r.get("id") == seq:
                    if "error" in r: raise RuntimeError(method+": "+str(r["error"]))
                    return r.get("result", {})
        async def ev(script):
            r = await cmd("Runtime.evaluate", {"expression":script,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:400])
            return r.get("result", {}).get("value")
        async def state():
            s=await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]'),
              ta=document.querySelector('textarea[placeholder*="标题"]'); const imgs=pm?[...pm.querySelectorAll('img')]:[];
              const b=document.body.innerText; const count=b.match(/共\\s*(\\d+)\\s*字/);
              const labs=[...document.querySelectorAll('label.byte-checkbox')].map(l=>({
                text:(l.innerText||'').trim(), checked:(l.querySelector('input')||{}).checked}));
              return JSON.stringify({url:location.href,hasEditor:!!pm,title:ta?ta.value:null,
               words:count?+count[1]:null,imgs:imgs.length,
               uniqImgs:new Set(imgs.filter(i=>i.naturalWidth>0).map(i=>i.src)).size,
               realImgs:imgs.filter(i=>i.naturalWidth>0).length,
               sizes:imgs.map(i=>i.naturalWidth+'x'+i.naturalHeight),
               bodyStart:(pm?.innerText||'').slice(0,75),
               bodyEnd:(pm?.innerText||'').slice(-125),
               ai:labs.filter(l=>l.text.includes('引用AI'))});})()""")
            print("STATE",s)
            return json.loads(s)
        if PHASE == "inspect":
            await state(); return
        if "/profile_v4/graphic/publish" not in str(await ev("location.href")):
            await asyncio.sleep(6)
        if "/profile_v4/graphic/publish" not in str(await ev("location.href")):
            print("NOT_EDITOR_OR_LOGIN_REDIRECT",await ev("location.href")); return
        if PHASE == "prepare":
            current=await state()
            if current["title"] and current["title"] != TITLE:
                print("EDITOR_HAS_FOREIGN_DRAFT_STOP", current["title"]); return
            if current["title"] == TITLE and current["realImgs"] > 0:
                print("EXISTING_D15_DRAFT_REUSE_WITHOUT_RESET");return
            h = article_html()
            plain = re.sub(r"<[^>]+>", " ", h)
            print("HTML",len(h),"IMAGES_EXPECTED",len(IMAGES))
            print("CLEAR",await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]'),
              pm=document.querySelector('.ProseMirror[contenteditable]');
              if(!ta||!pm)return 'NO_EDITOR';
              const s=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
              s.call(ta,'');ta.dispatchEvent(new Event('input',{bubbles:true}));
              pm.focus();const r=document.createRange();r.selectNodeContents(pm);
              const sel=window.getSelection();sel.removeAllRanges();sel.addRange(r);
              document.execCommand('delete');return 'CLEARED';})()"""))
            print("TITLE",await ev("""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');
              const set=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;
              set.call(t,%s);t.dispatchEvent(new Event('input',{bubbles:true}));return t.value.length;})()""" %
              json.dumps(TITLE,ensure_ascii=False)))
            print("PASTE",await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
              const dt=new DataTransfer();dt.setData('text/html',%s);dt.setData('text/plain',%s);
              pm.focus();const r=document.createRange();r.selectNodeContents(pm);
              const s=window.getSelection();s.removeAllRanges();s.addRange(r);
              pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
              return 'DISPATCHED';})()""" % (json.dumps(h,ensure_ascii=False),
                                         json.dumps(plain,ensure_ascii=False))))
            await asyncio.sleep(3)
            await state()
            for fig,name in IMAGES:
                print("INSERT_START", fig, name, flush=True)
                anchor=await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]'),
                  p=[...pm.querySelectorAll('p')].find(x=>(x.innerText||'').trim().includes(%s));
                  if(!p)return 'MISSING_FIG_CAPTION'; p.scrollIntoView({block:'center'});
                  pm.focus();const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
                  const s=window.getSelection();s.removeAllRanges();s.addRange(r);
                  return p.innerText.slice(0,55);})()""" % json.dumps("图 "+str(fig)+"｜",ensure_ascii=False))
                print("ANCHOR", anchor)
                if anchor == "MISSING_FIG_CAPTION": break
                print("IMAGE_BUTTON",await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
                  if(!b)return 'NO_IMAGE_BUTTON';b.click();return 'CLICKED';})()"""))
                await asyncio.sleep(2)
                doc=await cmd("DOM.getDocument")
                n=await cmd("DOM.querySelector",{"nodeId":doc["root"]["nodeId"],
                                                "selector":".btn-upload-handle input[type=file]"})
                nid=n.get("nodeId")
                if not nid: print("NO_FILE_INPUT_STOP"); break
                print("FILE_SENT",await cmd("DOM.setFileInputFiles",
                                          {"nodeId":nid,"files":[str(HERE/"img"/name)]}))
                ready=False
                for attempt in range(12):
                    await asyncio.sleep(2)
                    j=await ev("""(()=>{const txt=document.body.innerText;
                      const m=txt.match(/已上传\\s*(\\d+)\\s*张/);
                      const fail=(txt.match(/上传失败/g)||[]).length;
                      const b=[...document.querySelectorAll('button')].filter(x=>x.textContent.trim()==='确定');
                      return JSON.stringify({up:m?+m[1]:0,fail:fail,confirm:b.some(x=>!x.disabled)});})()""")
                    d=json.loads(j); print("UPLOAD_STATUS",fig,attempt+1,d,flush=True)
                    if d["up"]>=1 and d["fail"]==0 and d["confirm"]: ready=True; break
                    if d["fail"]>0: break
                if not ready:
                    print("UPLOAD_FAILED_STOP",fig); return
                print("CONFIRM",await ev("""(()=>{const b=[...document.querySelectorAll('button')]
                 .find(x=>x.textContent.trim()==='确定'&&!x.disabled);
                 if(!b)return 'NO_CONFIRM';b.click();return 'CLICKED';})()"""))
                await asyncio.sleep(3)
                s=await state()
                if s["realImgs"] < (fig-42):
                    print("IMAGE_NOT_INSERTED_STOP",fig);return
            s=await state()
            if s["uniqImgs"] != 6: print("SIX_IMAGES_NOT_READY_STOP"); return
            print("AI_MARK",await ev("""(()=>{const lab=[...document.querySelectorAll('label.byte-checkbox')]
              .find(x=>(x.innerText||'').includes('引用AI'));
              if(!lab)return 'NO_AI_DECLARATION'; const b=lab.querySelector('input');
              if(!b)return 'NO_AI_CHECKBOX'; if(!b.checked)b.click();
              return b.checked?'ON':'OFF';})()"""))
            print("D15_PREPARE_DONE",await state())
            return
        if PHASE == "mark":
            s=await state()
            if s["title"] != TITLE or s["uniqImgs"] != 6:
                print("MARK_GATE_FAIL",s);return
            print("AI_MARK",await ev("""(()=>{const lab=[...document.querySelectorAll('label.byte-checkbox')]
              .find(x=>(x.innerText||'').includes('引用AI'));
              if(!lab)return 'NO_AI_DECLARATION'; const b=lab.querySelector('input');
              if(!b)return 'NO_AI_CHECKBOX'; if(!b.checked)b.click();
              return b.checked?'ON':'OFF';})()"""))
            await state();return
        # Publication is a separate command, never automatically coupled to preparation.
        if PHASE == "publish":
            s=await state()
            if s["title"]!=TITLE or s["uniqImgs"]!=6 or len(s["bodyEnd"])<80 or not any(x["checked"] for x in s["ai"]):
                print("PUBLISH_PRE_GATE_FAIL", s); return
            print("PREVIEW",await ev("""(()=>{const b=[...document.querySelectorAll('button')]
             .find(x=>x.textContent.trim()==='预览并发布'); if(!b||b.disabled)return 'NO_BTN';b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(4)
            print("PUBLISH_CONFIRM",await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.textContent.trim()==='确认发布');if(!b||b.disabled)return 'NO_CONFIRM';
              b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(7)
            print("AFTER_SUBMIT_URL",await ev("location.href"))
            print("AFTER_SUBMIT_BODY",str(await ev("document.body.innerText"))[-700:])

asyncio.run(main())
