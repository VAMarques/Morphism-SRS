"""Exercise the shipped mobile presentation in a real, offline Chromium view.

The bridge is a fixture here; the native scheduler is tested separately on JVM.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineUrlSchemeHandler
from PySide6.QtWebEngineWidgets import QWebEngineView
from morphism_srs.web_engine.scheme_handler import register_morphism_scheme


class Assets(QWebEngineUrlSchemeHandler):
    def __init__(self, parent):
        super().__init__(parent)
        self.errors = []
    def requestStarted(self, job):
        path = job.requestUrl().path().lstrip("/")
        resources = ROOT / "src/morphism_srs/resources"
        web = ROOT / "src/morphism-portable/assets/web"
        if path == "mathjax_init.js":
            config = json.loads((resources / "defaults/mathjax_macros.json").read_text(encoding="utf-8"))
            data = ("window.MathJax="+json.dumps({"tex":config,"svg":{"fontCache":"local"},"startup":{"typeset":False}})+";").encode()
        else:
            target = web / path if path in ("index.html","graph_canvas.js","portable_ui.js") else resources / "web" / path
            if not target.is_file():
                self.errors.append(path)
                job.fail(job.Error.UrlNotFound)
                return
            data = target.read_bytes()
        mime = {"js":"text/javascript","css":"text/css","html":"text/html"}.get(path.rsplit(".",1)[-1],"application/octet-stream")
        buf=QBuffer(job); buf.setData(QByteArray(data)); buf.open(QIODevice.OpenModeFlag.ReadOnly)
        job.reply(mime.encode(),buf)


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == self.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print(f"Mobile Chromium: {message} ({source}:{line})")


class TestPortableWeb(unittest.TestCase):
    def test_offline_cloze_mathjax_dpi_navigation_rating_undo_and_stats(self):
        register_morphism_scheme()
        app=QApplication.instance() or QApplication([])
        view=QWebEngineView(); view.resize(390,844)
        profile=QWebEngineProfile(view)
        handler=Assets(profile); profile.installUrlSchemeHandler(b"morphism",handler)
        page=Page(profile,view); view.setPage(page)
        themes=[json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "src/morphism_srs/resources/themes").glob("*.json")]
        fixture = r'''
const note={id:1,title:"$\\mathbb{R}^n$",premise_html:"$\\bm{x}$",review_mode:"cloze",pos_x:-2100,pos_y:-650,due_count:1};
const cards=[1,2,3].map((id)=>({id,note_id:1,step_order:id-1,title:"Step "+id,front_html:"$x_"+id+"$",back_html:"$\\cancel{x_"+id+"}$"}));
let undoCard=0;
const methods={getSetting:()=>"",setSetting:()=>true,themes:()=>THEMES,
 listCoursesJson:()=>[{id:1,name:"Algebra",description:"Test",desired_retention:0.8,node_count:1,due_count:1}],
 getCourseGraphJson:()=>({nodes:[note],cards,edges:[]}),buildDueQueue:()=>[2],lastUndoCard:()=>undoCard,
 getCardPromptContextJson:()=>({card:cards[1],note,review_mode:"cloze",conditioning_siblings:[{...cards[0],position:"before"},{...cards[2],position:"after"}],intervals_preview:{1:"1d",2:"2d",3:"5d",4:"8d"}}),
 submitRating:()=>{undoCard=2;return{};},undoLastRating:()=>{undoCard=0;return true;},
 stats:()=>({total_cards:3,due_today:1,retention:0.8,states:[{state:0,count:3}],heatmap:[]}), updateNodePosition:()=>true};
window.MorphismNative=Object.fromEntries(Object.entries(methods).map(([key,fn])=>[key,(...args)=>JSON.stringify({ok:true,data:fn(...args)})]));
'''.replace("THEMES",json.dumps(themes),1)
        script=QWebEngineScript(); script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld); script.setSourceCode(fixture); page.scripts().insert(script)
        def js(code):
            result=[]; loop=QEventLoop()
            page.runJavaScript(code,lambda value:(result.append(value),loop.quit()))
            QTimer.singleShot(5000,loop.quit); loop.exec()
            self.assertTrue(result,"Chromium did not return a result")
            return result[0]
        def wait_for(code):
            loop=QEventLoop(); timer=QTimer(); timer.setInterval(30)
            timer.timeout.connect(lambda: page.runJavaScript(code,lambda ready:loop.quit() if ready else None))
            timer.start(); QTimer.singleShot(15000,loop.quit); loop.exec(); timer.stop()
            self.assertTrue(js(code),f"Timed out: {code}")
        try:
            view.show(); page.setUrl(QUrl("morphism://app/index.html"))
            wait_for("!!window.app && !!window.MathJax?.typesetPromise")
            self.assertEqual(js("document.querySelectorAll('.nav-tab').length"),4)
            self.assertEqual(js("document.querySelectorAll('.theme-option-btn').length"),10)
            self.assertEqual(js("window.getComputedStyle(document.querySelector('#view-graph')).display"), "flex")
            self.assertEqual(js("window.getComputedStyle(document.querySelector('#view-review')).display"), "none")
            wait_for("document.querySelectorAll('.graph-node-title mjx-container').length===1")
            self.assertTrue(js("(()=>{const g=app.graphView,n=g.notes[0],r=g.canvas.getBoundingClientRect();const x=g.offsetX+(n.pos_x+g.nodeWidth/2)*g.scale,y=g.offsetY+(n.pos_y+g.nodeHeight/2)*g.scale;return x>0&&x<r.width&&y>0&&y<r.height;})()"))
            self.assertTrue(js("!!document.querySelector('#btn-scan-qr')"))
            js("app.switchTab('review')")
            self.assertEqual(js("window.getComputedStyle(document.querySelector('#view-review')).display"), "flex")
            self.assertEqual(js("window.getComputedStyle(document.querySelector('#view-graph')).display"), "none")
            self.assertEqual(js("app.queue.length"), 1)
            js("app.showAnswer();")
            wait_for("document.querySelectorAll('#review-front-content mjx-container').length>=6")
            self.assertEqual(js("document.querySelectorAll('mjx-merror').length"),0)
            self.assertTrue(js("document.querySelector('#review-front-content').innerHTML.indexOf('Step 1') < document.querySelector('#review-front-content').innerHTML.indexOf('target-answer')"))
            self.assertTrue(js("document.querySelector('#review-front-content').innerHTML.indexOf('Step 3') > document.querySelector('#review-front-content').innerHTML.indexOf('target-answer')"))
            js("app.rateCurrentCard(3)")
            self.assertFalse(js("document.querySelector('#btn-undo').disabled"))
            js("app.undoRating();app.switchTab('stats')")
            self.assertEqual(js("document.querySelectorAll('#stats-heatmap-grid > div').length"),28)
            self.assertEqual(js("document.querySelector('#stat-total-cards').textContent"),"3")
            js("app.openModal('modal-theme')")
            self.assertTrue(js("onPortableBackPressed()"))
            self.assertFalse(js("document.querySelector('#modal-theme').classList.contains('active')"))
            self.assertTrue(js("onPortableBackPressed()"))
            self.assertEqual(js("app.currentTab"),"graph")
            self.assertFalse(js("onPortableBackPressed()"))
            js("Object.defineProperty(window,'devicePixelRatio',{value:3});app.graphView.resize();app.graphView.fitAll();")
            self.assertTrue(js("Math.abs(app.graphView.canvas.width-app.graphView.canvas.getBoundingClientRect().width*3)<1"))
            self.assertTrue(js("Math.abs(app.graphView._screenToWorld(app.graphView.offsetX+10*app.graphView.scale, app.graphView.offsetY+20*app.graphView.scale).x-10)<0.001"))
            self.assertEqual(handler.errors,[])
        finally:
            view.close(); page.deleteLater(); app.processEvents()


if __name__ == "__main__":
    unittest.main()
