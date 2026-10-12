import zh2, json, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
p = os.path.abspath("img/fig11-three-state-layers.png")
print("upload:", zh2.upload_image(tab, [p], wait=8.0))
print("counter:", zh2.counter(tab))
print("shot:", zh2.shot(tab, "_zh_up2.png"))
