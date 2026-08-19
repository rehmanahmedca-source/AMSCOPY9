/* AMS lazy modal loader v2 — one robust fetch-then-open helper for every
   on-demand edit/view modal (sales, bookings, pending bills, clients).

   Fixes the old "click edit -> overlay stuck, keeps loading, no result":
     1. Instant visible spinner the moment Edit is clicked (no dead wait).
     2. Hard 20s timeout (AbortController) — a stalled request can never
        hang the UI forever.
     3. Double-click / re-click guard per host — no ghost overlays, and the
        lock is held across retries so a double-fired Retry can't double-fetch.
     4. Built-in RETRY button on failure (timeout, network error, HTTP
        error, or a response missing the modal markup).  Cancelling or
        closing the error dialog always frees the lock, so Edit works again.
     5. Clean teardown when the real modal closes (dispose + clear host).

   Usage (page script):
     AMSLazyModal.load({
         hostId:   'lazyEditSaleModalHost',
         url:      '/direct_sales/42/edit-modal',
         selector: '[id^="editSaleModal"]',
         label:    'Loading sale form…',
         onReady:  (modalEl) => { …page-specific init…; }   // optional
     });
*/
(function () {
    "use strict";

    var DEFAULT_TIMEOUT_MS = 20000;
    var inFlight = {};            // hostId -> true while a load/retry is in flight
    var activeHost = null;        // hostId currently using the shared loader dialog
    var loaderState = 'idle';     // 'idle' | 'loading' | 'error'
    var loaderModalEl = null;     // the reusable spinner/error modal element

    function ensureLoaderModal() {
        if (loaderModalEl && document.body.contains(loaderModalEl)) return loaderModalEl;
        var wrap = document.createElement('div');
        wrap.innerHTML =
            '<div class="modal fade" id="amsLazyModalLoader" tabindex="-1">' +
            '  <div class="modal-dialog modal-dialog-centered">' +
            '    <div class="modal-content border-secondary bg-dark text-white" style="min-width:280px;">' +
            '      <div class="modal-body text-center py-4">' +
            '        <div id="amsLazyLoaderState"></div>' +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '</div>';
        loaderModalEl = wrap.firstElementChild;
        // If the user closes the error dialog (Cancel button or ESC), the
        // lock must be freed so Edit works again immediately.
        loaderModalEl.addEventListener('hidden.bs.modal', function () {
            if (loaderState === 'error' && activeHost) {
                releaseHost(activeHost);
            }
            loaderState = 'idle';
        });
        document.body.appendChild(loaderModalEl);
        return loaderModalEl;
    }

    function spinnerState(label) {
        return '<div class="spinner-border text-warning mb-3" role="status"></div>' +
               '<div class="fw-bold">' + (label || 'Loading…') + '</div>' +
               '<div class="text-white-50 x-small mt-1">This takes a second — it will appear automatically.</div>';
    }

    function errorState(message, onRetry) {
        var div = document.createElement('div');
        div.innerHTML =
            '<i class="bi bi-exclamation-triangle-fill text-danger" style="font-size:2rem;"></i>' +
            '<div class="fw-bold mt-2">The form could not be loaded</div>' +
            '<div class="text-white-50 x-small mt-1 mb-3">' + message + '</div>' +
            '<button type="button" class="btn btn-warning btn-sm fw-bold px-4">Retry</button>' +
            '<button type="button" class="btn btn-outline-secondary btn-sm ms-2">Cancel</button>';
        div.querySelector('.btn-warning').addEventListener('click', onRetry);
        div.querySelector('.btn-outline-secondary').addEventListener('click', function () {
            bootstrap.Modal.getInstance(document.getElementById('amsLazyModalLoader'))?.hide();
        });
        return div;
    }

    function showLoading(label) {
        var el = ensureLoaderModal();
        loaderState = 'loading';
        el.querySelector('#amsLazyLoaderState').innerHTML = spinnerState(label);
        bootstrap.Modal.getOrCreateInstance(el).show();
    }

    function showError(message, onRetry) {
        var el = ensureLoaderModal();
        loaderState = 'error';
        el.querySelector('#amsLazyLoaderState').replaceChildren(errorState(message, onRetry));
        bootstrap.Modal.getOrCreateInstance(el).show();
    }

    function hideLoader() {
        if (loaderModalEl) {
            bootstrap.Modal.getInstance(loaderModalEl)?.hide();
        }
    }

    function releaseHost(hostId) {
        var host = document.getElementById(hostId);
        inFlight[hostId] = false;
        if (host) host.removeAttribute('aria-busy');
        if (activeHost === hostId) activeHost = null;
    }

    function load(opts) {
        var hostId = opts.hostId;
        var host = document.getElementById(hostId);
        if (!host || !opts.url) {
            console.error('[AMSLazyModal] missing host or url — hostId=' + hostId + ' url=' + opts.url);
            return;
        }
        if (inFlight[hostId]) return;           // already loading / retrying — ignore re-clicks
        inFlight[hostId] = true;
        activeHost = hostId;
        host.setAttribute('aria-busy', 'true');

        function attempt() {
            showLoading(opts.label);
            var controller = new AbortController();
            var timer = setTimeout(function () { controller.abort(); }, DEFAULT_TIMEOUT_MS);

            fetch(opts.url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, signal: controller.signal })
                .then(function (response) {
                    clearTimeout(timer);
                    if (!response.ok) throw new Error('Server returned ' + response.status + '. Try again.');
                    return response.text();
                })
                .then(function (html) {
                    hideLoader();
                    host.innerHTML = html;
                    var modalEl = host.querySelector(opts.selector || '[class^="modal"]');
                    if (!modalEl) throw new Error('The form was not returned by the server. Try again.');
                    if (typeof opts.onReady === 'function') opts.onReady(modalEl);
                    modalEl.addEventListener('hidden.bs.modal', function () {
                        bootstrap.Modal.getInstance(modalEl)?.dispose();
                        host.replaceChildren();
                    }, { once: true });
                    releaseHost(hostId);
                    bootstrap.Modal.getOrCreateInstance(modalEl).show();
                })
                .catch(function (error) {
                    clearTimeout(timer);
                    var msg = (error && error.name === 'AbortError')
                        ? 'The request timed out (20s). Check your connection and try again.'
                        : ((error && error.message) || 'Network error. Try again.');
                    console.error('[AMSLazyModal]', opts.url, error);
                    // Lock stays held across retries; Cancel / closing the
                    // dialog frees it (see hidden.bs.modal above).
                    showError(msg, function () { attempt(); });
                });
        }

        attempt();
    }

    window.AMSLazyModal = { load: load, TIMEOUT_MS: DEFAULT_TIMEOUT_MS };
})();
