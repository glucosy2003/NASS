/* ==========================================================================
   NASS Website — Main JavaScript
   Handles: hamburger menu, tabs, toasts, search, AJAX calls
   ========================================================================== */

document.addEventListener('DOMContentLoaded', function () {
    initHamburger();
    initTabs();
});

/* ---------- Hamburger Menu (Mobile) ---------- */
function initHamburger() {
    var hamburger = document.getElementById('hamburger');
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');
    if (!hamburger || !sidebar) return;

    hamburger.addEventListener('click', function () {
        hamburger.classList.toggle('open');
        sidebar.classList.toggle('open');
        overlay.classList.toggle('active');
    });

    if (overlay) {
        overlay.addEventListener('click', function () {
            hamburger.classList.remove('open');
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
        });
    }

    // Close sidebar on link click (mobile)
    sidebar.querySelectorAll('.sidebar-link').forEach(function (link) {
        link.addEventListener('click', function () {
            if (window.innerWidth <= 768) {
                hamburger.classList.remove('open');
                sidebar.classList.remove('open');
                overlay.classList.remove('active');
            }
        });
    });
}

/* ---------- Tabs ---------- */
function initTabs() {
    document.querySelectorAll('.tabs').forEach(function (tabBar) {
        var buttons = tabBar.querySelectorAll('.tab-btn');
        var containerId = tabBar.getAttribute('data-tab-container');
        var container = document.getElementById(containerId);
        if (!container) return;

        buttons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                // Deactivate all
                buttons.forEach(function (b) { b.classList.remove('active'); });
                container.querySelectorAll('.tab-content').forEach(function (c) {
                    c.classList.remove('active');
                });
                // Activate clicked
                btn.classList.add('active');
                var target = document.getElementById(btn.getAttribute('data-tab'));
                if (target) target.classList.add('active');
            });
        });
    });
}

/* ---------- Toast Messages ---------- */
function showToast(message, type) {
    type = type || 'success';
    var toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(function () {
        toast.remove();
    }, 3200);
}

/* ---------- AJAX Helper ---------- */
function apiPost(url, data, onSuccess, onError) {
    var csrftoken = getCookie('csrftoken');
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken,
        },
        body: JSON.stringify(data),
    })
    .then(function (resp) {
        return resp.json().then(function (body) {
            if (resp.ok) {
                if (onSuccess) onSuccess(body);
            } else {
                if (onError) onError(body);
            }
        });
    })
    .catch(function (err) {
        if (onError) onError({ error: err.message });
    });
}

function apiGet(url, onSuccess, onError) {
    fetch(url)
    .then(function (resp) {
        return resp.json().then(function (body) {
            if (resp.ok) {
                if (onSuccess) onSuccess(body);
            } else {
                if (onError) onError(body);
            }
        });
    })
    .catch(function (err) {
        if (onError) onError({ error: err.message });
    });
}

/* ---------- CSRF Cookie Helper ---------- */
function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
}

/* ---------- Format Currency ---------- */
function fmtMoney(val) {
    var num = parseFloat(val);
    if (isNaN(num)) return 'MK 0.00';
    return 'MK ' + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ---------- Format Quantity ---------- */
function fmtQty(val) {
    var num = parseFloat(val);
    if (isNaN(num)) return '0';
    // Remove trailing zeros but keep at least one decimal if needed
    var text = num.toFixed(3);
    text = text.replace(/0+$/, '').replace(/\.$/, '');
    return text;
}
