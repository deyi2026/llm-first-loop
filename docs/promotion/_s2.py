import _cdp2, pickle
t = _cdp2.attach(pickle.load(open('_tab.pkl','rb')))
print("URL:", t.ev("location.href"))
print("READY:", t.ev("document.readyState"))
print("BTNS:", t.ev("JSON.stringify([...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,25))"))
print("BODYHEAD:", t.ev("document.body.innerText.replace(/\\s+/g,' ').slice(0,200)"))
