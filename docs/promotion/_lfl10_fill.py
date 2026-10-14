# -*- coding: utf-8 -*-
"""LFL第10期头条填充：标题+正文paste+8图+AI声明（不发布）。复用 D13/D14 链路。"""
import asyncio, json, base64, urllib.request, websockets

CDP = "http://127.0.0.1:9229"
BASE = "~/Project/llm-first-loop-mirror/outputs/lfl-article"
BODY_HTML = open(BASE + "/toutiao-body.html", encoding="utf-8").read()
TITLE = 'AI 说"改好了"却没改？这个开源项目，专治智能体撒谎'
# (锚点正则-插到该元素之后, 图片绝对路径)
IMGS = [
    (r"^它叫 ", BASE + "/assets/img0_banner.png"),
    (r"^官方给它的定位就一句话", BASE + "/assets/img1_positioning.png"),
    (r"^在 LFL 里，每条消息进来", BASE + "/assets/img2_core_loop.png"),
    (r"^程序层：安全硬边界", BASE + "/assets/img3_three_layers.png"),
    (r"^传统 Agent 出错", BASE + "/assets/img4_honesty.png"),
    (r"^昨天的事今天忘", BASE + "/assets/img6_memory.png"),
    (r"^LFL 会基于自评发起演进建议", BASE + "/assets/img5_evolution.png"),
    (r"^浏览器接管", BASE + "/assets/img7_capabilities.png"),
]

def mp_pages():
    d = json.load(urllib.request.urlopen(CDP + "/json"))
    return [t for t in d if t.get("type") == "page" and "mp.toutiao.com" in t.get("url", "")]

async def connect(t):
    ws = await websockets.connect(t["webSocketDebuggerUrl"], max_size=200 * 1024 * 1024)
    i = [0]
    async def cmd(method, params=None):
        i[0] += 1
        await ws.send(json.dumps({"id": i[0], "method": method, "params": params or {}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == i[0]:
                if "error" in m: raise RuntimeError(method + " -> " + str(m["error"]))
                return m.get("result", {})
    async def ev(e):
        r = await cmd("Runtime.evaluate", {"expression": e, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in r: return "ERR:" + str(r["exceptionDetails"].get("text"))
        return r.get("result", {}).get("value")
    return ws, cmd, ev

async def main():
    # 阶段1：挑一个 mp 页导航到 publish
    cands = [t for t in mp_pages() if "profile_v4/graphic/articles" in t.get("url", "")] or mp_pages()
    if not cands:
        print("NO_MP_PAGE"); return
    t = cands[0]
    ws, cmd, ev = await connect(t)
    print("NAV:", await cmd("Page.navigate", {"url": "https://mp.toutiao.com/profile_v4/graphic/publish"}))
    await asyncio.sleep(2)
    await ws.close()
    await asyncio.sleep(8)

    # 阶段2：重连 publish 页
    pg = [t2 for t2 in mp_pages() if "profile_v4/graphic/publish" in t2.get("url", "")]
    if not pg:
        print("NO_PUBLISH_PAGE_AFTER_NAV"); return
    t = pg[0]
    ws, cmd, ev = await connect(t)
    print("PAGE:", t["url"][:90])

    # 等编辑器就绪
    for _ in range(20):
        if await ev("!!document.querySelector('.ProseMirror[contenteditable]')") == True:
            break
        await asyncio.sleep(1)
    print("PM_READY:", await ev("!!document.querySelector('.ProseMirror[contenteditable]')"))

    # 清空旧内容（保险）
    print("CLEAR:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
      if(ta){const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
        s.call(ta,''); ta.dispatchEvent(new Event('input',{bubbles:true}));}
      const pm=document.querySelector('.ProseMirror[contenteditable]');
      if(pm){pm.focus(); const sel=window.getSelection(); const r=document.createRange();
        r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
        document.execCommand('delete');}
      return 'CLEARED';})()"""))
    await asyncio.sleep(1)

    # 标题
    print("TITLE:", await ev("""(()=>{const ta=document.querySelector('textarea[placeholder*="标题"]');
      if(!ta) return 'NO_TA';
      const s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
      s.call(ta, %s); ta.dispatchEvent(new Event('input',{bubbles:true}));
      return 'SET len='+ta.value.length;})()""" % json.dumps(TITLE)))

    # 正文 paste
    html = json.dumps(BODY_HTML)
    plain = json.dumps(BODY_HTML.replace("<", " ").replace(">", " ")[:6000])
    print("PASTE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
      if(!pm) return 'NO_PM';
      const dt=new DataTransfer(); dt.setData('text/html',%s); dt.setData('text/plain',%s);
      pm.focus(); const sel=window.getSelection(); const r=document.createRange();
      r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
      pm.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));
      return 'DISPATCHED';})()""" % (html, plain)))
    await asyncio.sleep(4)
    print("BLOCKS:", await ev("document.querySelectorAll('.ProseMirror > *').length"))

    # 逐张插图：锚段末尾定位光标 -> 工具栏图片按钮 -> setFileInputFiles -> 轮询 -> 确定
    async def insert_after(pat, img_path):
        pos = await ev("""((pat)=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const hit=[...pm.querySelectorAll('p,li,h2')].find(n=>new RegExp(pat).test((n.innerText||'').trim()));
          if(!hit) return 'NO_ANCHOR';
          hit.scrollIntoView({block:'center'});
          const r=hit.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.left+30), y:Math.round(r.top+r.height/2), txt:hit.innerText.slice(0,20)});})()""" ,
          json.dumps(pat) if False else pat)  # ev 直接传参不便，改用字符串拼接
        return pos
    # 上面受 ev 单参数限制，改回字符串拼接方式
    async def insert_after2(pat, img_path, idx):
        js = """(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const hit=[...pm.querySelectorAll('p,li,h2')].find(n=>new RegExp(%s).test((n.innerText||'').trim()));
          if(!hit) return 'NO_ANCHOR';
          hit.scrollIntoView({block:'center'});
          const r=hit.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.left+30), y:Math.round(r.top+r.height/2), txt:hit.innerText.slice(0,20)});})()""" % json.dumps(pat)
        pos = await ev(js)
        print(f"[图{idx}] ANCHOR:", pos)
        if not str(pos).startswith("{"):
            return False
        c = json.loads(pos)
        for ty in ("mousePressed", "mouseReleased"):
            await cmd("Input.dispatchMouseEvent", {"type": ty, "x": c["x"], "y": c["y"], "button": "left", "clickCount": 1})
        await asyncio.sleep(1)
        await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "End", "code": "End", "windowsVirtualKeyCode": 35, "nativeVirtualKeyCode": 35})
        await cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": "End", "code": "End", "windowsVirtualKeyCode": 35, "nativeVirtualKeyCode": 35})
        await asyncio.sleep(1)
        print(f"[图{idx}] BTN:", await ev("""(()=>{const b=document.querySelector('.syl-toolbar-tool.image .syl-toolbar-button');
          if(!b) return 'NO'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(3)
        # 等文件输入框出现并 set 文件；失败重试一轮
        for attempt in range(2):
            doc = await cmd("DOM.getDocument")
            q = await cmd("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": ".btn-upload-handle input[type=file], input[type=file]"})
            nid = q.get("nodeId")
            if not nid:
                print(f"[图{idx}] NO_FILE_INPUT"); return False
            print(f"[图{idx}] SET:", await cmd("DOM.setFileInputFiles", {"nodeId": nid, "files": [img_path]}))
            done = False
            for k in range(30):
                st = await ev("""(()=>{const t=document.body.innerText;
                  const failM=t.match(/上传失败[^\\d]*(\\d+)/); const fail=failM?parseInt(failM[1]):0;
                  const done=t.includes('已上传 1');
                  const btns=[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='确定'&&b.offsetParent);
                  const b=btns[btns.length-1];
                  return JSON.stringify({done, fail, btn:(b?(b.disabled?'disabled':'enabled'):'none')});})()""")
                s = json.loads(st) if str(st).startswith("{") else {}
                if s.get("fail", 0) > 0:
                    break
                if s.get("done") and s.get("btn") == "enabled":
                    print(f"[图{idx}] CONFIRM:", await ev("""(()=>{const btns=[...document.querySelectorAll('button')].filter(b=>b.textContent.trim()==='确定'&&b.offsetParent);
                      btns[btns.length-1].click(); return 'CLICKED';})()"""))
                    done = True
                    break
                await asyncio.sleep(1)
            if done:
                break
            print(f"[图{idx}] 上传未完成(fail>0或超时)，重试 {attempt+1}/2")
            await asyncio.sleep(2)
        await asyncio.sleep(5)
        return done

    print("IMGS_BEFORE:", await ev("document.querySelectorAll('.ProseMirror img').length"))
    for i, (pat, path) in enumerate(IMGS):
        await insert_after2(pat, path, i)

    # AI 声明
    print("AI_LABELS:", await ev("""JSON.stringify([...document.querySelectorAll('label.byte-checkbox')].map(l=>({t:l.innerText.trim().slice(0,30), c:l.querySelector('input[type=checkbox]')?.checked})))"""))
    print("AI_CLICK:", await ev("""(()=>{const ls=[...document.querySelectorAll('label.byte-checkbox')];
      const hit=ls.find(l=>/AI/.test(l.innerText));
      if(!hit) return 'NO_AI_LABEL';
      const inp=hit.querySelector('input[type=checkbox]');
      if(inp.checked) return 'ALREADY';
      inp.click(); return 'CLICKED';})()"""))
    await asyncio.sleep(1)
    print("AI_AFTER:", await ev("""JSON.stringify([...document.querySelectorAll('label.byte-checkbox')].map(l=>({t:l.innerText.trim().slice(0,30), c:l.querySelector('input[type=checkbox]')?.checked})))"""))

    # 终态校验 + 截图
    print("FINAL:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
      const im=[...pm.querySelectorAll('img')];
      const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
      return JSON.stringify({imgs:im.length, dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
        words:wc?wc[1]:null, blocks:pm.children.length,
        head:(pm.innerText||'').replace(/\\s+/g,' ').slice(0,60),
        tail:(pm.innerText||'').replace(/\\s+/g,' ').slice(-60)});})()"""))
    shot = await cmd("Page.captureScreenshot", {"format": "png"})
    open(BASE + "/toutiao-preview.png", "wb").write(base64.b64decode(shot["data"]))
    print("SCREENSHOT: saved")
    await ws.close()

asyncio.run(main())
