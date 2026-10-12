import _cdp, json, urllib.request, time
# 在现有标签里直接 fetch 线上文章（走页面 fetch，不受工具白名单限制）
JS = r"""
(async()=>{
  const r = await fetch('https://zhuanlan.zhihu.com/p/2092334918437230422',{credentials:'include'});
  const h = await r.text();
  const d = new DOMParser().parseFromString(h,'text/html');
  const art = d.querySelector('article') || d.body;
  const txt = art.innerText;
  const ps = [...art.querySelectorAll('p,h1,h2,h3,li,blockquote,pre,img')];
  return JSON.stringify({
    status: r.status,
    title: (d.querySelector('h1')||{}).innerText || '',
    len: txt.replace(/\s/g,'').length,
    lines: art.querySelectorAll('p').length,
    h1: art.querySelectorAll('h1').length,
    h2: art.querySelectorAll('h2').length,
    h3: art.querySelectorAll('h3').length,
    li: art.querySelectorAll('li').length,
    pre: art.querySelectorAll('pre').length,
    img: art.querySelectorAll('img').length,
    imgSrcs: [...art.querySelectorAll('img')].map(i=>i.src).filter(s=>s.includes('pic')).slice(0,8),
    literalMd: {
      '##': (txt.match(/^#{1,3} /gm)||[]).length,
      'boldAst': (txt.match(/\*\*/g)||[]).length,
      'gt': (txt.match(/^> /gm)||[]).length,
      'pipeTable': (txt.match(/\|---/g)||[]).length,
      'backtick': (txt.match(/`/g)||[]).length
    },
    head: txt.replace(/\s+/g,' ').slice(0,160),
    tail: txt.replace(/\s+/g,' ').slice(-200)
  },null,1);
})()
"""
print(_cdp.ev(_cdp.pick("zhihu.com/creator"), JS))
