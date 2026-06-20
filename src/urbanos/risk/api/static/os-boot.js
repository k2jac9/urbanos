/*
 * os-boot.js — cinematic "Urban OS" boot sequence (the peak-end OPEN of the demo).
 *
 * Drop-in, self-contained, 100% offline: no external assets, no CDN, no fonts to fetch.
 * Another page just does:
 *     <script src="/static/os-boot.js"></script>
 *     await OSBoot.play({ onEnter: () => map.flyTo(...) });
 *
 * Public API (window.OSBoot):
 *   OSBoot.play(opts?) -> Promise<void>
 *       Injects a full-screen overlay (DOM + CSS), plays the boot animation, and
 *       RESOLVES when the user clicks "Enter ▶" (or presses Enter/Space, or after
 *       opts.autoEnterMs). On enter it fades the overlay out, removes it, then resolves.
 *       opts:
 *         onEnter   : function  — called right BEFORE resolving (kick off map fly-to / skyline rise).
 *         autoEnterMs: number   — if set, auto-trigger Enter after this many ms (unattended demos).
 *         tagline   : string    — override the tagline (default "Turning urban data into real-time insight through AI").
 *         subline   : string    — override the small line under the tagline.
 *   OSBoot.skip() -> void
 *       Immediately remove the overlay and resolve any pending play() (Esc / impatient demos).
 *
 * :root CSS custom properties read (optional, all have hardcoded fallbacks):
 *   --accent       (fallback #4f9dff)   primary azure
 *   --accent-2     (fallback #22d3ee)   secondary sky
 *   --brand-1      (fallback --accent)  brand gradient start (azure)
 *   --brand-2      (fallback #9d6bff)   brand gradient end (iris)
 *   --os-boot-bg   (fallback #05070d)   backdrop color
 */
(function () {
  "use strict";

  var ACCENT = "#4f9dff", ACCENT2 = "#22d3ee", BG = "#05070d";
  var BRAND1 = "", BRAND2 = "#9d6bff";   // brand duotone — default to accent→iris
  // Read tokens off :root if the host page defines them; otherwise keep the fallbacks.
  try {
    var rs = getComputedStyle(document.documentElement);
    var a = rs.getPropertyValue("--accent").trim();   if (a) ACCENT = a;
    var b = rs.getPropertyValue("--accent-2").trim();  if (b) ACCENT2 = b;
    var g = rs.getPropertyValue("--os-boot-bg").trim(); if (g) BG = g;
    var b1 = rs.getPropertyValue("--brand-1").trim();  if (b1) BRAND1 = b1;
    var b2 = rs.getPropertyValue("--brand-2").trim();  if (b2) BRAND2 = b2;
  } catch (_) { /* SSR / no DOM — ignore */ }
  if (!BRAND1) BRAND1 = ACCENT;                 // fall back to the accent if no brand token
  var GRAD = "linear-gradient(105deg," + BRAND1 + " 0%," + BRAND2 + " 100%)";

  var REDUCED = false;
  try { REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) {}

  var STYLE_ID = "os-boot-style";
  var active = null;   // { root, resolve, onKey, done } for the in-flight play()

  // Inject the stylesheet once. Everything is scoped under #os-boot.
  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var css = "" +
      "#os-boot{position:fixed;inset:0;z-index:2147483600;display:flex;flex-direction:column;" +
        "align-items:center;justify-content:center;gap:1.4rem;text-align:center;" +
        "background:radial-gradient(120% 120% at 50% 38%, #0a1022 0%, " + BG + " 70%);" +
        "color:#e2e8f0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
        "opacity:0;transition:opacity .5s ease;-webkit-font-smoothing:antialiased;cursor:default}" +
      "#os-boot.on{opacity:1}" +
      "#os-boot.out{opacity:0;transition:opacity .55s ease}" +
      // Faint moving grid + scanline shimmer (tasteful cyber texture).
      "#os-boot .grid{position:absolute;inset:-2px;pointer-events:none;opacity:.18;" +
        "background-image:linear-gradient(" + ACCENT + "22 1px,transparent 1px)," +
        "linear-gradient(90deg," + ACCENT + "22 1px,transparent 1px);" +
        "background-size:44px 44px;mask-image:radial-gradient(80% 70% at 50% 40%,#000 40%,transparent 100%);" +
        "-webkit-mask-image:radial-gradient(80% 70% at 50% 40%,#000 40%,transparent 100%)}" +
      "#os-boot .scan{position:absolute;inset:0;pointer-events:none;opacity:.5;" +
        "background:repeating-linear-gradient(0deg,transparent 0 3px," + ACCENT + "0c 3px 4px);" +
        "animation:osb-scan 7s linear infinite}" +
      "@keyframes osb-scan{from{background-position:0 0}to{background-position:0 200px}}" +
      // Wordmark: azure→iris brand gradient clipped to the glyphs, with a duotone
      // drop-shadow glow. The glow lives on `filter` (NOT animated), so it persists
      // after the letter-spacing entrance settles — and survives reduced-motion.
      "#os-boot .mark{position:relative;font-weight:900;font-size:clamp(2.6rem,9.4vw,5.8rem);" +
        "letter-spacing:.16em;" +
        "background:" + GRAD + ";-webkit-background-clip:text;background-clip:text;" +
        "color:transparent;-webkit-text-fill-color:transparent;" +
        "filter:drop-shadow(0 0 24px " + BRAND2 + "66) drop-shadow(0 0 9px " + BRAND1 + "88);" +
        "animation:osb-mark 1.6s cubic-bezier(.2,.7,.2,1) both}" +
      "@keyframes osb-mark{0%{opacity:0;letter-spacing:-.12em}" +
        "60%{opacity:1}100%{opacity:1;letter-spacing:.16em}}" +
      "#os-boot .tag{font-size:clamp(1rem,3.2vw,1.5rem);color:" + ACCENT2 + ";font-weight:600;" +
        "opacity:0;animation:osb-fade .8s ease .9s both}" +
      "#os-boot .sub{font-size:.86rem;color:#7d93b2;letter-spacing:.02em;" +
        "opacity:0;animation:osb-fade .8s ease 1.3s both}" +
      "@keyframes osb-fade{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}" +
      // The one bright actionable thing (Von Restorff): the Enter button.
      "#os-boot .enter{margin-top:.6rem;font:inherit;font-size:1.05rem;font-weight:800;letter-spacing:.06em;" +
        "color:#06091a;background:" + GRAD + ";" +
        "border:0;border-radius:12px;padding:.8rem 2.2rem;cursor:pointer;" +
        "box-shadow:0 0 0 1px " + BRAND1 + ",0 8px 34px " + BRAND2 + "66;" +
        "opacity:0;transform:translateY(10px) scale(.96);" +
        "animation:osb-enter .6s cubic-bezier(.2,.8,.2,1) 1.7s both,osb-pulse 2.2s ease-in-out 2.4s infinite}" +
      "#os-boot .enter:hover{filter:brightness(1.08)}" +
      "#os-boot .enter:active{transform:translateY(1px) scale(.99)}" +
      "#os-boot .enter:focus-visible{outline:2px solid #fff;outline-offset:3px}" +
      "@keyframes osb-enter{to{opacity:1;transform:none}}" +
      "@keyframes osb-pulse{0%,100%{box-shadow:0 0 0 1px " + BRAND1 + ",0 6px 30px " + BRAND2 + "55}" +
        "50%{box-shadow:0 0 0 1px " + BRAND1 + ",0 8px 44px " + BRAND2 + "aa}}" +
      "#os-boot .hint{font-size:.72rem;color:#5a6b85;margin-top:-.4rem;opacity:0;animation:osb-fade .8s ease 2s both}" +
      // Reduced motion: drop transforms/loops, keep gentle fades only.
      "@media (prefers-reduced-motion: reduce){#os-boot *{animation-duration:.01ms!important;" +
        "animation-iteration-count:1!important}#os-boot .mark{letter-spacing:.16em}" +
        "#os-boot .scan,#os-boot .grid{animation:none}}";
    var el = document.createElement("style");
    el.id = STYLE_ID;
    el.textContent = css;
    document.head.appendChild(el);
  }

  function esc(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;";
    });
  }

  function build(opts) {
    var tagline = esc(opts.tagline || "Turning urban data into real-time insight through AI");
    var subline = esc(opts.subline || "Any city's open data → lenses of intelligence · Toronto first · 100% on-device");
    var root = document.createElement("div");
    root.id = "os-boot";
    root.setAttribute("role", "dialog");
    root.setAttribute("aria-label", "UrbanOS boot screen");
    root.innerHTML =
      '<div class="grid"></div><div class="scan"></div>' +
      '<div class="mark">Urban<span class="os">OS</span></div>' +
      '<div class="tag">' + tagline + "</div>" +
      '<div class="sub">' + subline + "</div>" +
      '<button class="enter" type="button" aria-label="Enter UrbanOS">Enter ▶</button>' +
      '<div class="hint">press Enter / Space &nbsp;·&nbsp; Esc to skip</div>';
    return root;
  }

  // Fade out + remove, then fire onEnter and resolve. Idempotent per play().
  function finish(ctx, fireEnter) {
    if (ctx.done) return;
    ctx.done = true;
    document.removeEventListener("keydown", ctx.onKey, true);
    if (fireEnter && typeof ctx.opts.onEnter === "function") {
      try { ctx.opts.onEnter(); } catch (e) { console.error("OSBoot onEnter:", e); }
    }
    var root = ctx.root;
    root.classList.remove("on");
    root.classList.add("out");
    var gone = false;
    var remove = function () {
      if (gone) return; gone = true;
      if (root.parentNode) root.parentNode.removeChild(root);
      ctx.resolve();
    };
    root.addEventListener("transitionend", remove, { once: true });
    setTimeout(remove, 650); // safety net if transitionend never fires
  }

  function play(opts) {
    opts = opts || {};
    if (typeof document === "undefined") return Promise.resolve();
    // Only one boot overlay at a time — supersede any prior one.
    if (active) skip();
    injectStyle();
    var root = build(opts);
    document.body.appendChild(root);

    return new Promise(function (resolve) {
      var ctx = { root: root, opts: opts, resolve: resolve, done: false, onKey: null };
      active = ctx;

      var enter = function () { if (active === ctx) active = null; finish(ctx, true); };

      root.querySelector(".enter").addEventListener("click", enter);

      ctx.onKey = function (e) {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault(); enter();
        } else if (e.key === "Escape") {
          e.preventDefault(); if (active === ctx) active = null; finish(ctx, false);
        }
      };
      document.addEventListener("keydown", ctx.onKey, true);

      // Fade the backdrop in on the next frame (lets the CSS transition run).
      requestAnimationFrame(function () { root.classList.add("on"); });

      // Reduced motion: no big timeline, focus Enter early. Otherwise focus once it's revealed.
      var focusDelay = REDUCED ? 200 : 2100;
      setTimeout(function () {
        if (!ctx.done) { try { root.querySelector(".enter").focus(); } catch (_) {} }
      }, focusDelay);

      // Optional unattended auto-advance.
      if (typeof opts.autoEnterMs === "number" && opts.autoEnterMs >= 0) {
        setTimeout(function () { if (!ctx.done) enter(); }, opts.autoEnterMs);
      }
    });
  }

  // Immediately tear down the active overlay (no onEnter, no fade dependency) and resolve it.
  function skip() {
    if (!active) return;
    var ctx = active;
    active = null;
    finish(ctx, false);
  }

  window.OSBoot = { play: play, skip: skip };
})();
