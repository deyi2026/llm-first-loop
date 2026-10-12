import zh2, json
tab = zh2.pick("/edit")
print("TAB:", tab["url"][:70], tab["id"][:12])
print("activate:", zh2.activate(tab))
print("counter before:", zh2.counter(tab))
print("click body:", zh2.click(tab, "document.querySelector('.public-DraftEditor-content')"))
print("activeElement:", zh2.ev(tab, "document.activeElement.className"))
print("typ ZZ:", zh2.typ(tab, "ZZ", wait=1.0))
print("counter after:", zh2.counter(tab))
