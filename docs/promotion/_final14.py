import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def page(sub, excl=None):
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    for t in d:
        u=t.get("url","")
        if t.get("type")=="page" and sub in u and (not excl or excl not in u): return t
JS=r"""(async()=>{
 const out={};
 const urls={'toutiao':'https://www.toutiao.com/article/7696133427334070825/','zhihu':'https://zhuanlan.zhihu.com/p/2093444801823760655'};
 for(const k in urls){
   const r=await fetch(urls[k],{credentials:'include'});
   const h=await r.text(); const d=new DOMParser().parseFromString(h,'text/html');
   const art=d.querySelector('article')||d.body; const t=art.innerText||'';
   const heads=(t.match(/(开场：一个让工程师难受的设计|一、先说清楚|二、五步循环|三、反直觉的核心|四、它敢让自己改自己|五、诚实的边界|六、未来趋势判断|七、需要攻克的技术方向|八、现在该怎么看它)/g)||[]).length;
   out[k]={status:r.status,title:(d.querySelector('h1')||{}).innerText||'',chars:t.replace(/\s/g,'').length,
     heads,cap1:t.includes('分权：哪些判断程序绝不接手'),cap2:t.includes('自主演进的三道锁'),
     b3:t.includes('不对这个数字背书'),p0:t.includes('P0*'),ai:t.includes('未经人工事实核验'),
     img_nodes:art.querySelectorAll('img').length};
 }
 return JSON.stringify(out);})()"""
async def main():
    pg=page("toutiao.com","mp.toutiao")
    async with websockets.connect(pg["webSocketDebuggerUrl"],max_size=400*1024*1024) as ws:
        await ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":JS,"returnByValue":True,"awaitPromise":True}}))
        while True:
            r=json.loads(await asyncio.wait_for(ws.recv(),90))
            if r.get("id")==1:
                res=r.get("result",{})
                v=res.get("result",{}).get("value")
                print(v)
                o=json.loads(v) if v else {}
                for k,val in o.items():
                    ok = val.get("status")==200 and val.get("heads",0)>=9 and all(val.get(c) for c in ("cap1","cap2","b3","p0","ai"))
                    print(f"{k}: {'PASS' if ok else 'FAIL'} {val}")
                return
asyncio.run(main())
