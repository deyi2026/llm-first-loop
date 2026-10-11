import _cdp, time
t = _cdp.pick("zhihu.com/creator")
print("confirm:", _cdp.click_expr(t, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='确认' && b.getBoundingClientRect().height>0)"))
time.sleep(3)
JS = r"""
(()=>{
  const cards=[...document.querySelectorAll('div.CreationManage-CreationCard')];
  return JSON.stringify({
    count: cards.length,
    arts: cards.map(c=>(c.querySelector('a[href*="/p/"]')||{}).href||''),
    brokenStillThere: document.body.innerHTML.includes('2092328791062401746'),
    header: (document.body.innerText.match(/共\s*\d+\s*条内容/)||[null])[0]
  },null,1);
})()
"""
print(_cdp.ev(t, JS))
