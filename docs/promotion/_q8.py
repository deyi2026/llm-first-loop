import zh2, json, os
tab = zh2.pick("/edit"); zh2.activate(tab)
p = os.path.abspath("20261010-lfl-daily-03.md")
print("file:", p, os.path.getsize(p))
print("BEFORE:", zh2.counter(tab))
print("setFileInputFiles:", zh2.set_file(tab, 'input[type=file][accept*=".md"]', [p]))
print("AFTER:", zh2.counter(tab))
print("html head:", zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerHTML.slice(0,400)"))
