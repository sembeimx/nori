/**
 * Nori CSRF shim — signed double-submit cookie (v2.0.0)
 *
 * Before any form is submitted, this shim reads the visitor's own CSRF cookie
 * and writes its raw value into every <input name="_csrf_token"> field, replacing
 * any stale server-rendered (possibly masked) value that may have been baked into
 * a cached page by a different visitor.
 *
 * It also patches fetch() and XMLHttpRequest so that all same-origin unsafe
 * requests carry X-CSRF-Token: <cookie value> automatically.
 *
 * Wire format: the cookie value IS the signed structure "{nonce}.{sig}".
 * The shim copies this value raw — it performs no HMAC computation and requires
 * no server secret. The server validates via two checks:
 *   (1) Verify sig = HMAC-SHA256(SECRET_KEY, nonce) — detects forged cookies.
 *   (2) Compare submitted value to cookie value — double-submit match.
 *
 * IMPORTANT: If you set CSRF_COOKIE_NAME to something other than 'csrftoken',
 * update the COOKIE_NAME constant below to match.
 *
 * REQ-CSRF-012, design §6.
 */

(function () {
    'use strict';

    // Name of the CSRF cookie. Must match CSRF_COOKIE_NAME in settings.py.
    var COOKIE_NAME = 'csrftoken';

    /**
     * Read a cookie value by name from document.cookie.
     * Returns an empty string when the cookie is absent.
     */
    function readCookie(name) {
        var prefix = name + '=';
        var parts = document.cookie.split(';');
        for (var i = 0; i < parts.length; i++) {
            var part = parts[i].trim();
            if (part.indexOf(prefix) === 0) {
                return part.substring(prefix.length);
            }
        }
        return '';
    }

    /**
     * Determine whether a URL is same-origin.
     * Cross-origin requests must not carry the CSRF token.
     */
    function isSameOrigin(url) {
        if (!url || url.charAt(0) === '/' || url.charAt(0) === '#' || url.charAt(0) === '?') {
            return true;
        }
        try {
            var target = new URL(url);
            return target.origin === window.location.origin;
        } catch (e) {
            return false;
        }
    }

    var UNSAFE_METHODS = /^(POST|PUT|DELETE|PATCH)$/i;

    /**
     * Patch forms: on submit, overwrite _csrf_token fields with the visitor's
     * own raw cookie value, correcting any stale cached value in the HTML.
     */
    function patchForms() {
        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (!form || !form.elements) {
                return;
            }
            var tokenValue = readCookie(COOKIE_NAME);
            if (!tokenValue) {
                return;
            }
            var inputs = form.elements;
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].name === '_csrf_token') {
                    inputs[i].value = tokenValue;
                }
            }
        }, true);
    }

    /**
     * Patch fetch() to add X-CSRF-Token on same-origin unsafe requests.
     */
    function patchFetch() {
        if (typeof window.fetch !== 'function') {
            return;
        }
        var originalFetch = window.fetch.bind(window);
        window.fetch = function (input, init) {
            init = init || {};
            var method = (init.method || 'GET').toUpperCase();
            var url = (typeof input === 'string') ? input : (input.url || '');
            if (UNSAFE_METHODS.test(method) && isSameOrigin(url)) {
                var tokenValue = readCookie(COOKIE_NAME);
                if (tokenValue) {
                    var headers = new Headers(init.headers || {});
                    if (!headers.has('X-CSRF-Token')) {
                        headers.set('X-CSRF-Token', tokenValue);
                    }
                    init = Object.assign({}, init, { headers: headers });
                }
            }
            return originalFetch(input, init);
        };
    }

    /**
     * Patch XMLHttpRequest to add X-CSRF-Token on same-origin unsafe requests.
     */
    function patchXHR() {
        if (typeof XMLHttpRequest === 'undefined') {
            return;
        }
        var originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function (method, url) {
            this._csrfMethod = method;
            this._csrfUrl = url;
            return originalOpen.apply(this, arguments);
        };
        var originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function () {
            if (UNSAFE_METHODS.test(this._csrfMethod || '') && isSameOrigin(this._csrfUrl || '')) {
                var tokenValue = readCookie(COOKIE_NAME);
                if (tokenValue) {
                    this.setRequestHeader('X-CSRF-Token', tokenValue);
                }
            }
            return originalSend.apply(this, arguments);
        };
    }

    document.addEventListener('DOMContentLoaded', function () {
        patchForms();
        patchFetch();
        patchXHR();
    });
}());
