import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
print("BEFORE:", zh2.counter(tab))
print(zh2.type_keys(tab, "## 探针标题"))
print("after md keys:", zh2.counter(tab))
print("html:", zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerHTML.slice(0,400)"))
