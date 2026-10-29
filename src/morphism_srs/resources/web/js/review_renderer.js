(function () {
    "use strict";

    var _typesetQueue = Promise.resolve();

    function typesetElements(elements) {
        if (!window.MathJax) {
            return;
        }
        _typesetQueue = _typesetQueue.catch(function () {}).then(function () {
            return window.MathJax.startup && window.MathJax.startup.promise;
        }).then(function () {
            if (window.MathJax.typesetClear) {
                window.MathJax.typesetClear(elements);
            }
            if (window.MathJax.typesetPromise) {
                return window.MathJax.typesetPromise(elements).catch(function (err) {
                    console.error("MathJax typeset error:", err);
                });
            }
        });
    }

    window.addEventListener("morphism-mathjax-ready", function () {
        var root = document.getElementById("review-root");
        if (root) typesetElements([root]);
    });

    window.MorphismReview = {
        updateMacros: function (macrosObj) {
            if (window.MathJax && window.MathJax.config && window.MathJax.config.tex) {
                Object.assign(window.MathJax.config.tex.macros, macrosObj || {});
            }
        },

        renderSiblingHtml: function (sib, labelPrefix) {
            var stepTitle = sib.title ? (" — " + sib.title) : "";
            return (
                '<div class="sibling-step">' +
                '<div class="sibling-header">' + labelPrefix + " Step " + (sib.step_order + 1) + stepTitle + '</div>' +
                '<div class="sibling-front">' + (sib.front_html || "") + '</div>' +
                '<div class="sibling-back">' + (sib.back_html || "") + '</div>' +
                '</div>'
            );
        },

        renderCardState: function (payload) {
            var root = document.getElementById("review-root");
            var titleEl = document.getElementById("note-title");
            var badgeEl = document.getElementById("mode-badge");
            var tagRow = document.getElementById("tag-row");
            var sibBefore = document.getElementById("siblings-before");
            var sibAfter = document.getElementById("siblings-after");
            var stepLabel = document.getElementById("active-step-label");
            var frontEl = document.getElementById("card-front");
            var dividerEl = document.getElementById("answer-divider");
            var backEl = document.getElementById("card-back");

            titleEl.textContent = payload.note_title || "Untitled Note";
            badgeEl.textContent = (payload.review_mode || "standard").toUpperCase();

            tagRow.innerHTML = "";
            (payload.tags || []).forEach(function (t) {
                var span = document.createElement("span");
                span.className = "tag-chip";
                span.textContent = "#" + t;
                tagRow.appendChild(span);
            });

            var beforeHtml = [];
            var afterHtml = [];
            var prefix = payload.review_mode === "cloze" ? "Given Context" : "Verified";
            (payload.siblings || []).forEach(function (sib) {
                if (sib.position === "after") {
                    afterHtml.push(window.MorphismReview.renderSiblingHtml(sib, prefix));
                } else {
                    beforeHtml.push(window.MorphismReview.renderSiblingHtml(sib, prefix));
                }
            });
            sibBefore.innerHTML = beforeHtml.join("");
            sibAfter.innerHTML = afterHtml.join("");

            var sOrder = (payload.step_order || 0) + 1;
            var cTitle = payload.card_title ? (" — " + payload.card_title) : "";
            if (payload.review_mode === "serial") {
                stepLabel.textContent = "Step " + sOrder + cTitle + "  [P(A_" + sOrder + " | A_j, j < " + sOrder + ")]";
            } else if (payload.review_mode === "cloze") {
                stepLabel.textContent = "Cloze Target " + sOrder + cTitle + "  [P(A_" + sOrder + " | A_j, j ≠ " + sOrder + ")]";
            } else {
                stepLabel.textContent = "Card " + sOrder + cTitle;
            }

            frontEl.innerHTML = payload.front_html || "";

            if (payload.show_answer) {
                dividerEl.style.display = "block";
                backEl.style.display = "block";
                backEl.classList.remove("ghost");
                backEl.style.visibility = "visible";
                backEl.innerHTML = payload.back_html || "";
            } else {
                dividerEl.style.display = "none";
                backEl.style.display = "none";
                backEl.classList.remove("ghost");
                backEl.style.visibility = "visible";
                backEl.innerHTML = "";
            }

            typesetElements([root]);
        },

        revealAnswer: function (backHtml) {
            var dividerEl = document.getElementById("answer-divider");
            var backEl = document.getElementById("card-back");
            if (dividerEl) dividerEl.style.display = "block";
            if (backEl) {
                backEl.style.display = "block";
                backEl.classList.remove("ghost");
                backEl.style.visibility = "visible";
                if (typeof backHtml === "string") {
                    backEl.innerHTML = backHtml;
                }
                typesetElements([backEl]);
            }
        },

        setAnswerGhost: function (isGhost) {
            var backEl = document.getElementById("card-back");
            if (backEl) {
                if (isGhost) {
                    backEl.classList.add("ghost");
                    backEl.style.visibility = "hidden";
                } else {
                    backEl.classList.remove("ghost");
                    backEl.style.visibility = "visible";
                }
            }
        },

        hideAnswer: function () {
            this.setAnswerGhost(true);
        },

        toggleAnswer: function (backHtml) {
            var backEl = document.getElementById("card-back");
            if (backEl && backEl.style.visibility === "hidden") {
                this.setAnswerGhost(false);
                return true;
            } else {
                this.setAnswerGhost(true);
                return false;
            }
        }
    };

    function isHideShortcut(e) {
        return (
            e.key === "`" ||
            e.key === "~" ||
            e.key === "|" ||
            e.key === "°" ||
            e.key === "¬" ||
            e.keyCode === 192 ||
            e.keyCode === 220 ||
            e.which === 192 ||
            e.which === 220
        );
    }

    var _isGhostHeld = false;

    window.addEventListener("keydown", function (e) {
        if (isHideShortcut(e)) {
            if (!_isGhostHeld) {
                _isGhostHeld = true;
                window.MorphismReview.setAnswerGhost(true);
            }
            e.preventDefault();
        }
    });

    window.addEventListener("keyup", function (e) {
        if (isHideShortcut(e)) {
            _isGhostHeld = false;
            window.MorphismReview.setAnswerGhost(false);
            e.preventDefault();
        }
    });
})();
