# -*- coding: utf-8 -*-
"""发布前逐段校验：源 markdown 实义段vs 编辑器实际段。归一化加粗/书名号/引号。"""
import asyncio, json, re, urllib.request, websockets
CDP="http://127.0.0.1:9229"
MD="20261010-lfl-daily-03.md"

def norm(s):
    s=re.sub(r'[*`>\[\]()#|_-]','',s)
    s=re.sub(r'\*\*','',s)
    s=re.sub(r'[《》“”"\'\'‘’]','',s)
    s=re.sub(r'[，,。.：:；;、！!？?（）()【】\[\]…—\-·]','',s)
    return re.sub(r'\s+','',s)

def units(md):
    out=[]
    body=md.split("\n",1)[1]
    for ln in body.split("\n"):
        ln=ln.strip()
        if not ln or re.match(r'^(---|\*\*\*)$',ln): continue
        ln=re.sub(r'^#{1,6}\s*','',ln); ln=re.sub(r'^>\s*','',ln)
        ln=re.sub(r'^[-*]\s+','',ln); ln=re.sub(r'^\d+\.\s+','',ln)
        n=norm(ln)
        if len(n)>=8: out.append(n)
    return out

def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "toutiao" in t.get("url","")]

async def main():
    us=units(open(MD,encoding="utf-8").read())
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        got=await ev("document.querySelector('.ProseMirror[contenteditable]').innerText")
    g=norm(got)
    miss=[u for u in us if u not in g]
    print("源实义段:",len(us),"缺失:",len(miss))
    for m in miss[:8]: print("  MISS:", m[:70])
    # 串内容检测：文章不应出现别的主题关键词
    for bad in ["持久化勃起","安全套","延时喷剂"]:
        if bad in got: print("  !!! 串内容:", bad)
    print("OK" if not miss else "HAS_MISSING")
asyncio.run(main())
