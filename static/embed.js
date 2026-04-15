/**
 * Nexar Fleet Sales Agent — Embed Widget
 * Drop this script via Google Tag Manager as a Custom HTML tag.
 * It injects a floating chat button that opens the agent in an iframe overlay.
 */
(function () {
  if (window.__nexarFleetWidgetLoaded) return;
  window.__nexarFleetWidgetLoaded = true;

  var AGENT_URL = 'https://fleet-sales-agent.nexar.app';
  var NEXAR_BLUE = '#0057FF';
  var CLOSE_COLOR = '#444';

  /* ── Styles ─────────────────────────────────────────────────────────── */
  var style = document.createElement('style');
  style.textContent = [
    '#nxr-chat-btn{',
      'position:fixed;bottom:24px;right:24px;z-index:999998;',
      'width:56px;height:56px;border-radius:50%;',
      'background:' + NEXAR_BLUE + ';',
      'border:none;cursor:pointer;',
      'box-shadow:0 4px 16px rgba(0,0,0,0.25);',
      'display:flex;align-items:center;justify-content:center;',
      'transition:transform .2s,box-shadow .2s;',
    '}',
    '#nxr-chat-btn:hover{transform:scale(1.08);box-shadow:0 6px 20px rgba(0,0,0,0.32);}',
    '#nxr-chat-overlay{',
      'position:fixed;bottom:96px;right:24px;z-index:999999;',
      'width:400px;height:600px;',
      'border-radius:16px;overflow:hidden;',
      'box-shadow:0 8px 40px rgba(0,0,0,0.22);',
      'display:none;flex-direction:column;',
      'background:#fff;',
    '}',
    '#nxr-chat-overlay.open{display:flex;}',
    '#nxr-chat-header{',
      'background:' + NEXAR_BLUE + ';',
      'padding:12px 16px;display:flex;align-items:center;justify-content:space-between;',
      'flex-shrink:0;',
    '}',
    '#nxr-chat-header span{color:#fff;font-family:sans-serif;font-size:14px;font-weight:600;}',
    '#nxr-close-btn{',
      'background:none;border:none;cursor:pointer;',
      'color:#fff;font-size:20px;line-height:1;padding:0 4px;',
    '}',
    '#nxr-chat-frame{width:100%;flex:1;border:none;}',
    /* Mobile: full-screen overlay */
    '@media(max-width:480px){',
      '#nxr-chat-overlay{',
        'bottom:0;right:0;left:0;width:100%;height:90vh;border-radius:16px 16px 0 0;',
      '}',
    '}',
  ].join('');
  document.head.appendChild(style);

  /* ── Overlay ─────────────────────────────────────────────────────────── */
  var overlay = document.createElement('div');
  overlay.id = 'nxr-chat-overlay';
  overlay.innerHTML =
    '<div id="nxr-chat-header">' +
      '<span>Nexar Fleet Assistant</span>' +
      '<button id="nxr-close-btn" aria-label="Close chat">&times;</button>' +
    '</div>' +
    '<iframe id="nxr-chat-frame" src="' + AGENT_URL + '" allow="clipboard-write" title="Nexar Fleet Sales Assistant"></iframe>';
  document.body.appendChild(overlay);

  /* ── Floating button ─────────────────────────────────────────────────── */
  var btn = document.createElement('button');
  btn.id = 'nxr-chat-btn';
  btn.setAttribute('aria-label', 'Chat with Nexar Fleet');
  btn.innerHTML =
    '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
      '<path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2Z" fill="white"/>' +
    '</svg>';
  document.body.appendChild(btn);

  /* ── Interactions ────────────────────────────────────────────────────── */
  var isOpen = false;

  function openWidget() {
    overlay.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
    isOpen = true;
  }

  function closeWidget() {
    overlay.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
    isOpen = false;
  }

  btn.addEventListener('click', function () {
    isOpen ? closeWidget() : openWidget();
  });

  document.getElementById('nxr-close-btn').addEventListener('click', closeWidget);

  /* Close on outside click */
  document.addEventListener('click', function (e) {
    if (isOpen && !overlay.contains(e.target) && e.target !== btn) {
      closeWidget();
    }
  });

  /* Close on Escape */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen) closeWidget();
  });
})();
