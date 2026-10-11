import _cdp
t = _cdp.pick("zhihu.com/creator")
FIND = """[...document.querySelectorAll('div.CreationManage-CreationCard')]
  .find(c => c.querySelector('a[href*="/p/2092328791062401746"]'))"""
BTN = "(%s).querySelectorAll('button')" % FIND
print("card count:", _cdp.ev(t, "document.querySelectorAll('div.CreationManage-CreationCard').length"))
print("card found:", _cdp.ev(t, "!!(%s)" % FIND))
print("btn texts:", _cdp.ev(t, "JSON.stringify([...%s].map(b=>b.innerText.trim()))" % BTN))
print("more-click:", _cdp.click_expr(t, "[...%s].find(b=>b.innerText.includes('更多'))" % BTN))
