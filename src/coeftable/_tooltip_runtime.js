(() => {
  "use strict";
  if (window.coeftableTooltips) return;

  const mounts = new Map();
  const cache = new WeakMap();
  const ns = "http://www.w3.org/2000/svg";
  let panel, style, observer, active = null, dismissTimer;
  let nextPanelId = 0;
  const css = `
.ct-tooltip-panel{position:fixed;z-index:2147483647;box-sizing:border-box;
 max-width:min(360px,calc(100vw - 16px));max-height:calc(100vh - 16px);
 width:max-content;padding:10px 12px;border:1px solid;border-radius:6px;
 font:12px/1.45 system-ui,sans-serif;overflow:auto;overflow-wrap:anywhere;
 white-space:normal;box-shadow:0 3px 16px #0003;pointer-events:none}
.ct-tooltip-panel[hidden]{display:none}
.ct-tooltip-panel:focus-visible,.ct-tooltip-target:focus-visible{outline:2px solid currentColor;outline-offset:2px}
.ct-tooltip-x{font-weight:650;margin-bottom:5px}
.ct-tooltip-trace+.ct-tooltip-trace{margin-top:7px}
.ct-tooltip-sample+.ct-tooltip-sample{margin-top:5px}
.ct-tooltip-target{touch-action:pan-y}
`;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function visible(svg) {
    if (!svg.isConnected || !svg.getClientRects().length) return false;
    const computed = getComputedStyle(svg);
    return computed.display !== "none" && computed.visibility !== "hidden" &&
      svg.getBoundingClientRect().width > 0 && svg.getBoundingClientRect().height > 0;
  }

  function geometry(svg) {
    if (!visible(svg)) return null;
    const matrix = svg.getScreenCTM();
    if (!matrix || !Number.isFinite(matrix.a * matrix.d - matrix.b * matrix.c) ||
        Math.abs(matrix.a * matrix.d - matrix.b * matrix.c) < 1e-12) return null;
    return matrix;
  }

  function retire(svg) {
    cache.delete(svg);
    if (active?.svg === svg) hide();
    clearGuide(svg);
    svg.querySelector(".ct-tooltip-target")?.remove();
    return null;
  }

  function setup(svg) {
    const raw = svg.getAttribute("data-ct-tooltip");
    const previous = cache.get(svg);
    if (previous && previous.raw === raw) return previous;
    if (previous) retire(svg);
    let data;
    try { data = JSON.parse(raw); } catch { return retire(svg); }
    if (data?.version !== 1 || !["sparkline", "forest"].includes(data.kind)) return retire(svg);
    const r = data.rect;
    if (!r || ![r.left, r.right, r.top, r.bottom].every(Number.isFinite) ||
        r.right <= r.left || r.bottom <= r.top || !Array.isArray(data.traces)) return retire(svg);
    const positions = new Map();
    for (const trace of data.traces) {
      for (const point of trace.points) {
        if (Number.isFinite(point.x) && Number.isFinite(point.px)) positions.set(point.x, point.px);
      }
    }
    const xs = [...positions].sort((a, b) => a[0] - b[0]);
    if (data.kind === "sparkline" && !xs.length) return retire(svg);
    let target = svg.querySelector(".ct-tooltip-target");
    if (!target) target = document.createElementNS(ns, "rect");
    target.setAttribute("class", "ct-tooltip-target");
    for (const [key, value] of Object.entries({x:r.left, y:r.top, width:r.right-r.left, height:r.bottom-r.top})) {
      target.setAttribute(key, value);
    }
    target.setAttribute("fill", "transparent");
    target.setAttribute("pointer-events", "all");
    target.setAttribute("tabindex", "0");
    target.setAttribute("role", "img");
    target.setAttribute("aria-label", "Inspect plot values. Use Left, Right, Home, End; Escape dismisses.");
    target.removeAttribute("aria-describedby");
    const state = {raw, data, xs, index:0, target};
    cache.set(svg, state);
    svg.append(target);
    return state;
  }

  function scan(root) {
    if (root.matches?.("svg[data-ct-tooltip]")) setup(root);
    for (const svg of root.querySelectorAll("svg[data-ct-tooltip]")) setup(svg);
  }

  function clearGuide(svg) {
    for (const mark of svg.querySelectorAll(".ct-tooltip-guide,.ct-tooltip-highlight")) mark.remove();
  }

  function hide() {
    clearTimeout(dismissTimer);
    if (active) {
      clearGuide(active.svg);
      const {target} = active.state;
      target.removeAttribute("aria-describedby");
      if (active.capture !== null && target.hasPointerCapture(active.capture)) {
        target.releasePointerCapture(active.capture);
      }
    }
    active = null;
    if (panel) panel.hidden = true;
  }

  function deferHide() {
    clearTimeout(dismissTimer);
    dismissTimer = setTimeout(() => {
      if (!active || active.capture !== null || active.touchHeld) return;
      if (active.svg.matches(":hover") || active.svg.contains(document.activeElement) ||
          panel.matches(":hover") || panel.contains(document.activeElement)) return;
      hide();
    }, 120);
  }

  function nearest(xs, px) {
    let low = 0, high = xs.length;
    while (low < high) {
      const middle = (low + high) >>> 1;
      if (xs[middle][1] < px) low = middle + 1;
      else high = middle;
    }
    if (low === 0) return 0;
    if (low === xs.length) return low - 1;
    return px - xs[low-1][1] <= xs[low][1] - px ? low - 1 : low;
  }

  function svgMark(svg, tag, attrs, className) {
    const mark = document.createElementNS(ns, tag);
    mark.setAttribute("class", className);
    mark.setAttribute("pointer-events", "none");
    for (const [key, value] of Object.entries(attrs)) mark.setAttribute(key, value);
    svg.append(mark);
  }

  function render(svg, state, index) {
    const matrix = geometry(svg);
    if (!matrix) { hide(); return; }
    clearTimeout(dismissTimer);
    if (active && active.svg !== svg) hide();
    if (!active) active = {svg, state, capture:null, touchHeld:false};
    active.touchHeld = false;
    state.index = index;
    const {data, xs} = state, r = data.rect;
    const x = data.kind === "sparkline" ? xs[index][0] : null;
    const selected = data.traces.flatMap(trace => trace.points.filter(p => data.kind === "forest" || p.x === x));
    panel.replaceChildren();
    panel.style.backgroundColor = data.colors.surface;
    panel.style.color = data.colors.text;
    panel.style.borderColor = data.colors.axis;
    if (data.kind === "sparkline") panel.append(node("div", "ct-tooltip-x", selected[0].x_text));
    clearGuide(svg);
    if (data.kind === "sparkline") {
      svgMark(svg, "line", {x1:xs[index][1], x2:xs[index][1], y1:r.top, y2:r.bottom,
        stroke:data.colors.axis, "stroke-width":1, "stroke-dasharray":"2,2"}, "ct-tooltip-guide");
    }
    for (const trace of data.traces) {
      const section = node("div", "ct-tooltip-trace");
      if (trace.label) {
        const label = node("strong", "ct-tooltip-label", trace.label);
        label.style.color = trace.color;
        section.append(label);
      }
      const points = trace.points.filter(p => data.kind === "forest" || p.x === x);
      if (!points.length) section.append(node("div", "ct-tooltip-sample", "No observation"));
      for (const point of points) {
        const sample = node("div", "ct-tooltip-sample");
        const status = ["value", "missing"].includes(point.status) ? "" : ` (${point.status} scale)`;
        sample.append(node("div", "ct-tooltip-value", point.value_text + status));
        if (point.lower_text !== "Missing" || point.upper_text !== "Missing") {
          sample.append(node("div", "ct-tooltip-interval", `Interval: ${point.lower_text} … ${point.upper_text}`));
        }
        for (const [label, text] of point.extras) {
          sample.append(node("div", "ct-tooltip-extra", `${label}: ${text}`));
        }
        section.append(sample);
        if (data.kind === "sparkline" && Number.isFinite(point.py)) {
          svgMark(svg, "circle", {cx:point.px, cy:point.py, r:2.5, fill:trace.color}, "ct-tooltip-highlight");
        }
      }
      panel.append(section);
    }
    panel.hidden = false;
    state.target.setAttribute("aria-describedby", panel.id);
    panel.style.left = "8px";
    panel.style.top = "8px";
    const anchor = new DOMPoint(data.kind === "sparkline" ? xs[index][1] : (r.left+r.right)/2, r.bottom).matrixTransform(matrix);
    const box = panel.getBoundingClientRect();
    const left = Math.max(8, Math.min(innerWidth-box.width-8, anchor.x+10));
    const top = Math.max(8, Math.min(innerHeight-box.height-8, anchor.y+8));
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    const overflow = panel.scrollHeight > panel.clientHeight || panel.scrollWidth > panel.clientWidth;
    panel.style.pointerEvents = overflow ? "auto" : "none";
    panel.tabIndex = overflow ? 0 : -1;
    panel.scrollTop = 0;
  }

  function routed(root, event, cachedOnly = false) {
    const svg = event.target.closest?.("svg[data-ct-tooltip]");
    if (!svg) return null;
    let nearestRoot = svg;
    while (nearestRoot && !mounts.has(nearestRoot)) nearestRoot = nearestRoot.parentNode;
    if (nearestRoot !== root) return null;
    const state = cachedOnly ? cache.get(svg) : setup(svg);
    return state ? {svg, state} : null;
  }

  function pointEvent(root, event) {
    const exiting = ["pointerout", "pointerup", "pointercancel"].includes(event.type);
    const entry = routed(root, event, exiting);
    if (!entry) return;
    const {svg, state} = entry;
    if (event.type === "pointercancel") { if (active?.svg === svg) hide(); return; }
    if (event.type === "pointerout") { if (!svg.contains(event.relatedTarget)) deferHide(); return; }
    if (event.type === "pointerup") {
      if (active?.svg === svg) {
        if (state.target.hasPointerCapture(event.pointerId)) state.target.releasePointerCapture(event.pointerId);
        active.capture = null;
        active.touchHeld = event.pointerType !== "mouse";
      }
      return;
    }
    if (event.type === "pointermove" && event.pointerType !== "mouse" && active?.capture !== event.pointerId) return;
    const matrix = geometry(svg);
    if (!matrix) { hide(); return; }
    const local = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
    const r = state.data.rect;
    if (active?.capture == null && (local.x < r.left || local.x > r.right || local.y < r.top || local.y > r.bottom)) return;
    render(svg, state, state.data.kind === "forest" ? 0 : nearest(state.xs, local.x));
    if (event.type === "pointerdown" && active) {
      active.capture = event.pointerId;
      // Synthetic pointer events may have no browser-managed pointer to capture.
      try { state.target.setPointerCapture(event.pointerId); } catch { /* no active native pointer */ }
    }
  }

  function focusEvent(root, event) {
    const entry = routed(root, event, event.type === "focusout");
    if (!entry) return;
    if (event.type === "focusout") { deferHide(); return; }
    render(entry.svg, entry.state, entry.state.index);
  }

  function keyEvent(root, event) {
    const entry = routed(root, event);
    if (!entry) return;
    const {svg, state} = entry;
    if (event.key === "Escape") { event.preventDefault(); hide(); return; }
    if (["PageDown", "PageUp"].includes(event.key)) {
      if (active?.svg === svg && !panel.hidden) {
        event.preventDefault();
        panel.scrollTop += (event.key === "PageDown" ? 1 : -1) * panel.clientHeight * .85;
      }
      return;
    }
    let index = state.index;
    if (event.key === "Home") index = 0;
    else if (event.key === "End") index = state.xs.length-1;
    else if (event.key === "ArrowLeft") index--;
    else if (event.key === "ArrowRight") index++;
    else return;
    event.preventDefault();
    render(svg, state, state.data.kind === "forest" ? 0 : Math.max(0, Math.min(state.xs.length-1, index)));
  }

  function outside(event) {
    if (active && !active.svg.contains(event.target) && !panel.contains(event.target)) hide();
  }
  function scroll(event) { if (!panel?.contains(event.target)) hide(); }
  function escape(event) { if (event.key === "Escape") hide(); }

  function initialize() {
    panel = node("div", "ct-tooltip-panel");
    panel.hidden = true;
    do { panel.id = `ct-tooltip-${++nextPanelId}`; } while (document.getElementById(panel.id));
    panel.setAttribute("role", "tooltip");
    panel.setAttribute("aria-live", "polite");
    panel.setAttribute("aria-atomic", "true");
    panel.addEventListener("pointerenter", () => clearTimeout(dismissTimer));
    panel.addEventListener("pointerleave", deferHide);
    panel.addEventListener("focusout", deferHide);
    style = node("style", "ct-tooltip-styles", css);
    document.head.append(style);
    document.body.append(panel);
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("scroll", scroll, true);
    document.addEventListener("keydown", escape);
    window.addEventListener("resize", hide);
    observer = new MutationObserver(records => {
      const relevant = records.some(record => !record.target.closest?.(".ct-tooltip-panel,.ct-tooltip-guide,.ct-tooltip-highlight"));
      if (!relevant) return;
      for (const record of records) {
        if (record.attributeName === "data-ct-tooltip" && record.target instanceof SVGSVGElement) {
          setup(record.target);
        }
      }
      for (const root of mounts.keys()) scan(root);
      if (active && (!visible(active.svg) || !geometry(active.svg))) hide();
    });
    observer.observe(document.documentElement, {subtree:true, childList:true, attributes:true,
      attributeFilter:["style", "class", "hidden", "data-ct-tooltip"]});
  }

  function mount(root) {
    if (mounts.has(root)) return mounts.get(root);
    if (!mounts.size) initialize();
    const handlers = [];
    for (const type of ["pointermove", "pointerdown", "pointerup", "pointercancel", "pointerout"]) {
      const handler = event => pointEvent(root, event);
      root.addEventListener(type, handler);
      handlers.push([type, handler]);
    }
    for (const type of ["focusin", "focusout"]) {
      const handler = event => focusEvent(root, event);
      root.addEventListener(type, handler);
      handlers.push([type, handler]);
    }
    const keyHandler = event => keyEvent(root, event);
    root.addEventListener("keydown", keyHandler);
    handlers.push(["keydown", keyHandler]);
    let disposed = false;
    const dispose = () => {
      if (disposed) return;
      disposed = true;
      for (const [type, handler] of handlers) root.removeEventListener(type, handler);
      mounts.delete(root);
      if (active && root.contains(active.svg)) hide();
      const svgs = root.matches?.("svg[data-ct-tooltip]") ? [root] : root.querySelectorAll("svg[data-ct-tooltip]");
      for (const svg of svgs) {
        let ancestor = svg;
        while (ancestor && !mounts.has(ancestor)) ancestor = ancestor.parentNode;
        if (!ancestor) {
          clearGuide(svg);
          svg.querySelector(".ct-tooltip-target")?.remove();
          cache.delete(svg);
        }
      }
      if (!mounts.size) {
        hide();
        observer.disconnect();
        document.removeEventListener("pointerdown", outside, true);
        document.removeEventListener("scroll", scroll, true);
        document.removeEventListener("keydown", escape);
        window.removeEventListener("resize", hide);
        panel.remove();
        style.remove();
      }
    };
    mounts.set(root, dispose);
    scan(root);
    return dispose;
  }

  window.coeftableTooltips = {mount};
})();
