import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("state:", zh2.counter(tab))
FIND = """[...document.querySelectorAll('.public-DraftEditor-content [data-block] img')].filter(function(im){
  var b=im.closest('[data-block]'); var p=b.previousElementSibling;
  while(p&&!p.hasAttribute('data-block')) p=p.previousElementSibling;
  return p && (p.innerText||'').indexOf('这是我觉得整套架构')===0;})[0]"""
print("found:", zh2.ev(tab, "!!(%s)" % FIND))
print("click img:", zh2.click(tab, FIND))
time.sleep(0.8)
zh2.key(tab, "Backspace", wait=2.0)
print("after:", zh2.counter(tab))
print("img blocks:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 const out=[]; const bl=[...h.querySelectorAll('[data-block]')];
 bl.forEach(function(b,i){ if(b.querySelector('img')) out.push({i, prev: bl[i-1]?(bl[i-1].innerText||'').replace(/\s+/g,' ').slice(0,30):null}); });
 return JSON.stringify(out);})()"""))
