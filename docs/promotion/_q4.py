import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
print("BEFORE:", zh2.counter(tab))
lines = open("20261010-lfl-daily-03.md", encoding="utf-8").read().split("\n")
body = "\n".join(lines[1:]).lstrip("\n")          # drop the H1 title line
probe = "\n".join(body.split("\n")[:12])
print("probe chars:", len(probe))
print("--- probe text ---"); print(probe); print("--- end ---")
print("insert:", zh2.typ(tab, probe, wait=2.5))
print("AFTER:", zh2.counter(tab))
print("html:", zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerHTML.slice(0,700)"))
