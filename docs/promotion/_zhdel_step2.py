import _cdp
t = _cdp.pick("zhihu.com/creator")
JS = r"""
(()=>{
  const items=[...document.querySelectorAll('div,li,span,button,a')]
    .filter(e=>{const r=e.getBoundingClientRect(); return r.width>0&&r.height>0&&r.height<60&&e.children.length===0;})
    .map(e=>({tag:e.tagName, txt:e.innerText.trim().slice(0,20), x:Math.round(e.getBoundingClientRect().left), y:Math.round(e.getBoundingClientRect().top)}))
    .filter(o=>o.txt && ['删除','编辑','分享','举报','权限','置顶','预览','复制链接'].some(k=>o.txt.includes(k)));
  return JSON.stringify(items,null,1);
})()
"""
print(_cdp.ev(t, JS))
