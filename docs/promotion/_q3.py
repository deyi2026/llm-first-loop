import zh2, json, asyncio, websockets
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
print("selectAllChildren:", zh2.ev(tab, r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return s.toString().length;})()"""))
print("delete:", zh2.key(tab, "Backspace", wait=1.0))
c = zh2.counter(tab); print("AFTER:", c)
if c["len"] > 0:
    print("-- fallback: repeated Backspace --")
    async def many(s, n):
        c = {"modifiers":0,"key":"Backspace","code":"Backspace","windowsVirtualKeyCode":8}
        for _ in range(n):
            await s("Input.dispatchKeyEvent", dict(c, type="keyDown"))
            await s("Input.dispatchKeyEvent", dict(c, type="keyUp"))
    zh2._one(tab["webSocketDebuggerUrl"], lambda s: many(s, 200), wait=1.5)
    print("AFTER NUKES:", zh2.counter(tab))
