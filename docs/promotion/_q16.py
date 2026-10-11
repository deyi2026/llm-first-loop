import zh2, json, subprocess, html as H
# markdown -> html via the repo's own converter
r = subprocess.run(["python3","md2html.py","20261010-lfl-daily-03.md","_d3.html"],capture_output=True,text=True)
print(r.stdout.strip(), r.stderr.strip()[:200])
body = open("_d3.html",encoding="utf-8").read()
print("html chars:", len(body))
tab = zh2.pick("/edit"); zh2.activate(tab)
print("grant:", zh2.grant_clipboard(tab))
open("_d3.json","w",encoding="utf-8").write(json.dumps({"html":body,"text":"x"},ensure_ascii=False))
js = r"""
(async()=>{
  const d = JSON.parse(document.querySelector('#__clipdata').textContent);
  const item = new ClipboardItem({
    'text/html': new Blob([d.html], {type:'text/html'}),
    'text/plain': new Blob([d.text], {type:'text/plain'})
  });
  await navigator.clipboard.write([item]);
  return 'WROTE ' + d.html.length;
})()
"""
# inject data without a DOM write into the editor: use a data carrier via Runtime.evaluate argument
js2 = r"""
(async(html, text) => {
  const item = new ClipboardItem({
    'text/html': new Blob([html], {type:'text/html'}),
    'text/plain': new Blob([text], {type:'text/plain'})
  });
  await navigator.clipboard.write([item]);
  return 'WROTE ' + html.length;
})
"""
import asyncio, websockets
async def run():
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=200*1024*1024) as ws:
        n=[0]
        async def s(method, params):
            n[0]+=1
            await ws.send(json.dumps({"id":n[0],"method":method,"params":params}))
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),40))
                if m.get("id")==n[0]: return m
        rr = await s("Runtime.callFunctionOn", {})
        return rr
# simpler: use Runtime.evaluate with expression built from a JS string literal
expr = js2 + "\n" + "(" + json.dumps(body, ensure_ascii=False) + ",'placeholder text')"
print("clip:", zh2.ev(tab, expr))
