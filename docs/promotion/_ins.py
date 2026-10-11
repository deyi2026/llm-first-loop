import zh2, json, os, sys, time

def caret_to(tab, anchor, kind="h2"):
    """Place the caret in the empty paragraph right after the given heading."""
    js = """(()=>{const h=[...document.querySelectorAll('.public-DraftEditor-content h2')]
      .find(e=>(e.innerText||'').trim().startsWith(%s));
    if(!h) return 'NO_ANCHOR';
    const blk=h.closest('[data-block]')||h; let n=blk.nextElementSibling;
    while(n && !(n.hasAttribute&&n.hasAttribute('data-block'))) n=n.nextElementSibling;
    const t=n||blk; t.scrollIntoView({block:'center'});
    return (t.innerText||'').replace(/\\s+/g,' ').slice(0,30);})()""" % json.dumps(anchor)
    r = zh2.ev(tab, js)
    time.sleep(0.6)
    click_js = """(()=>{const h=[...document.querySelectorAll('.public-DraftEditor-content h2')]
      .find(e=>(e.innerText||'').trim().startsWith(%s));
    const blk=h.closest('[data-block]')||h; let n=blk.nextElementSibling;
    while(n && !(n.hasAttribute&&n.hasAttribute('data-block'))) n=n.nextElementSibling;
    return n||blk;})()""" % json.dumps(anchor)
    zh2.click(tab, click_js)
    sel = zh2.ev(tab, """(()=>{const s=window.getSelection();let n=s.anchorNode,inEd=false;
      while(n){if(n.classList&&n.classList.contains('public-DraftEditor-content')){inEd=true;break;}n=n.parentElement||n.parentNode;}
      return inEd;})()""")
    return r, sel

def insert_image(tab, path, anchor):
    before = zh2.counter(tab)["imgs"]
    r, sel = caret_to(tab, anchor)
    if sel is not True:
        return {"anchor": r, "caret": sel, "err": "no caret"}
    zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('图片'))")
    time.sleep(1.2)
    zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='上传图片')")
    time.sleep(1.2)
    up = zh2.upload_image(tab, [path], wait=5.0)
    time.sleep(2.0)
    zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='插入图片')")
    time.sleep(4.0)
    c = zh2.counter(tab)
    return {"anchor": r, "upload": up, "imgs_before": before, "imgs_after": c["imgs"], "字数": c["counter"]}

if __name__ == "__main__":
    tab = zh2.pick("/edit"); zh2.activate(tab)
    JOBS = [
        ("img/fig11-three-state-layers.png", "哲学一：事实是一种有结构的"),
        ("img/fig12-debt-ratchet.png",        "哲学二：反身的债务基线"),
        ("img/fig13-ideal-vs-reality.png",    "哲学三：六面是操作模型"),
        ("img/fig15-evidence-tiering.png",    "哲学四：证据可以引用"),
    ]
    for path, anchor in JOBS:
        print(path, "->", json.dumps(insert_image(tab, os.path.abspath(path), anchor), ensure_ascii=False)[:300])
