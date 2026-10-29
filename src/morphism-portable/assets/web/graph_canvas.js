/**
 * Morphism SRS Proto2 - Clean Canvas Interactive DAG Graph View
 * Geometric shapes: Standard (Rounded Rect), Serial (Hex/Chamfer), Cloze (Pill/Ellipse).
 */

class TouchGraphView {
    constructor(canvas, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.options = options;

        this.notes = [];
        this.edges = [];
        this.selectedNote = null;
        this.searchQuery = "";

        this.offsetX = 50;
        this.offsetY = 80;
        this.scale = 0.85;
        this.minScale = 0.2;
        this.maxScale = 3.0;

        this.draggedNode = null;
        this.isPanning = false;
        this.startPanX = 0;
        this.startPanY = 0;
        this.pointers = new Map();
        this.initialPinchDistance = null;
        this.initialScale = 1.0;
        this.dragStartTime = 0;
        this.dragStartPos = { x: 0, y: 0 };

        this.nodeWidth = 210;
        this.nodeHeight = 72;

        this.resizeObserver = new ResizeObserver(() => { this.resize(); if(this.needsFit) this.fitAll(); });
        this.resizeObserver.observe(this.canvas);
        this.labelsLayer=document.createElement("div");
        this.labelsLayer.style.cssText="position:absolute;inset:0;overflow:hidden;pointer-events:none";
        this.canvas.insertAdjacentElement("afterend",this.labelsLayer);
        this.labelNodes=new Map();
        this._setupEvents();
        this.resize();
    }

    resize() {
        const dpr = window.devicePixelRatio || 1;
        const rect = this.canvas.getBoundingClientRect();
        this.canvas.width = Math.max(100, Math.round(rect.width * dpr));
        this.canvas.height = Math.max(100, Math.round(rect.height * dpr));
        this.dpr = dpr;
        this.render();
    }

    setData(notes, edges) {
        this.needsFit=true;
        this.notes = notes || [];
        this.edges = edges || [];
        if(window.MathJax?.typesetClear) window.MathJax.typesetClear([this.labelsLayer]);
        this.labelsLayer.replaceChildren(); this.labelNodes.clear();
        this.notes.forEach(note => {
            const label=document.createElement("div");
            label.className="graph-node-title";
            label.textContent=note.title || "Sin titulo";
            label.style.cssText=`position:absolute;left:0;top:0;width:${this.nodeWidth-28}px;height:28px;overflow:hidden;white-space:nowrap;font:bold 13px sans-serif;transform-origin:0 0`;
            this.labelsLayer.append(label); this.labelNodes.set(note.id,label);
        });
        if(typeof typeset==="function") typeset([...this.labelNodes.values()]);
        this.render();
    }

    setSearchQuery(q) {
        this.searchQuery = (q || "").trim().toLowerCase();
        this.render();
    }

    _setupEvents() {
        window.addEventListener("resize", () => this.resize());
        this.canvas.addEventListener("pointerdown", (e) => this._onPointerDown(e));
        this.canvas.addEventListener("pointermove", (e) => this._onPointerMove(e));
        this.canvas.addEventListener("pointerup", (e) => this._onPointerUp(e));
        this.canvas.addEventListener("pointercancel", (e) => this._onPointerUp(e));
        this.canvas.addEventListener("wheel", (e) => this._onWheel(e), { passive: false });
    }

    _screenToWorld(sx, sy) {
        const dpr = this.dpr || 1;
        return {
            x: (sx - this.offsetX) / this.scale,
            y: (sy - this.offsetY) / this.scale
        };
    }

    _findNodeAt(wx, wy) {
        for (let i = this.notes.length - 1; i >= 0; i--) {
            const n = this.notes[i];
            const nx = n.pos_x ?? n.x ?? 0;
            const ny = n.pos_y ?? n.y ?? 0;
            if (wx >= nx && wx <= nx + this.nodeWidth && wy >= ny && wy <= ny + this.nodeHeight) {
                return n;
            }
        }
        return null;
    }

    _onPointerDown(e) {
        this.canvas.setPointerCapture(e.pointerId);
        this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        if (this.pointers.size === 1) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            const world = this._screenToWorld(sx, sy);
            const clicked = this._findNodeAt(world.x, world.y);

            this.dragStartTime = Date.now();
            this.dragStartPos = { x: e.clientX, y: e.clientY };

            if (clicked) {
                this.draggedNode = clicked;
                const nx = clicked.pos_x ?? clicked.x ?? 0;
                const ny = clicked.pos_y ?? clicked.y ?? 0;
                this.nodeDragOffset = { x: world.x - nx, y: world.y - ny };
            } else {
                this.isPanning = true;
                this.startPanX = e.clientX - this.offsetX;
                this.startPanY = e.clientY - this.offsetY;
            }
        } else if (this.pointers.size === 2) {
            this.draggedNode = null;
            this.isPanning = false;
            const pts = Array.from(this.pointers.values());
            this.initialPinchDistance = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
            this.initialScale = this.scale;
        }
    }

    _onPointerMove(e) {
        if (!this.pointers.has(e.pointerId)) return;
        this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        if (this.pointers.size === 1) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;

            if (this.draggedNode) {
                const world = this._screenToWorld(sx, sy);
                const nx = Math.round(world.x - this.nodeDragOffset.x);
                const ny = Math.round(world.y - this.nodeDragOffset.y);
                this.draggedNode.pos_x = nx;
                this.draggedNode.pos_y = ny;
                this.draggedNode.x = nx;
                this.draggedNode.y = ny;
                this.render();
            } else if (this.isPanning) {
                this.offsetX = e.clientX - this.startPanX;
                this.offsetY = e.clientY - this.startPanY;
                this.render();
            }
        } else if (this.pointers.size === 2 && this.initialPinchDistance) {
            const pts = Array.from(this.pointers.values());
            const currentDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
            const factor = currentDist / this.initialPinchDistance;
            this.scale = Math.max(this.minScale, Math.min(this.maxScale, this.initialScale * factor));
            this.render();
        }
    }

    _onPointerUp(e) {
        this.pointers.delete(e.pointerId);
        const dist = Math.hypot(e.clientX - this.dragStartPos.x, e.clientY - this.dragStartPos.y);
        const duration = Date.now() - this.dragStartTime;

        if (dist < 8 && duration < 350) {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            const world = this._screenToWorld(sx, sy);
            const clicked = this._findNodeAt(world.x, world.y);

            this.selectedNote = clicked;
            if (this.options.onNodeSelected) {
                this.options.onNodeSelected(clicked);
            }
        }

        if (this.pointers.size === 0) {
            if (this.draggedNode && this.options.onNodeMoved) {
                this.options.onNodeMoved(this.draggedNode);
            }
            this.draggedNode = null;
            this.isPanning = false;
            this.initialPinchDistance = null;
        } else if (this.pointers.size === 1) {
            const rem = Array.from(this.pointers.values())[0];
            this.isPanning = true;
            this.startPanX = rem.x - this.offsetX;
            this.startPanY = rem.y - this.offsetY;
        }

        this.render();
    }

    _onWheel(e) {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.15 : 0.85;
        this.scale = Math.max(this.minScale, Math.min(this.maxScale, this.scale * factor));
        this.render();
    }

    fitAll() {
        if (!this.notes || this.notes.length === 0) return;
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        for (const n of this.notes) {
            const nx = n.pos_x ?? n.x ?? 0;
            const ny = n.pos_y ?? n.y ?? 0;
            minX = Math.min(minX, nx);
            minY = Math.min(minY, ny);
            maxX = Math.max(maxX, nx + this.nodeWidth);
            maxY = Math.max(maxY, ny + this.nodeHeight);
        }

        const rect = this.canvas.getBoundingClientRect();
        const w = rect.width;
        const h = rect.height;
        if (w <= 0 || h <= 0) return;

        const boundsW = (maxX - minX) + 120;
        const boundsH = (maxY - minY) + 120;

        this.needsFit=false;
        this.scale = Math.max(0.01, Math.min(1.2, Math.min(w / boundsW, h / boundsH)));
        this.offsetX = (w - boundsW * this.scale) / 2 - minX * this.scale + 60 * this.scale;
        this.offsetY = (h - boundsH * this.scale) / 2 - minY * this.scale + 60 * this.scale;
        this.render();
    }

    autoArrange() {
        if (!this.notes || this.notes.length === 0) return;
        const inDegree = {};
        const adj = {};
        for (const n of this.notes) {
            const nid = n.id;
            inDegree[nid] = 0;
            adj[nid] = [];
        }

        for (const e of this.edges) {
            const src = e.source_note_id ?? e.source_id;
            const tgt = e.target_note_id ?? e.target_id;
            if (adj[src] && inDegree[tgt] !== undefined) {
                adj[src].push(tgt);
                inDegree[tgt] += 1;
            }
        }

        const levels = {};
        const queue = [];
        for (const n of this.notes) {
            if (inDegree[n.id] === 0) {
                levels[n.id] = 0;
                queue.push(n.id);
            }
        }

        while (queue.length > 0) {
            const u = queue.shift();
            for (const v of adj[u] || []) {
                levels[v] = Math.max(levels[v] || 0, (levels[u] || 0) + 1);
                inDegree[v]--;
                if (inDegree[v] === 0) {
                    queue.push(v);
                }
            }
        }

        const byLevel = {};
        for (const n of this.notes) {
            const l = levels[n.id] !== undefined ? levels[n.id] : 0;
            if (!byLevel[l]) byLevel[l] = [];
            byLevel[l].push(n);
        }

        const colSpacing = 270;
        const rowSpacing = 100;
        for (const lvl in byLevel) {
            const list = byLevel[lvl];
            list.forEach((n, idx) => {
                const nx = 60 + parseInt(lvl) * colSpacing;
                const ny = 60 + idx * rowSpacing;
                n.pos_x = nx;
                n.pos_y = ny;
                n.x = nx;
                n.y = ny;
            });
        }

        this.fitAll();
    }

    _drawNodeShape(ctx, x, y, w, h, mode) {
        ctx.beginPath();
        if (mode === "serial") {
            ctx.moveTo(x+w/2,y); ctx.lineTo(x+w,y+h/2);
            ctx.lineTo(x+w/2,y+h); ctx.lineTo(x,y+h/2); ctx.closePath();
        } else if (mode === "cloze") {
            ctx.ellipse(x+w/2,y+h/2,w/2,h/2,0,0,Math.PI*2);
        } else {
            // Standard rounded rect
            const r = 10;
            ctx.moveTo(x + r, y);
            ctx.lineTo(x + w - r, y);
            ctx.arcTo(x + w, y, x + w, y + h, r);
            ctx.arcTo(x + w, y + h, x, y + h, r);
            ctx.arcTo(x, y + h, x, y, r);
            ctx.arcTo(x, y, x + w, y, r);
            ctx.closePath();
        }
    }

    render() {
        const ctx = this.ctx;
        const w = this.canvas.getBoundingClientRect().width;
        const h = this.canvas.getBoundingClientRect().height;
        const theme = window.AppTheme || {
            bg_color: "#0B0710",
            card_bg: "#171019",
            border_color: "#3D2148",
            accent: "#F02A8C",
            edge_color: "#B47AD0",
            text: "#F7F1F8",
            text_muted: "#806F86",
            node_border: "#80D6A3",
            due_border: "#FF667D"
        };

        ctx.save();
        ctx.scale(this.dpr || 1, this.dpr || 1);
        ctx.fillStyle = theme.bg_color || "#000000";
        ctx.fillRect(0, 0, w, h);

        // Dot grid
        ctx.fillStyle = theme.border_color ? theme.border_color + "44" : "#222233";
        const gridStep = 40 * this.scale;
        const startX = (this.offsetX % gridStep);
        const startY = (this.offsetY % gridStep);
        for (let x = startX; x < w; x += gridStep) {
            for (let y = startY; y < h; y += gridStep) {
                ctx.beginPath();
                ctx.arc(x, y, 1.2, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        ctx.translate(this.offsetX, this.offsetY);
        ctx.scale(this.scale, this.scale);

        // Map for lookup
        const nodeMap = new Map();
        for (const n of this.notes) {
            nodeMap.set(n.id, n);
        }

        // Draw edges (Cardinal port Bezier splines with aligned arrowheads)
        ctx.strokeStyle = theme.edge_color || "#38bdf8";
        ctx.lineWidth = 2.4;
        for (const edge of this.edges) {
            const srcId = edge.source_note_id ?? edge.source_id;
            const tgtId = edge.target_note_id ?? edge.target_id;
            const src = nodeMap.get(srcId);
            const tgt = nodeMap.get(tgtId);
            if (src && tgt) {
                const hw1 = this.nodeWidth / 2;
                const hh1 = this.nodeHeight / 2;
                const hw2 = this.nodeWidth / 2;
                const hh2 = this.nodeHeight / 2;

                const p1x = (src.pos_x ?? src.x ?? 0) + hw1;
                const p1y = (src.pos_y ?? src.y ?? 0) + hh1;
                const p2x = (tgt.pos_x ?? tgt.x ?? 0) + hw2;
                const p2y = (tgt.pos_y ?? tgt.y ?? 0) + hh2;

                const dx = p2x - p1x;
                const dy = p2y - p1y;

                let startX, startY, endX, endY, c1x, c1y, c2x, c2y, tipAngle;

                if (Math.hypot(dx, dy) < 1) continue;

                // Dynamic boundary intersection: closest connection points on perimeter
                const getBorderPt = (cx, cy, hw, hh, tx, ty) => {
                    const vx = tx - cx;
                    const vy = ty - cy;
                    if (Math.abs(vx) < 1e-4 && Math.abs(vy) < 1e-4) return { x: cx, y: cy };
                    const sx = Math.abs(vx) > 1e-4 ? hw / Math.abs(vx) : Infinity;
                    const sy = Math.abs(vy) > 1e-4 ? hh / Math.abs(vy) : Infinity;
                    const s = Math.min(sx, sy);
                    return { x: cx + vx * s, y: cy + vy * s };
                };

                const start = getBorderPt(p1x, p1y, hw1, hh1, p2x, p2y);
                const end = getBorderPt(p2x, p2y, hw2, hh2, p1x, p1y);

                startX = start.x;
                startY = start.y;
                endX = end.x;
                endY = end.y;

                const edgeDist = Math.hypot(endX - startX, endY - startY);
                const span = Math.max(25, edgeDist * 0.25);
                tipAngle = Math.atan2(endY - startY, endX - startX);

                c1x = startX + Math.cos(tipAngle) * span;
                c1y = startY + Math.sin(tipAngle) * span;
                c2x = endX - Math.cos(tipAngle) * span;
                c2y = endY - Math.sin(tipAngle) * span;

                ctx.beginPath();
                ctx.moveTo(startX, startY);
                ctx.bezierCurveTo(c1x, c1y, c2x, c2y, endX, endY);
                ctx.stroke();

                // Arrowhead aligned with tipAngle entering target port
                const arr = 12.0;
                const barbAngle = Math.PI / 6;
                const pLeftX = endX - arr * Math.cos(tipAngle - barbAngle);
                const pLeftY = endY - arr * Math.sin(tipAngle - barbAngle);
                const pRightX = endX - arr * Math.cos(tipAngle + barbAngle);
                const pRightY = endY - arr * Math.sin(tipAngle + barbAngle);

                ctx.fillStyle = theme.accent || "#38bdf8";
                ctx.beginPath();
                ctx.moveTo(endX, endY);
                ctx.lineTo(pLeftX, pLeftY);
                ctx.lineTo(pRightX, pRightY);
                ctx.closePath();
                ctx.fill();
            }
        }

        // Draw nodes
        for (const note of this.notes) {
            const nx = note.pos_x ?? note.x ?? 0;
            const ny = note.pos_y ?? note.y ?? 0;
            const isSelected = this.selectedNote && (this.selectedNote.id === note.id);
            const isDue = Boolean(note.isDue);
            const mode = (note.review_mode || "standard").toLowerCase();

            const matchesSearch = this.searchQuery && (
                (note.title || "").toLowerCase().includes(this.searchQuery) ||
                (note.tags && note.tags.some(t => t.toLowerCase().includes(this.searchQuery)))
            );

            // Glow if search matches
            if (matchesSearch) {
                ctx.save();
                ctx.shadowColor = theme.accent || "#F02A8C";
                ctx.shadowBlur = 18;
                ctx.fillStyle = theme.accent || "#F02A8C";
                this._drawNodeShape(ctx, nx - 2, ny - 2, this.nodeWidth + 4, this.nodeHeight + 4, mode);
                ctx.fill();
                ctx.restore();
            }

            const cardCount = Array.isArray(note.cards) ? note.cards.length : (note.card_count || 1);
            const newCount = typeof note.new_count === "number" ? note.new_count : (isDue ? 0 : cardCount);

            // Morphism Standard Node Color Palette:
            // Unreviewed / root: slate grey (#334155 / #1e293b, border #94a3b8)
            // Up-to-date learned: royal blue (#2563eb / #1e3a8a, border #93c5fd)
            // In learning: cyan (#0284c7 / #0f172a, border #38bdf8)
            // Due: red (#dc2626 / #7f1d1d, border #fca5a5)
            let gradTop, gradBot, borderColor, borderWidth, statusLabel;
            if (isDue) {
                gradTop = "#dc2626";
                gradBot = "#7f1d1d";
                borderColor = "#fca5a5";
                borderWidth = 3.2;
                statusLabel = `DUE (${note.due_count || 1})`;
            } else if (cardCount > 0 && newCount === 0) {
                gradTop = "#2563eb";
                gradBot = "#1e3a8a";
                borderColor = "#93c5fd";
                borderWidth = 3.0;
                const rMinPct = Math.round((note.r_min || 1.0) * 100);
                statusLabel = `R_min ${rMinPct}%`;
            } else if (cardCount > 0 && newCount < cardCount) {
                gradTop = "#0284c7";
                gradBot = "#0f172a";
                borderColor = "#38bdf8";
                borderWidth = 2.8;
                statusLabel = `LEARNING (${cardCount - newCount}/${cardCount})`;
            } else {
                gradTop = "#334155";
                gradBot = "#1e293b";
                borderColor = "#94a3b8";
                borderWidth = 2.0;
                statusLabel = `NEW (${cardCount})`;
            }

            // Background fill
            const grad = ctx.createLinearGradient(nx, ny, nx, ny + this.nodeHeight);
            grad.addColorStop(0, gradTop);
            grad.addColorStop(1, gradBot);
            ctx.fillStyle = grad;
            this._drawNodeShape(ctx, nx, ny, this.nodeWidth, this.nodeHeight, mode);
            ctx.fill();

            // Border
            ctx.lineWidth = isSelected ? borderWidth + 1.2 : borderWidth;
            ctx.strokeStyle = isSelected ? (theme.accent || "#38bdf8") : borderColor;
            if (isSelected) {
                ctx.setLineDash([6, 3]);
            } else {
                ctx.setLineDash([]);
            }
            this._drawNodeShape(ctx, nx, ny, this.nodeWidth, this.nodeHeight, mode);
            ctx.stroke();
            ctx.setLineDash([]);

            // Title
            ctx.fillStyle = "#f8fafc";
            ctx.font = "bold 13px -apple-system, BlinkMacSystemFont, Roboto, sans-serif";
            const title = note.title || "Untitled";
            const label = this.labelNodes.get(note.id);
            if (label) {
                label.style.color = "#f8fafc";
                label.style.width = `${isDue ? this.nodeWidth - 62 : this.nodeWidth - 28}px`;
                label.style.transform = `translate(${this.canvas.offsetLeft + this.offsetX + (nx + 14) * this.scale}px,${this.canvas.offsetTop + this.offsetY + (ny + 8) * this.scale}px) scale(${this.scale})`;
            }

            // Subtitle (Mode + status label)
            const modeIcon = mode === "serial" ? "⚡ Serial" : (mode === "cloze" ? "✂️ Cloze" : "🧩 Standard");
            ctx.fillStyle = isDue ? "#fca5a5" : "#cbd5e1";
            ctx.font = "11px -apple-system, BlinkMacSystemFont, Roboto, sans-serif";
            ctx.fillText(`${modeIcon} • ${statusLabel}`, nx + 14, ny + 48);

            // Due Badge
            if (isDue) {
                ctx.fillStyle = theme.accent || "#F02A8C";
                ctx.beginPath();
                const bx = nx + this.nodeWidth - 44;
                const by = ny + 12;
                ctx.roundRect ? ctx.roundRect(bx, by, 34, 18, 4) : ctx.rect(bx, by, 34, 18);
                ctx.fill();

                ctx.fillStyle = "#ffffff";
                ctx.font = "bold 10px sans-serif";
                ctx.fillText("DUE", bx + 6, by + 13);
            }
        }

        ctx.restore();
    }

    _drawTruncatedText(ctx, text, x, y, maxWidth) {
        if (ctx.measureText(text).width <= maxWidth) {
            ctx.fillText(text, x, y);
            return;
        }
        let t = text;
        while (t.length > 0 && ctx.measureText(t + "…").width > maxWidth) {
            t = t.substring(0, t.length - 1);
        }
        ctx.fillText(t + "…", x, y);
    }
}

if (typeof window !== "undefined") {
    window.TouchGraphView = TouchGraphView;
}
