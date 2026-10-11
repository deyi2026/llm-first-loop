import zh2, json, os
tab = zh2.pick("/edit"); zh2.activate(tab)
print("files on md input:", zh2.ev(tab, r"""(()=>{const i=[...document.querySelectorAll('input[type=file]')].find(x=>x.accept.includes('.md'));
 return i?JSON.stringify({n:i.files.length,name:i.files[0]&&i.files[0].name,size:i.files[0]&&i.files[0].size}):'none';})()"""))
print("dispatch change:", zh2.ev(tab, r"""(()=>{const i=[...document.querySelectorAll('input[type=file]')].find(x=>x.accept.includes('.md'));
 if(!i) return 'none'; i.dispatchEvent(new Event('input',{bubbles:true})); i.dispatchEvent(new Event('change',{bubbles:true})); return 'dispatched';})()"""))
import time; time.sleep(4)
print("AFTER:", zh2.counter(tab))
