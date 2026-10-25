/* Presentation only: all persistent data, queues and scheduling live in SQLite/Kotlin. */
"use strict";
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function native(method, ...args) {
    const response = JSON.parse(window.MorphismNative[method](...args));
    if (!response.ok) throw new Error(response.error);
    return response.data;
}
let typesetQueue = Promise.resolve();
function typeset(elements) {
    typesetQueue = typesetQueue.catch(() => {}).then(() => window.MathJax?.startup?.promise).then(() => {
        if (window.MathJax?.typesetPromise) {
            const live = elements.filter(e => e?.isConnected);
            window.MathJax.typesetClear(live);
            return window.MathJax.typesetPromise(live);
        }
    }).catch(console.error);
}
class MorphismApp {
    constructor() {
        this.currentTab = "graph"; this.queue = []; this.index = 0; this.undo = []; this.busy = false;
        this.activeCourseId = Number(native("getSetting", "active_course_id")) || 0;
        this.themes = native("themes");
        this.graphView = new TouchGraphView($("graph-canvas"), {
            onNodeSelected: node => this.inspectNode(node),
            onNodeMoved: () => this.savePositions()
        });
        this.applyTheme(native("getSetting", "active_theme_id") || "dark_slate");
        this.bind(); this.refresh();
    }
    refresh() {
        this.courses = native("listCoursesJson");
        if (!this.courses.some(c => c.id === this.activeCourseId)) this.activeCourseId = this.courses[0]?.id || 0;
        native("setSetting", "active_course_id", String(this.activeCourseId));
        this.data = native("getCourseGraphJson", this.activeCourseId);
        this.graphView.setData(this.data.nodes, this.data.edges);
        $("lbl-active-course").textContent = this.courses.find(c => c.id === this.activeCourseId)?.name || "Sin curso";
        const due = this.data.nodes.reduce((sum, n) => sum + n.due_count, 0);
        $("fab-due-count").textContent = due; $("badge-due-count").textContent = due;
        $("badge-due-count").style.display = due ? "inline-block" : "none";
        this.renderCoursesList();
        if (this.currentTab === "stats") this.renderStats();
        requestAnimationFrame(() => {
            this.graphView.resize();
            this.graphView.fitAll();
        });
    }
    applyTheme(id) {
        const theme = this.themes.find(t => t.id === id) || this.themes[0];
        const t = theme.tokens;
        const mapped = {bg_color:t.bg_primary,surface_bg:t.bg_secondary,card_bg:t.bg_surface_0,border_color:t.border_subtle,
            accent:t.accent_primary,accent_hover:t.accent_primary_hover,text:t.text_primary,text_muted:t.text_muted,
            edge_color:t.accent_secondary,node_border:t.node_learned_border,due_border:t.node_due_border};
        window.AppTheme = mapped;
        Object.entries(mapped).forEach(([key,value]) => document.documentElement.style.setProperty("--" + (key === "text" ? "text-color" : key.replaceAll("_","-")), value));
        // Canonical cards.css consumes these tokens.
        Object.entries(t).forEach(([key,value]) => document.documentElement.style.setProperty("--"+key.replaceAll("_","-"),value));
        native("setSetting","active_theme_id",theme.id);
        this.graphView.render();
    }
    renderCoursesList() {
        const container = $("courses-list-container"); container.replaceChildren();
        if (!this.courses.length) {
            const p = document.createElement("p"); p.textContent = "Sin cursos. Pulsa Sincronizar con PC para comenzar.";
            container.append(p); return;
        }
        this.courses.forEach(course => {
            const item = document.createElement("div"); item.className = "course-card-item" + (course.id === this.activeCourseId ? " active" : "");
            item.innerHTML = `<strong>${escapeHtml(course.name)}</strong><p>${escapeHtml(course.description)}</p><small>${course.node_count} nodos · ${course.due_count} vencidas · ${Math.round(course.desired_retention*100)}%</small>`;
            item.onclick = () => { this.activeCourseId = course.id; this.queue=[]; this.undo=[]; this.refresh(); this.switchTab("graph"); this.graphView.fitAll(); };
            container.append(item);
        });
    }
    switchTab(id) {
        if (this.busy) return;
        this.currentTab = id;
        document.querySelectorAll(".view-page").forEach(p => p.classList.toggle("active",p.id === "view-"+id));
        document.querySelectorAll(".nav-tab").forEach(p => p.classList.toggle("active",p.dataset.tab === id));
        if (id === "graph") {
            requestAnimationFrame(() => {
                this.graphView.resize();
            });
        }
        if (id === "review") {
            if (!this.queue.length || this.index >= this.queue.length) {
                this.queue = native("buildDueQueue", this.activeCourseId, 0);
                this.index = 0;
            }
            this.renderCurrentReviewCard();
        }
        if (id === "stats") this.renderStats();
    }
    savePositions() {
        if(this.busy) return;
        this.graphView.notes.forEach(n => native("updateNodePosition",this.activeCourseId,n.id,n.pos_x,n.pos_y));
    }
    inspectNode(node) {
        if (!node || this.busy) return;
        $("node-title").textContent = node.title;
        $("node-content").innerHTML = node.premise_html + this.data.cards.filter(c=>c.note_id===node.id).map(c=>
            `<div class="sibling-step"><strong>${escapeHtml(c.title)}</strong><div>${c.front_html}</div><div>${c.back_html}</div></div>`).join("");
        $("btn-node-review").onclick = () => { this.closeModal("modal-node"); this.startDueReview(node.id); };
        this.openModal("modal-node"); typeset([$("node-content")]);
    }
    startDueReview(noteId=0) {
        this.queue = native("buildDueQueue",this.activeCourseId,noteId); this.index=0; this.undo=[];
        this.switchTab("review"); this.renderCurrentReviewCard();
    }
    renderCurrentReviewCard() {
        const finished = this.index >= this.queue.length;
        $("review-empty-state").style.display = finished ? "block" : "none";
        $("review-card-container").style.display = finished ? "none" : "block";
        // Keep Undo accessible after the final rating.
        const undoCard = native("lastUndoCard");
        $("review-bottom-controls").style.display = !finished || undoCard ? "flex" : "none";
        $("btn-undo").disabled = !undoCard;
        $("btn-show-answer").style.display = finished ? "none" : "block";
        $("rating-buttons-row").style.display = "none";
        $("review-progress-fill").style.width = `${this.queue.length ? this.index/this.queue.length*100 : 100}%`;
        if (finished) { $("review-empty-state").querySelector(".empty-msg").textContent = "Todo al día. Puedes deshacer la última calificación."; this.refresh(); return; }
        this.prompt = native("getCardPromptContextJson",this.queue[this.index],this.activeCourseId);
        this.startedAt = performance.now(); this.answerShown = false;
        const {card,note,review_mode:mode,conditioning_siblings:siblings} = this.prompt;
        $("review-card-note-title").textContent = note.title;
        $("review-card-type-chip").textContent = mode.toUpperCase();
        $("review-card-type-chip").className = "card-type-chip " + mode;
        const sibling = s => `<div class="sibling-step"><div class="sibling-header">Paso ${s.step_order+1} ${escapeHtml(s.title)}</div><div class="sibling-front">${s.front_html}</div><div class="sibling-back">${s.back_html}</div></div>`;
        $("review-front-content").innerHTML = `<div class="premise-box">${note.premise_html}</div>` +
            siblings.filter(s=>s.position==="before").map(sibling).join("") +
            `<div class="active-card-box"><div class="active-step-badge">Paso ${card.step_order+1} ${escapeHtml(card.title)}</div><div class="card-front">${card.front_html}</div><div class="card-back" id="target-answer" hidden>${card.back_html}</div></div>` +
            siblings.filter(s=>s.position==="after").map(sibling).join("");
        $("review-back-content").style.display="none";
        typeset([$("review-front-content")]);
    }
    showAnswer() {
        if(!this.prompt || this.index>=this.queue.length) return;
        $("target-answer").hidden=false; this.answerShown=true;
        $("btn-show-answer").style.display="none"; $("rating-buttons-row").style.display="grid";
        ["again","hard","good","easy"].forEach((key,i)=>$("forecast-"+key).textContent=this.prompt.intervals_preview[i+1]);
        typeset([$("review-front-content")]);
    }
    rateCurrentCard(rating) {
        if(this.busy || !this.answerShown) return;
        native("submitRating",this.queue[this.index],this.activeCourseId,rating,Math.round(performance.now()-this.startedAt));
        this.undo.push(this.index); this.index++; this.renderCurrentReviewCard();
    }
    undoRating() {
        if(this.busy) return;
        const cardId=native("lastUndoCard");
        if(!cardId) return;
        if(native("undoLastRating")) {
            if(this.undo.length) this.index=this.undo.pop();
            else {
                // An undo record survives app restarts and completed syncs.
                const card=this.data.cards.find(c=>c.id===cardId);
                if(!card) { this.refresh(); this.renderCurrentReviewCard(); return; }
                this.queue=[cardId]; this.index=0;
            }
            this.renderCurrentReviewCard();
        }
    }
    renderStats() {
        const stats=native("stats",this.activeCourseId);
        $("stat-total-cards").textContent=stats.total_cards;
        $("stat-notes-count").textContent=this.data.nodes.length;
        $("stat-retention").textContent=Math.round(stats.retention*100)+"%";
        $("stat-due-today").textContent=stats.due_today || 0;
        const names=["Nuevas","Aprendizaje","Repaso","Reaprendizaje"];
        $("stat-states").textContent=stats.states.map(s=>`${names[s.state]}: ${s.count}`).join(" · ");
        const counts=new Map(stats.heatmap.map(d=>[d.day,d.count]));
        $("stats-heatmap-grid").replaceChildren();
        for(let ago=27;ago>=0;ago--) {
            const day=new Date(); day.setUTCDate(day.getUTCDate()-ago);
            const date=day.toISOString().slice(0,10), count=counts.get(date)||0, cell=document.createElement("div");
            cell.title=`${date}: ${count} repasos`; cell.style.cssText=`height:16px;border-radius:3px;background:${count ? "var(--accent)" : "var(--border-color)"};opacity:${count ? Math.min(1,0.3+count/12) : 0.3}`;
            $("stats-heatmap-grid").append(cell);
        }
    }
    performSync() {
        if(this.busy) return;
        this.busy=true; $("btn-run-sync").disabled=true;
        document.body.classList.add("syncing");
        $("sync-status-msg").textContent="Sincronizando repasos, cambios SQL y archivos multimedia…";
        window.MorphismNative.synchronize($("sync-endpoint-url").value.trim());
    }
    syncFinished(result) {
        this.busy=false; $("btn-run-sync").disabled=false;
        document.body.classList.remove("syncing");
        $("sync-status-msg").textContent=result.ok ? "Sincronización completada." : "Error: "+result.error;
        if(result.ok) { this.activeCourseId=Number(native("getSetting","active_course_id")) || 0; this.applyTheme(native("getSetting","active_theme_id") || "dark_slate"); this.queue=[]; this.undo=[]; this.refresh(); this.renderCurrentReviewCard(); this.switchTab("graph"); this.graphView.fitAll(); }
    }
    openModal(id) { $(id).classList.add("active"); }
    closeModal(id) { $(id).classList.remove("active"); }
    bind() {
        document.querySelectorAll(".nav-tab").forEach(b=>b.onclick=()=>this.switchTab(b.dataset.tab));
        $("btn-review-due").onclick=()=>this.startDueReview(); $("btn-show-answer").onclick=()=>this.showAnswer();
        ["again","hard","good","easy"].forEach((key,i)=>$("btn-"+key).onclick=()=>this.rateCurrentCard(i+1));
        $("btn-undo").onclick=()=>this.undoRating(); $("btn-fit-graph").onclick=()=>this.graphView.fitAll();
        $("btn-auto-layout").onclick=()=>{this.graphView.autoArrange();this.savePositions();};
        $("txt-graph-search").oninput=e=>this.graphView.setSearchQuery(e.target.value);
        $("lbl-active-course").onclick=()=>this.switchTab("courses");
        $("btn-open-sync").onclick=()=>{ $("sync-endpoint-url").value=native("getSetting","sync_last_url"); this.openModal("modal-sync"); };
        $("btn-scan-qr").onclick=()=>{ if(!this.busy) window.MorphismNative.scanQr(); };
        $("btn-run-sync").onclick=()=>this.performSync(); $("btn-open-guide").onclick=()=>this.openModal("modal-guide");
        $("btn-theme-selector").onclick=()=>this.openModal("modal-theme");
        const grid=document.querySelector(".theme-grid"); grid.replaceChildren();
        this.themes.forEach(theme=>{const b=document.createElement("button");b.className="theme-option-btn";b.textContent=theme.name;
            b.onclick=()=>{this.applyTheme(theme.id);this.closeModal("modal-theme");};grid.append(b);});
        document.querySelectorAll(".modal-overlay").forEach(m=>m.onclick=e=>{if(e.target===m)this.closeModal(m.id);});
        window.addEventListener("morphism-mathjax-ready",()=>typeset([$("review-front-content"),$("node-content"),...this.graphView.labelNodes.values()]));
    }
}
window.onPortableSyncResult=result=>window.app.syncFinished(result);
window.onPortableBackPressed=()=>{
    const modal=document.querySelector(".modal-overlay.active");
    if(modal){window.app.closeModal(modal.id);return true;}
    if(window.app.currentTab!=="graph"){window.app.switchTab("graph");return true;}
    return window.app.busy;
};
window.addEventListener("error",event=>{ if($("sync-status-msg")) $("sync-status-msg").textContent=event.message; });
function initMorphismApp() {
    try {
        if (!window.app) window.app = new MorphismApp();
    } catch(e) {
        document.body.textContent = "No se pudo abrir Morphism: " + e.message;
    }
}
if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", initMorphismApp);
} else {
    initMorphismApp();
}

window.onPortableQrResult = result => {
    if(result.error) $("sync-status-msg").textContent=result.error;
    if(result.url) { $("sync-endpoint-url").value=result.url; window.app.performSync(); }
};
