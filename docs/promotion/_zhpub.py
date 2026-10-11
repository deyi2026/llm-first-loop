# -*- coding: utf-8 -*-
"""知乎发布：已验证配方 bringToFront -> Range清空 -> ClipboardEvent粘贴 -> 图片粘贴"""
import sys, time, re, json, base64, asyncio, urllib.request, websockets
sys.path.insert(0,'.')
import zh2
KNOWN={"2092334918437230422","2092313733624238657","2092310847452463615"}

def ztab():
    for t in zh2.pages():
        u=t.get("url","")
        if "zhuanlan.zhihu.com" in u and not any(k in u for k in KNOWN): return t
    raise SystemExit("NO_ZHIHU_TAB")

def tune(html_path):
    h=open(html_path, encoding="utf-8").read()
    h=h.replace("<strong>","<b>").replace("</strong>","</b>")
    # 只把中文序号的章节标题提升为 h2
    def up(m):
        t=m.group(1)
        return "<h2>%s</h2>"%t if re.match(r'^[一二三四五六七八九十]+、', t) else "<p><b>%s</b></p>"%t
    h=re.sub(r'<p><b>([^<]{2,60})</b></p>', up, h)
    plain=re.sub(r'<[^>]+>','',h)
    return h, plain

def clear(tab):
    zh2.ev(tab,"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');ed.focus();
      const r=document.createRange(); r.selectNodeContents(ed);
      const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); return 1;})()""")
    time.sleep(0.4); zh2.key(tab,"Backspace"); time.sleep(2.0)

def paste_text(tab, html, plain):
    return zh2.ev(tab,"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');ed.focus();
      const dt=new DataTransfer(); dt.setData('text/html',%s); dt.setData('text/plain',%s);
      ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));return 1;})()"""
      % (json.dumps(html,ensure_ascii=False), json.dumps(plain,ensure_ascii=False)))

def paste_image(tab, path, anchor_prefix):
    b64=base64.b64encode(open(path,"rb").read()).decode()
    return zh2.ev(tab,"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
      const c=[...ed.querySelectorAll('p')].find(p=>p.textContent.startsWith(%s));
      if(!c) return 'NO_ANCHOR:'+%s;
      const r=document.createRange(); r.setStartBefore(c); r.setEndBefore(c);
      const s=window.getSelection(); s.removeAllRanges(); s.addRange(r); ed.focus();
      const bin=atob(%s); const arr=new Uint8Array(bin.length);
      for(let i=0;i<bin.length;i++) arr[i]=bin.charCodeAt(i);
      const dt=new DataTransfer(); dt.items.add(new File([arr],%s,{type:'image/png'}));
      ed.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true}));return 1;})()"""
      % (json.dumps(anchor_prefix), json.dumps(anchor_prefix[:14]), json.dumps(b64), json.dumps(path.split("/")[-1])))

STATE="""(()=>{const ed=document.querySelector('.public-DraftEditor-content');const t=document.body.innerText;
 const pb=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='发布');
 return JSON.stringify({counter:(t.match(/字数[：:]\\s*\\d+/)||['none'])[0],
  publishDisabled:pb?pb.disabled:null, edLen:ed?ed.innerText.replace(/\\s/g,'').length:null,
  h2:ed?ed.querySelectorAll('h2').length:null, quote:ed?ed.querySelectorAll('blockquote').length:null,
  imgs:ed?ed.querySelectorAll('img').length:null,
  loaded:ed?[...ed.querySelectorAll('img')].filter(i=>i.naturalWidth>0).length:null,
  title:(document.querySelector('textarea[placeholder*="标题"]')||{}).value},null,0);})()"""
