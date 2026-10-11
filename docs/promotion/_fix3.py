import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
FIND = """[...document.querySelectorAll('.public-DraftEditor-content [data-block] img')].filter(function(im){
  var b=im.closest('[data-block]'); var p=b.previousElementSibling;
  while(p&&!p.hasAttribute('data-block')) p=p.previousElementSibling;
  return p && (p.innerText||'').indexOf('这是我觉得整套架构')===0;})[0]"""
print("scroll+click:", zh2.click(tab, "(()=>{var im=(%s); if(im){im.closest('[data-block]').scrollIntoView({block:'center'});} return im;})()" % FIND))
time.sleep(1.0)
print("click2:", zh2.click(tab, FIND))
time.sleep(0.8)
print("sel:", zh2.ev(tab, "JSON.stringify({hasRange:!!window.getSelection().rangeCount, txt:window.getSelection().toString().length})"))
zh2.key(tab, "Backspace", wait=2.5)
print("after:", zh2.counter(tab))
