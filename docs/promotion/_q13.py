import zh2, json, asyncio
tab = zh2.pick("/edit"); zh2.activate(tab)
# clear probe
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
zh2.ev(tab, """(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return 1;})()""")
zh2.key(tab, "Backspace", wait=0.8)
print("cleared:", zh2.counter(tab))

async def type_md(tab, text, wait=0.8):
    """char-by-char; newline -> real Enter key event"""
    async def f(s):
        for seg_i, seg in enumerate(text.split("\n")):
            if seg_i:
                await s("Input.dispatchKeyEvent", {"type":"keyDown","key":"Enter","code":"Enter","windowsVirtualKeyCode":13,"modifiers":0})
                await s("Input.dispatchKeyEvent", {"type":"keyUp","key":"Enter","code":"Enter","windowsVirtualKeyCode":13,"modifiers":0})
            for chx in seg:
                await s("Input.dispatchKeyEvent", {"type":"char","text":chx,"key":chx,"modifiers":0})
    zh2._one(tab["webSocketDebuggerUrl"], f, wait=wait)
    return "OK"

probe = "# 一级标题\n\n正文一句。\n\n## 二级标题\n\n> 引用一句。\n\n- 列表一\n- 列表二\n\n**加粗片段**与`行内代码`。"
print("typing probe...", type_md(tab, probe, wait=2.0))
print("html:", zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerHTML"))
