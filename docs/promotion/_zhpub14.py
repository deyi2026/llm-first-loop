# -*- coding: utf-8 -*-
"""D14 知乎发布：导航 /write -> 清空 -> 贴正文 -> 图注前插两图 -> 填标题 -> 状态核对 -> 发布 -> 回读 URL"""
import asyncio, json, re, base64, os, urllib.request, websockets
CDP="http://127.0.0.1:9229"; HTML_F="20261013-lfl-daily-14.html"
TITLE="把程序从大脑降级为手脚：Agent 运行时的反直觉赌注"
def page():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        if t.get("type")=="page" and "zhuanlan.zhihu.com" in t.get("url",""): return t
    return None
def tune(h):
    h=h.replace("<strong>","<b>").replace("</strong>","</b>")
    def up(m):
        t=m.group(1)
        return "<h2>%s</h2>"%t if re.match(r'^[一二三四五六七八九十]+、|^开场',t) else "<p><b>%s</b></p>"%t
    h=re.sub(r'<p><b>([^<]{2,60})</b></p>', up, h)
    return h, re.sub(r'<[^>]+>','\n',h)
CLEAR="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');if(!ed)return 'NO_ED';
 ed.focus(); const r=document.createRange(); r.selectNodeContents(ed);
 const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); return 'CLEARED';})()"""
PASTE="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');ed.focus();
 const dt=new DataTransfer(); dt.setData('text/html',%s); dt.setData('text/plain',%s);
 ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})); return 'PASTED';})()"""
IMG="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const c=[...ed.querySelectorAll('p')].find(p=>(p.textContent||'').startsWith(%s));
 if(!c) return 'NO_ANCHOR';
 const r=document.createRange(); r.setStartBefore(c); r.setEndBefore(c);
 const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); ed.focus();
 const bin=atob(%s); const arr=new Uint8Array(bin.length);
 for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
 const dt=new DataTransfer(); dt.items.add(new File([arr],%s,{type:'image/png'}));
 ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})); return 'IMG_PASTED';})()"""
TITLEJS="""(()=>{const t=document.querySelector('textarea[placeholder*="标题"]');if(!t)return 'NO_TITLE';
 const set=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
 set.call(t,%s); t.dispatchEvent(new Event('input',{bubbles:true})); return t.value.length;})()"""
STATE="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const b=document.body.innerText;
 const pb=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='发布');
 const im=[...ed.querySelectorAll('img')];
 return JSON.stringify({counter:(b.match(/字数[：:]\\s*\\d+/)||['none'])[0], publishDisabled:pb?pb.disabled:null,
  edLen:ed.innerText.replace(/\\s/g,'').length, h2:ed.querySelectorAll('h2').length,
  imgs:im.length, loaded:im.filter(x=>x.naturalWidth>0).length, dims:im.map(x=>x.naturalWidth+'x'+x.naturalHeight),
  titleLen:(document.querySelector('textarea[placeholder*="标题"]')||{}).value.length});})()"""
async def main():
    pg=page()
    if not pg: print("NO_PAGE"); return
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        i=[0]
        async def s(m,p=None):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":m,"params":p or {}}))
            while True:
                r=json.loads(await asyncio.wait_for(ws.recv(),120))
                if r.get("id")==i[0]: return r.get("result",{})
        async def ev(e):
            r=await s("Runtime.evaluate",{"expression":e,"returnByValue":True,"awaitPromise":True})
            if "exceptionDetails" in r: return "ERR:"+json.dumps(r["exceptionDetails"],ensure_ascii=False)[:200]
            return r.get("result",{}).get("value")
        async def key(k,vk):
            b={"key":k,"code":k,"windowsVirtualKeyCode":vk,"nativeVirtualKeyCode":vk}
            await s("Input.dispatchKeyEvent",dict(b,type="keyDown")); await asyncio.sleep(0.08)
            await s("Input.dispatchKeyEvent",dict(b,type="keyUp"))
        await s("Page.bringToFront",{}); await asyncio.sleep(0.5)
        await s("Page.navigate",{"url":"https://zhuanlan.zhihu.com/write"}); await asyncio.sleep(8)
        print("URL:", await ev("location.href"))
        print("CLEAR:", await ev(CLEAR)); await asyncio.sleep(0.5); await key("Backspace",8); await asyncio.sleep(3)
        h,plain=tune(open(HTML_F,encoding="utf-8").read())
        print("PASTE:", await ev(PASTE % (json.dumps(h,ensure_ascii=False), json.dumps(plain,ensure_ascii=False))))
        await asyncio.sleep(12)
        for cap,img in [("分权：哪些判断程序绝不接手","img/fig41-power-split.png"),
                        ("自主演进的三道锁","img/fig42-evolution-locks.png")]:
            b64=base64.b64encode(open(img,"rb").read()).decode()
            print("IMG", img, await ev(IMG % (json.dumps(cap,ensure_ascii=False), json.dumps(b64), json.dumps(os.path.basename(img)))))
            await asyncio.sleep(10)
        print("TITLE:", await ev(TITLEJS % json.dumps(TITLE,ensure_ascii=False)))
        await asyncio.sleep(3)
        print("STATE:", await ev(STATE))
        print("SEQ:", await ev("""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
          const bl=[...ed.querySelectorAll('[data-block=true]')];
          return JSON.stringify(bl.map((d,n)=>n+':'+d.tagName+(d.querySelector('img')?'[IMG]':'')+':'+(d.innerText||'').replace(/\\s+/g,' ').slice(0,14)).filter(x=>x.includes('[IMG]')));})()"""))
asyncio.run(main())
