import zh2, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
p = os.path.abspath("20261010-lfl-daily-03.md")
print("set_file2:", zh2.set_file2(tab, "[...document.querySelectorAll('input[type=file]')].find(x=>x.accept.includes('.md'))", [p]))
print("AFTER:", zh2.counter(tab))
print("btns:", zh2.ev(tab, "JSON.stringify([...document.querySelectorAll('button')].map(b=>({t:(b.innerText||'').replace(/\\s/g,'').slice(0,10),d:b.disabled})).filter(x=>x.t))"))
