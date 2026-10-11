import zh2, json, os, time
from _ins import caret_to, insert_image
tab = zh2.pick("/edit"); zh2.activate(tab)
print("before:", zh2.counter(tab))
print(json.dumps(insert_image(tab, os.path.abspath("img/fig11-three-state-layers.png"), "哲学一：事实是一种有结构的"), ensure_ascii=False)[:400])
print("after:", zh2.counter(tab))
