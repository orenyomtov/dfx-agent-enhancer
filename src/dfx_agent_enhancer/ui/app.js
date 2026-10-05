// DFX Agent Enhancer page. Renders the snapshot Python pushes every 2 seconds.
// One page, two views: #panel (the open rack) and #mini (the rack minimized).
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  // Bar colours sampled from the original: [fill at the top of the scale, fill at the bottom, track top, track bottom]
  var BARS = [
    ["#c8ea36", "#264f00", "#2a3018", "#30351c"],
    ["#4ec808", "#06582c", "#213018", "#27351c"],
    ["#02d883", "#045556", "#183026", "#1c352b"],
    ["#02d2d2", "#042e57", "#183030", "#1c3535"],
    ["#2d57da", "#042d55", "#1c2130", "#212835"],
    ["#8230d8", "#562d55", "#261c30", "#2b2235"],
    ["#da2d84", "#55042c", "#301c26", "#35222c"],
    ["#da2d2d", "#550404", "#301c1c", "#352222"],
    ["#d68206", "#7f2e03", "#302618", "#352c1c"],
    ["#cec902", "#805804", "#303018", "#35351c"]
  ];

  function api() { return window.pywebview && window.pywebview.api; }
  function call(name, arg) {
    var a = api();
    if (!a || !a[name]) return Promise.resolve(null);
    return arg === undefined ? a[name]() : a[name](arg);
  }

  // ------------------------------------------------------------ 7-segment digits
  // The original column is 23px wide and holds one 9px digit. To show values like 84k or 0.2G
  // without widening it, the LCD here has three narrow cells (5.4 x 13) at the same height.
  var W = 5.4, H = 13, T = 1.45, G = 0.3, CELLS = 3;
  function hseg(y) {
    var x1 = T / 2 + G, x2 = W - T / 2 - G, h = T / 2;
    return [[x1, y], [x1 + h, y - h], [x2 - h, y - h], [x2, y], [x2 - h, y + h], [x1 + h, y + h]];
  }
  function vseg(x, y1, y2) {
    var h = T / 2;
    return [[x, y1], [x + h, y1 + h], [x + h, y2 - h], [x, y2], [x - h, y2 - h], [x - h, y1 + h]];
  }
  var SEG = {
    a: hseg(T / 2), g: hseg(H / 2), d: hseg(H - T / 2),
    f: vseg(T / 2, T / 2 + G, H / 2 - G), b: vseg(W - T / 2, T / 2 + G, H / 2 - G),
    e: vseg(T / 2, H / 2 + G, H - T / 2 - G), c: vseg(W - T / 2, H / 2 + G, H - T / 2 - G)
  };
  var DIG = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "", G: "acdef", $: "acdfg"
  };
  // letters the 7 segments cannot show, drawn as strokes in the same weight (designed on a 7 x 13 cell)
  var EXTRA = {
    k: '<path class="on" d="M0 0.4h1.9v12.2H0zM1.6 7.2 5.6 3.6h1.4v.9L2.6 8.2zM2.9 6.9l4.1 5.4v.3H5.3L1.9 8z"/>',
    M: '<path class="on" d="M0 .4h1.9v12.2H0zM5.1 .4H7v12.2H5.1zM1.4 .6l2.1 4.2 2.1-4.2v2.6L3.5 7.6 1.4 3.2z"/>'
  };
  function pts(p) { return p.map(function (q) { return q[0].toFixed(2) + "," + q[1].toFixed(2); }).join(" "); }
  var GHOST = Object.keys(SEG).map(function (k) { return '<polygon class="ghost" points="' + pts(SEG[k]) + '"/>'; }).join("");

  function digitSVG(ch, dp) {
    var body = GHOST;
    if (EXTRA[ch]) body += '<g transform="scale(' + (W / 7).toFixed(4) + ' 1)">' + EXTRA[ch] + "</g>";
    else (DIG[ch] || "").split("").forEach(function (s) { body += '<polygon class="on" points="' + pts(SEG[s]) + '"/>'; });
    // $: the S of the 7 segments with a stroke through it, reaching past the cell like a printed $
    if (ch === "$") body += '<rect class="on" x="' + (W / 2 - 0.45).toFixed(2) + '" y="-1.1" width=".9" height="' + (H + 2.2) + '"/>';
    body += '<circle class="' + (dp ? "dp" : "ghost") + '" cx="' + (W + 0.6) + '" cy="' + (H - 0.7) + '" r=".6"/>';
    return '<svg viewBox="0 0 ' + W + " " + H + '">' + body + "</svg>";
  }
  // Each row draws only the cells its text needs (1 to 3; -- is 2) and the row is centred on the
  // column, so a single digit sits where the original's one digit sat.
  function digitRow(text) {
    var cells = [];
    for (var i = 0; i < text.length; i++) {
      if (text[i] === "." && cells.length) cells[cells.length - 1].dp = true;
      else cells.push({ ch: text[i], dp: false });
    }
    return cells.slice(-CELLS).map(function (c) { return digitSVG(c.ch, c.dp); }).join("");
  }
  // every value fits three cells (a decimal point rides on its cell): 7, 412, 9.9k, 84k, 0.8M, 12M, 0.2G;
  // null (no usage data) shows --
  function fmtCount(n) {
    if (n === null || n === undefined) return "--";
    if (n < 1000) return String(n);
    if (n < 1e4) return (Math.floor(n / 100) / 10).toFixed(1) + "k";
    if (n < 1e5) return Math.floor(n / 1000) + "k";
    if (n < 1e7) return (Math.floor(n / 1e5) / 10).toFixed(1) + "M";
    if (n < 1e8) return Math.floor(n / 1e6) + "M";
    return Math.min(9.9, Math.floor(n / 1e8) / 10).toFixed(1) + "G";     // a heavy week: 0.2G
  }
  // dollars, also in three cells: $0, $0.4, $4.2, $42, then without the sign 420, 4.2k, 42k, 0.4M
  function fmtUsd(n) {
    if (n === null || n === undefined) return "--";
    if (n === 0) return "$0";
    if (n < 9.95) return "$" + n.toFixed(1);
    if (n < 99.5) return "$" + Math.round(n);
    if (n < 999.5) return String(Math.round(n));
    if (n < 9950) return (n / 1000).toFixed(1) + "k";
    if (n < 99500) return Math.round(n / 1000) + "k";
    return Math.min(9.9, n / 1e6).toFixed(1) + "M";
  }

  // ------------------------------------------------------------ static parts
  function grad(c) { return "linear-gradient(" + c[0] + "," + c[1] + ")"; }
  function buildBars(tracks, fills, cls, left, pitch) {
    for (var i = 0; i < 10; i++) {
      var t = document.createElement("div");
      t.className = cls;
      t.style.left = left + pitch * i + "px";
      t.style.background = "linear-gradient(" + BARS[i][2] + "," + BARS[i][3] + ")";
      tracks.appendChild(t);
      var f = document.createElement("div");
      f.className = cls;
      f.style.left = left + pitch * i + "px";
      f.innerHTML = '<div class="fill"></div>';
      f.firstChild.style.backgroundImage = grad(BARS[i]);
      fills.appendChild(f);
    }
  }
  // Each bar owns its whole 23 px column (x25.5 + 23 i, from the top of the track to the axis
  // row), so hovering the empty space above a short bar shows its tooltip too.
  function buildCols() {
    for (var i = 0; i < 10; i++) {
      var c = document.createElement("div");
      c.className = "col";
      c.dataset.i = i;
      c.style.left = 12.5 + 23 * i + "px";
      $("cols").appendChild(c);
    }
  }
  function buildDigits() {
    var host = $("digits");
    for (var i = 0; i < 5; i++) {
      var r = document.createElement("div");
      r.className = "drow";
      r.style.top = 8 + 28 * i + "px";
      host.appendChild(r);
    }
  }
  buildBars($("tracks"), $("fills"), "bar", 19, 23);
  buildBars($("mtracks"), $("mfills"), "mbar", 7.9, 8.71);   // x32.6 + 8.71 n on the deck
  buildCols();
  buildDigits();

  // ------------------------------------------------------------ time axis
  // Python sends [{x: 0..1, text}]: x 0 is the window start (x25.5, the gap before bar 1), 1 is
  // now (x255.5). The first label is left-aligned at x19 and the last right-aligned at x254, as
  // the original 40Hz / 14kHz; interior labels are centred, and dropped when they would come
  // within 4 px of a label already placed. Widths come from a canvas, so this works while the
  // panel is not displayed.
  var measure = document.createElement("canvas").getContext("2d");
  measure.font = "italic bold 9px Arial";
  function textW(t) { return measure.measureText(t).width - 0.15 * t.length; }
  var axisKey = "";
  function renderAxis(ticks) {
    var key = JSON.stringify(ticks || []);
    if (key === axisKey || !ticks || ticks.length < 2) return;
    axisKey = key;
    var n = ticks.length, boxes = ticks.map(function (t, i) {
      var w = textW(t.text), l = i === 0 ? 6 : i === n - 1 ? 241 - w : 12.5 + 230 * t.x - w / 2;
      return { l: l, r: l + w, text: t.text };
    });
    var last = boxes[n - 1], shown = [boxes[0]];
    for (var i = 1; i < n - 1; i++) {
      var b = boxes[i];
      if (b.l >= shown[shown.length - 1].r + 4 && b.r <= last.l - 4) shown.push(b);
    }
    shown.push(last);
    var host = $("axis");
    host.innerHTML = "";
    shown.forEach(function (b) {
      var e = document.createElement("i");
      e.textContent = b.text;
      e.style.left = b.l.toFixed(1) + "px";
      host.appendChild(e);
    });
  }

  // ------------------------------------------------------------ tooltips
  // Native title tooltips do not show while the app is inactive (almost always), so the rack has
  // one tooltip of its own, driven by the same hover tracking as the highlight. Bars show theirs
  // at once (sliding across the bars scrubs); other controls after a 500 ms rest.
  var tip = $("tip"), tipFor = null, tipTimer = null, barTips = [], barHeights = [];
  function tipTarget(el) { return el && el.closest ? el.closest("#panel [data-tip], #panel .col") : null; }
  function hotBar(i, on) {
    $("tracks").children[i].classList.toggle("hot", on);
    $("fills").children[i].classList.toggle("hot", on);
  }
  function hideTip() { tip.style.display = "none"; }
  function setTipTarget(t) {
    if (t === tipFor) return;
    if (tipFor && tipFor.classList.contains("col")) hotBar(+tipFor.dataset.i, false);
    tipFor = t;
    clearTimeout(tipTimer);
    hideTip();
    if (!t) return;
    if (t.classList.contains("col")) { hotBar(+t.dataset.i, true); showTip(); }
    else tipTimer = setTimeout(showTip, 500);
  }
  function showTip() {
    var t = tipFor;
    if (!t) return;
    var bar = t.classList.contains("col"), text = bar ? barTips[+t.dataset.i] : t.dataset.tip;
    if (!text) { hideTip(); return; }
    var lines = text.split("\n");
    tip.className = "tip" + (bar ? " for-bar" : "");
    tip.innerHTML = "";
    lines.forEach(function (line, k) {
      var d = document.createElement("div");
      if (lines.length > 1 && k === 0) d.className = "h";
      d.textContent = line;
      tip.appendChild(d);
    });
    tip.style.display = "block";
    var w = tip.offsetWidth, h = tip.offsetHeight, x, y;
    if (bar) {
      // At the top of the plot (y66), centred on the bar, inside the screen right of the Y labels
      // (x30-256). It must never hide the bar it describes: when the bar reaches up into the box,
      // the box goes beside the bar (the side with more room), or, if it is too wide for that,
      // above the track, over the tabs.
      var i = +t.dataset.i, top = 76 + 76 * (1 - (barHeights[i] || 0));
      x = Math.max(30, Math.min(256 - w, 37 + 23 * i - w / 2));
      y = 66;
      if (top < y + h + 2) {
        var right = 45 + 23 * i, left = 29 + 23 * i - w;
        if (i < 5 && right + w <= 256) x = right;
        else if (i >= 5 && left >= 30) x = left;
        else y = 75 - h;
      }
    } else {             // above the control, inside the rack
      var r = t.getBoundingClientRect();
      x = Math.max(6, Math.min(266 - w, r.left + r.width / 2 - w / 2));
      y = r.top - h - 3;
      if (y < 6) y = r.bottom + 3;
    }
    tip.style.left = Math.round(x) + "px";
    tip.style.top = Math.round(y) + "px";
  }

  // ------------------------------------------------------------ render
  // All logic is in Python (snapshot.py); the page only applies heights, fills, LEDs and text.
  var ROWS = ["sessions", "subagents", "spend", "tools", "errors"];

  function setHeights(host, hs) {
    var f = host.querySelectorAll(".fill");
    for (var i = 0; i < f.length; i++) f[i].style.height = ((hs && hs[i]) || 0) * 100 + "%";
  }
  function setRow(r, n, loading) {
    var row = $("row-" + r.id);
    var w = (Math.max(0, Math.min(1, r.fill || 0)) * 78).toFixed(1);   // the thumb stops at the track's right end (x144)
    row.querySelector(".fill").style.width = w + "px";
    row.querySelector(".thumb").style.left = (2 + +w) + "px";
    row.querySelector(".led").className = "led " + (loading ? "off" : (r.led || "off"));
    row.dataset.tip = r.tip || "";
    var d = $("digits").children[n], text = loading ? "--" : (r.id === "spend" ? fmtUsd : fmtCount)(r.value);   // not ready, not zero
    d.dataset.tip = r.tip || "";
    if (d.dataset.v !== text) { d.dataset.v = text; d.innerHTML = digitRow(text); }
  }
  function renderToggles(t) {
    t = t || {};
    var c = $("chime"), p = $("top");
    c.classList.toggle("on", !!t.chime);
    c.dataset.tip = "Chime: " + (t.chime ? "on" : "off") +
      ". Plays a sound when a session stops working (it finished, or it waits for your answer).";
    p.classList.toggle("on", !!t.onTop);
    p.dataset.tip = "Keep on top: " + (t.onTop ? "on. The rack stays above other windows." :
      "off. Other windows can cover the rack.");
  }

  function renderPanel(s) {
    var sp = s.spectrum[s.metric];
    setHeights($("fills"), sp.heights);
    var yl = $("ylab").children;
    for (var i = 0; i < yl.length; i++) yl[i].textContent = sp.labels[i] || "";
    $("lime-text").textContent = sp.tab;
    $("tab-lime").dataset.tip = sp.tip || "";
    renderAxis(s.axis);
    barTips = sp.tips || [];
    barHeights = sp.heights || [];
    $("note").textContent = s.loading ? "Loading…" : (s.metric === "spend" && sp.known === false ? "No usage data" : "");
    var ro = s.readout || { text: "Loading…", led: "off" };
    $("tab-text").textContent = ro.text;
    $("rled").className = "rled " + (ro.led || "off");
    $("readout").dataset.tip = ro.tip || "";
    s.rows.forEach(function (r) { setRow(r, ROWS.indexOf(r.id), s.loading); });
    renderToggles(s.toggles);

    var keys = document.querySelectorAll(".wkey");
    for (var k = 0; k < keys.length; k++) keys[k].classList.toggle("on", keys[k].dataset.w === s.window);
    var mk = document.querySelectorAll(".bkey");
    for (var m = 0; m < mk.length; m++) mk[m].classList.toggle("on", mk[m].dataset.m === s.metric);
    if (tipFor && tip.style.display === "block") showTip();   // the bars moved on: refresh the text
  }

  // The deck is the rack minimized: the same graph, and its current value as the big text. A tag
  // in the corner names the graph's window, as the rack's key does, so a value per minute over an
  // hourly graph is not read as the bars' own value.
  var WIN = { now: "NOW", "1h": "1H", today: "TODAY", week: "WEEK" };
  function renderMini(s) {
    var d = s.deckText || { big: "…", small: "" };
    $("mbig").textContent = d.big;
    $("msmall").textContent = d.small || "";
    $("mini-text").classList.toggle("idle", !d.small && d.big !== "…");
    setHeights($("mfills"), s.spectrum[s.metric].heights);
    $("mwin").textContent = WIN[s.window] || "";
    $("mscreen").title = s.deckTip || "Expand to the panel";
  }

  function render(s) {
    if (!s || !s.spectrum) return;
    renderPanel(s);
    renderMini(s);
  }
  window.__push = render;

  // Python switches the view; the window itself is resized by Python.
  window.__mode = function (m) {
    document.body.className = "mode-" + m;
    window.__hoverAt(-1, -1);
  };

  // ------------------------------------------------------------ wire up
  function on(el, fn) {
    el.addEventListener("click", function (e) { e.stopPropagation(); if (fn) fn.call(this, e); });
  }
  function radio(sel, attr, api) {
    var keys = document.querySelectorAll(sel);
    for (var k = 0; k < keys.length; k++) {
      on(keys[k], function () {
        for (var j = 0; j < keys.length; j++) keys[j].classList.toggle("on", keys[j] === this);
        call(api, this.dataset[attr]).then(render);
      });
    }
  }
  radio(".wkey", "w", "set_window");
  radio(".bkey", "m", "set_metric");
  on($("oval"), function () { call("dock"); });
  on($("chev"), function () { call("dock"); });
  on($("dash"), function () { call("hide"); });
  on($("menu"), function () { call("menu"); });
  [["chime", "chime"], ["top", "onTop"]].forEach(function (p) {
    on($(p[0]), function () { this.classList.toggle("on"); call("toggle", p[1]).then(render); });
  });
  on($("dome-hide"), function () { call("hide"); });
  on($("dome-expand"), function () { call("open_panel"); });
  on($("dome-menu"), function () { call("menu"); });
  on($("mini-oval"), function () { call("open_panel"); });
  // inert controls: hover and press only
  [".key-led", ".track", ".tab", ".dome:not([id])", ".mk"].forEach(function (sel) {
    var els = document.querySelectorAll(sel);
    for (var i = 0; i < els.length; i++) on(els[i], null);
  });

  // Dragging: a mouse-down on the chassis (.drag, never a control) tells Python, which moves the
  // window with the mouse in screen coordinates (pywebview's own drag region misplaced it on a
  // second display of another height).
  document.addEventListener("mousedown", function (e) {
    if (e.button === 0 && e.target.closest && e.target.closest(".drag")) call("drag_start");
  }, true);

  // The deck can be dragged by its chassis or display; a click there that did not move expands it.
  var down = null;
  $("mini").addEventListener("mousedown", function (e) { down = [e.screenX, e.screenY]; });
  $("mini").addEventListener("click", function (e) {
    if (down && Math.abs(e.screenX - down[0]) + Math.abs(e.screenY - down[1]) > 3) return;
    call("open_panel");
  });

  // Hover while another app is frontmost: WebKit only tracks the mouse in the key window, so
  // Python tells the page where the mouse is (on every move, also while the app is active), the
  // CSS treats .hover like :hover, and the tooltip follows. Returns "1" over a control (Python
  // shows the pointer cursor), else "0"; bars carry a tooltip but are not controls.
  var CTL = ".key-led, .track, .wkey, .bkey, .tab, .bandbtn, .oval, .winbtn, .dome, .mk, .moval";
  var hov = null;
  window.__hoverAt = function (x, y) {
    var el = x < 0 ? null : document.elementFromPoint(x, y);
    var c = el && el.closest ? el.closest(CTL) : null;
    if (c !== hov) {
      if (hov) hov.classList.remove("hover");
      if (c) c.classList.add("hover");
      hov = c;
    }
    setTipTarget(tipTarget(el));
    return c ? "1" : "0";
  };

  if (window.MODE) window.__mode(window.MODE);
  window.addEventListener("pywebviewready", function () { call("snapshot").then(render); });
  if (window.SAMPLE) render(window.SAMPLE);
})();
