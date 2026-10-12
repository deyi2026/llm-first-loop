import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
for i in range(2):
    zh2.cmd_key(tab, "z", "KeyZ", 90, ["undo"], wait=1.5)
print("after undo:", zh2.counter(tab))
print("imgs:", zh2.ev(tab, "document.querySelectorAll('.public-DraftEditor-content img').length"))
