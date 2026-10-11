import zh, json
tid = json.load(open("_zh_tid.json"))
print("focus editor:", zh.click(tid, "document.querySelector('.public-DraftEditor-content')"))
print("counter after focus:", zh.counter(tid))
print("select-all:", zh.key(tid, "A", mods=4))
print("delete:", zh.key(tid, "Backspace"))
print("CLEARED:", zh.counter(tid))
