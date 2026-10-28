"""Clicks every control on a dashboard.html and checks the result. python uitest.py FILE WIDTH SCHEME [touch]"""
import sys, re
from playwright.sync_api import sync_playwright
src,W,scheme=sys.argv[1],int(sys.argv[2]),sys.argv[3]; touch=len(sys.argv)>4
res=[]
def ck(name,ok,detail=""): res.append((name,bool(ok),detail))
with sync_playwright() as p:
    b=p.chromium.launch(); ctx=b.new_context(viewport={"width":W,"height":900},color_scheme=scheme,has_touch=touch,is_mobile=touch,accept_downloads=True)
    pg=ctx.new_page(); errs=[]; pg.on("pageerror",lambda e: errs.append(str(e))); pg.on("console",lambda m: errs.append(m.text) if m.type=="error" else None)
    pg.goto("file://"+src); pg.wait_for_timeout(400)
    T=lambda s: pg.locator(s).first.inner_text()
    ck("loads without errors",not errs,errs[:2])
    ck("no sideways scrolling",pg.evaluate("document.documentElement.scrollWidth")<=W,pg.evaluate("document.documentElement.scrollWidth"))
    ck("account value shown",re.match(r"^\$[\d,]+\.\d\d$",T("#acct-v")),T("#acct-v"))
    ck("chart drawn",pg.locator("#acct-chart svg path.ln").count()==1)
    labels={"1D":"Past 24 hours","1W":"Past week","1M":"Past month","3M":"Past 3 months","ALL":"Since the test started"}
    for r,lab in labels.items():
        pg.locator('.rng button[data-r="%s"]'%r).click(); pg.wait_for_timeout(80)
        pressed=pg.locator('.rng button[aria-pressed=true]').all_inner_texts()
        ck("range %s"%r,pressed==[r] and T("#acct-per").startswith(lab),"%s | %s"%(pressed,T("#acct-per")))
    box=pg.locator("#acct-chart svg").bounding_box()
    if not touch:
        pg.mouse.move(box["x"]+box["width"]*0.4,box["y"]+box["height"]*0.5); pg.wait_for_timeout(80)
        sc=T("#acct-per"); vis=pg.locator("#acct-chart line.xh").get_attribute("visibility")
        ck("drag/hover reads a past value",not sc.startswith("Since") and vis=="visible",sc)
        pg.mouse.move(box["x"]+box["width"]*0.5,box["y"]-60); pg.wait_for_timeout(80)
        ck("leaving the chart restores",T("#acct-per").startswith("Since"),T("#acct-per"))
    else:
        pg.evaluate("""([x,y])=>{const s=document.querySelector('#acct-chart svg');
          s.dispatchEvent(new PointerEvent('pointerdown',{clientX:x,clientY:y,pointerType:'touch',bubbles:true}));
          s.dispatchEvent(new PointerEvent('pointermove',{clientX:x+30,clientY:y,pointerType:'touch',bubbles:true}));}""",[box["x"]+box["width"]*0.3,box["y"]+box["height"]*0.5])
        sc=T("#acct-per"); ck("finger drag reads a past value",not sc.startswith("Since"),sc)
        pg.evaluate("()=>document.querySelector('#acct-chart svg').dispatchEvent(new PointerEvent('pointerup',{pointerType:'touch',bubbles:true}))")
        ck("lifting the finger restores",T("#acct-per").startswith("Since"),T("#acct-per"))
    pg.locator("#acct-chart svg").focus(); pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(50)
    k1=T("#acct-per"); pg.keyboard.press("Escape"); pg.wait_for_timeout(50)
    ck("arrow keys and Escape",not k1.startswith("Since") and T("#acct-per").startswith("Since"),k1)
    v0=T("#acct-v"); pg.locator('.seg button[data-led="maker"]').click(); pg.wait_for_timeout(100)
    ck("switch to limit-order test",pg.locator('.seg button[data-led="maker"]').get_attribute("aria-pressed")=="true" and pg.locator('.seg button[data-led="main"]').get_attribute("aria-pressed")=="false",T("#acct-v"))
    rows=pg.locator("#act-list li .t2").all_inner_texts()
    ck("activity follows the switch",all(t.startswith("Limit order") for t in rows) if rows else T("#act-list").startswith("No"),rows[:1])
    pg.locator('.seg button[data-led="main"]').click(); pg.wait_for_timeout(100)
    ck("switch back to main bot",T("#acct-v")==v0,T("#acct-v"))
    # activity filters
    for f in ("open","closed","all"):
        pg.locator('.chips button[data-f="%s"]'%f).click(); pg.wait_for_timeout(60)
        tags=pg.locator("#act-list .tag").all_inner_texts(); empty=pg.locator("#act-list li.empty").count()
        ok={"open":all(t in("Open","Waiting to fill") for t in tags),"closed":all(t in("Won","Lost","Not filled") for t in tags),"all":True}[f]
        ck("filter %s"%f,ok and pg.locator('.chips button[aria-pressed=true]').get_attribute("data-f")==f,"%d rows%s"%(len(tags)," (empty note)" if empty else ""))
    more=pg.locator("#act-list li.more button")
    if more.count():
        n0=pg.locator("#act-list li .t1").count(); more.click(); pg.wait_for_timeout(60)
        ck("show more",pg.locator("#act-list li .t1").count()>n0,"%d -> %d"%(n0,pg.locator("#act-list li .t1").count()))
    # tabs
    for tid,pid in (("#tb-stm","#tp-stm"),("#tb-tax","#tp-tax"),("#tb-act","#tp-act")):
        pg.locator(tid).click(); pg.wait_for_timeout(60)
        vis=[x for x in ("#tp-act","#tp-stm","#tp-tax") if pg.locator(x).is_visible()]
        ck("tab "+tid[4:],vis==[pid] and pg.locator(tid).get_attribute("aria-selected")=="true",vis)
    pg.locator("#tb-act").focus(); pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(60)
    ck("tabs with arrow keys",pg.locator("#tb-stm").get_attribute("aria-selected")=="true")
    ncards=pg.locator("#stm-list .stm").count(); ck("statements listed",ncards>=1,"%d months"%ncards)
    for i,lab in ((0,"statement CSV"),(1,"statement printable copy")):
        with pg.expect_download() as d: pg.locator("#stm-list .dl button").nth(i).click()
        ck("download "+lab,d.value.suggested_filename.endswith(("csv","html")),d.value.suggested_filename)
    pg.locator("#tb-tax").click(); pg.wait_for_timeout(60)
    sa=pg.locator("#tax-list .showall")
    if sa.count():
        n0=pg.locator("#tax-list tr").count(); sa.first.click(); pg.wait_for_timeout(60); ck("tax show all",pg.locator("#tax-list tr").count()>n0)
    for i,lab in ((0,"tax CSV"),(1,"tax printable copy")):
        with pg.expect_download() as d: pg.locator("#tax-list .dl button").nth(i).click()
        ck("download "+lab,d.value.suggested_filename.endswith(("csv","html")),d.value.suggested_filename)
    # older parts of the page
    for summ in pg.locator("details summary").all():
        t=summ.inner_text(); summ.click(); pg.wait_for_timeout(40)
        ck("opens: "+t[:34],summ.evaluate("s=>s.parentElement.open"))
    tipn=pg.locator("[data-tip]").first
    if tipn.count():
        tipn.scroll_into_view_if_needed(); tipn.hover() if not touch else tipn.tap(); pg.wait_for_timeout(400)
        ck("tooltips (hover/tap)",pg.evaluate("getComputedStyle(document.getElementById('tip')).opacity")=="1",pg.evaluate("document.getElementById('tip').textContent")[:50])
    w0=pg.locator("#acct-chart svg").get_attribute("viewBox"); pg.set_viewport_size({"width":max(320,min(W,700)-60),"height":900}); pg.wait_for_timeout(350)
    ck("chart redraws on resize",pg.locator("#acct-chart svg").get_attribute("viewBox")!=w0,"%s -> %s"%(w0,pg.locator("#acct-chart svg").get_attribute("viewBox")))
    ck("no errors after all clicks",not errs,errs[:2])
    b.close()
bad=[r for r in res if not r[1]]
for n,ok,d in res: print("%s %-38s %s"%("PASS" if ok else "FAIL",n,d if not ok else ""))
print("== %d checks, %d failed"%(len(res),len(bad)))
