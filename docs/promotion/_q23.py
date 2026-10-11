import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("dispatch:", zh2.ev(tab, r"""(()=>{const i=[...document.querySelectorAll('input[type=file]')].filter(x=>x.accept.includes('image')).pop();
 if(!i||!i.files.length) return 'no files';
 i.dispatchEvent(new Event('input',{bubbles:true}));
 i.dispatchEvent(new Event('change',{bubbles:true}));
 return 'dispatched n='+i.files.length;})()"""))
for i in range(4):
    time.sleep(4)
    print(i, zh2.counter(tab))
print("shot:", zh2.shot(tab, "_zh_up.png"))
