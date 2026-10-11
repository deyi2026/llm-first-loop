import _cdp
JS = r"""
(()=>{
  const cards = [...document.querySelectorAll('div.CreationManage-CreationCard')];
  const out = cards.map((c,i) => ({
    i,
    art: (c.querySelector('a[href*="/p/"]')||{}).href || '',
    head: c.innerText.replace(/\s+/g,' ').slice(0,60),
    allBtns: [...c.querySelectorAll('button,[class*="More"],[class*="more"],[class*="Operate"],[class*="operation"]')]
       .map(b => ({tag:b.tagName, cls:String(b.className).slice(0,45),
                   txt:(b.innerText||'').trim().slice(0,14),
                   aria:b.getAttribute('aria-label')||b.getAttribute('title')||'',
                   vis: b.offsetParent!==null}))
  }));
  return JSON.stringify({count:cards.length, out}, null, 1);
})()
"""
_cdp.run(_cdp.pick("zhihu.com/creator"), JS)
