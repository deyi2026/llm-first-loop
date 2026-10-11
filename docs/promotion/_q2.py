import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
print("counter now:", zh2.counter(tab))
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
print("selectAll(Meta+A):", zh2.key(tab, "A", mods=4))
print("selText:", zh2.ev(tab, "window.getSelection().toString().slice(0,50)"))
print("delete:", zh2.key(tab, "Backspace", wait=1.0))
print("CLEARED:", zh2.counter(tab))
print("textContent len:", zh2.ev(tab, "(document.querySelector('.public-DraftEditor-content')||{}).textContent.length"))
