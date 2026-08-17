/* AMS UI v2 — runtime helpers (side-sheet, flatpickr defaults, theme-aware combobox).
   Loaded after theme.js. Safe to load on legacy pages — features are opt-in. */
(function () {
    "use strict";

    /* -----------------------------------------------------------------
       Side-sheet drawer (replaces fullscreen modal forms)
       Markup contract:
         <div class="ui-sheet" id="someSheet" data-ui-sheet>
           <div class="ui-sheet-header">…<button data-ui-sheet-close></button></div>
           <div class="ui-sheet-body">…</div>
           <div class="ui-sheet-footer">…</div>
         </div>
       Open with: AMSUI.openSheet('someSheet')   or
                  <button data-ui-sheet-target="someSheet">…</button>
       ----------------------------------------------------------------- */
    var backdrop = null;
    function ensureBackdrop() {
        if (backdrop) return backdrop;
        backdrop = document.createElement("div");
        backdrop.className = "ui-sheet-backdrop";
        backdrop.addEventListener("click", closeAllSheets);
        document.body.appendChild(backdrop);
        return backdrop;
    }
    function openSheet(idOrEl) {
        var el = (typeof idOrEl === "string") ? document.getElementById(idOrEl) : idOrEl;
        if (!el) return;
        var bd = ensureBackdrop();
        bd.classList.add("show");
        el.classList.add("show");
        document.body.style.overflow = "hidden";
        el.dispatchEvent(new CustomEvent("ams:sheetopen"));
    }
    function closeSheet(idOrEl) {
        var el = (typeof idOrEl === "string") ? document.getElementById(idOrEl) : idOrEl;
        if (!el) return;
        el.classList.remove("show");
        var anyOpen = document.querySelector(".ui-sheet.show");
        if (!anyOpen && backdrop) {
            backdrop.classList.remove("show");
            document.body.style.overflow = "";
        }
        el.dispatchEvent(new CustomEvent("ams:sheetclose"));
    }
    function closeAllSheets() {
        document.querySelectorAll(".ui-sheet.show").forEach(function (el) { el.classList.remove("show"); });
        if (backdrop) backdrop.classList.remove("show");
        document.body.style.overflow = "";
    }

    document.addEventListener("click", function (ev) {
        var openBtn = ev.target.closest("[data-ui-sheet-target]");
        if (openBtn) {
            ev.preventDefault();
            openSheet(openBtn.getAttribute("data-ui-sheet-target"));
            return;
        }
        var closeBtn = ev.target.closest("[data-ui-sheet-close]");
        if (closeBtn) {
            ev.preventDefault();
            var sheet = closeBtn.closest(".ui-sheet");
            if (sheet) closeSheet(sheet);
        }
    });
    document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape") closeAllSheets();
    });

    /* -----------------------------------------------------------------
       Flatpickr unified defaults (only on .ui-date / .ui-datetime inputs)
       ----------------------------------------------------------------- */
    function initDatePickers(root) {
        if (typeof flatpickr === "undefined") return;
        (root || document).querySelectorAll(".ui-date:not(.ui-pk-bound)").forEach(function (el) {
            el.classList.add("ui-pk-bound");
            flatpickr(el, { dateFormat: "Y-m-d", allowInput: true });
        });
        (root || document).querySelectorAll(".ui-datetime:not(.ui-pk-bound)").forEach(function (el) {
            el.classList.add("ui-pk-bound");
            flatpickr(el, { enableTime: true, dateFormat: "Y-m-d H:i", allowInput: true });
        });
    }

    /* -----------------------------------------------------------------
       Theme-aware combobox skin (adds ui-combobox-v2 class to existing
       .combobox-list elements on opted-in pages so theme tokens apply)
       ----------------------------------------------------------------- */
    function skinCombos(root) {
        (root || document).querySelectorAll(".ui-v2 .combobox-list").forEach(function (el) {
            el.classList.add("ui-combobox-v2");
        });
    }

    /* -----------------------------------------------------------------
       Row-click drill-down: any <tr data-href="..."> becomes navigable
       ----------------------------------------------------------------- */
    function bindRowDrill(root) {
        (root || document).querySelectorAll("tr[data-href]:not(.ui-row-bound)").forEach(function (tr) {
            tr.classList.add("ui-row-bound", "is-clickable");
            tr.addEventListener("click", function (ev) {
                if (ev.target.closest("a, button, input, label, select, textarea")) return;
                window.location.href = tr.getAttribute("data-href");
            });
        });
    }

    function initAll(root) {
        initDatePickers(root);
        skinCombos(root);
        bindRowDrill(root);
    }

    document.addEventListener("DOMContentLoaded", function () { initAll(document); });

    window.AMSUI = {
        openSheet: openSheet,
        closeSheet: closeSheet,
        closeAllSheets: closeAllSheets,
        initAll: initAll,
        initDatePickers: initDatePickers
    };
})();
