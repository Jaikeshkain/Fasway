(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  // ---------------- storage / settings ----------------
  const store = {
    get(k, d) { try { const v = localStorage.getItem("fasway." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("fasway." + k, JSON.stringify(v)); } catch {} },
  };
  const settings = Object.assign(
    { speed: 1.6, accel: 1.2, scrollSpeed: 2.0, natural: true, haptics: true, lang: "mix-roman", review: false,
      screenOn: false, screenLarge: false, screenQuality: "medium", screenControl: true, clipAuto: true },
    store.get("settings", {})
  );
  const saveSettings = () => store.set("settings", settings);

  // ---------------- pairing token ----------------
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get("t")) {
    store.set("token", hash.get("t"));
    history.replaceState(null, "", location.pathname);
  }
  // re-scanning a QR while the page is open only changes the hash -> reload to re-pair
  window.addEventListener("hashchange", () => location.reload());
  const token = store.get("token", "");
  if (!token) $("#noToken").classList.remove("hidden");

  // ---------------- websocket ----------------
  let ws = null, retry = 0;
  const statusEl = $("#status");
  function setStatus(cls, text) { statusEl.className = "status " + cls; statusEl.querySelector("b").textContent = text; }

  function connect() {
    if (!token) return;
    setStatus("wait", "Connecting…");
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${scheme}://${location.host}/ws?t=${encodeURIComponent(token)}`);
    ws.onopen = () => { retry = 0; setStatus("on", "Connected"); syncScreen(); };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.t === "rtc_answer") onRtcAnswer(m);
      else if (m.t === "hello") setLaptopOS(m.os);
      else if (m.t === "sys") onSys(m);
      else if (m.t === "clip") onClip(m);
      else if (m.t === "clip_ok") notify(!m.ok ? "Couldn't set the laptop clipboard" : m.paste ? "Pasted on laptop" : "Sent to laptop clipboard");
    };
    ws.onclose = (e) => {
      stopScreen(false);
      setStatus("off", e.code === 4001 ? "Re-scan QR" : "Offline");
      if (e.code === 4001) return;
      setTimeout(connect, Math.min(4000, 300 * 2 ** retry++));
    };
    ws.onerror = () => {};
  }
  function send(obj, droppable = false) {
    if (!ws || ws.readyState !== 1) return false;
    if (droppable && ws.bufferedAmount > 32768) return false; // avoid lag build-up
    ws.send(JSON.stringify(obj));
    return true;
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && (!ws || ws.readyState > 1)) { retry = 0; connect(); }
  });
  connect();

  const buzz = () => { if (settings.haptics && navigator.vibrate) navigator.vibrate(8); };

  // ---------------- tabs ----------------
  $$("nav button").forEach((b) => b.addEventListener("click", () => {
    $$("nav button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
    syncScreen();
    if (b.dataset.tab === "kbd") kbdInput.focus(); // inside the tap, so Android opens the keyboard
    if (b.dataset.tab === "ctl") refreshSys();
  }));

  // ---------------- screen preview (WebRTC) ----------------
  const QUALITY = { low: { w: 854, fps: 20 }, medium: { w: 1280, fps: 30 }, high: { w: 1920, fps: 30 } };
  const screenEl = $("#screen"), vid = $("#screenVid"), screenMsg = $("#screenMsg"), screenBtn = $("#screenBtn");
  let pc = null, rtcRetry = null;

  function showScreenMsg(text) { screenMsg.textContent = text || ""; screenMsg.classList.toggle("hidden", !text); }

  const activeTab = () => $(".tab.active");
  function wantScreen() {
    return settings.screenOn && document.visibilityState === "visible" &&
      !!activeTab().querySelector(".screen-slot") && ws && ws.readyState === 1;
  }
  function syncScreen() {
    // the preview is shared by the Touchpad and Keyboard tabs: move it into the visible one
    const slot = activeTab().querySelector(".screen-slot");
    if (slot && screenEl.parentElement !== slot) { slot.appendChild(screenEl); vid.play().catch(() => {}); }
    screenEl.classList.toggle("hidden", !settings.screenOn);
    screenEl.classList.toggle("large", settings.screenLarge);
    screenBtn.classList.toggle("on", settings.screenOn);
    if (wantScreen()) { if (!pc) startScreen(); } else if (pc) stopScreen(true);
  }

  async function startScreen() {
    clearTimeout(rtcRetry);
    showScreenMsg("Connecting to screen…");
    const conn = pc = new RTCPeerConnection({ iceServers: [] }); // same Wi-Fi: no STUN/TURN needed
    const tr = conn.addTransceiver("video", { direction: "recvonly" });
    try { // prefer VP8 (what the laptop encodes)
      const codecs = RTCRtpReceiver.getCapabilities("video").codecs;
      tr.setCodecPreferences([...codecs.filter((c) => /vp8/i.test(c.mimeType)), ...codecs.filter((c) => !/vp8/i.test(c.mimeType))]);
    } catch {}
    try { tr.receiver.jitterBufferTarget = 0; } catch {}   // lowest latency
    try { tr.receiver.playoutDelayHint = 0; } catch {}
    conn.ontrack = (e) => { vid.srcObject = e.streams[0] || new MediaStream([e.track]); vid.play().catch(() => {}); };
    conn.onconnectionstatechange = () => {
      if (conn !== pc) return;
      const s = conn.connectionState;
      if (s === "connected") showScreenMsg("");
      if (s === "failed" || s === "disconnected") {
        showScreenMsg("Screen connection lost – retrying…");
        stopScreen(false);
        rtcRetry = setTimeout(syncScreen, 1500);
      }
    };
    await conn.setLocalDescription(await conn.createOffer());
    // laptop side doesn't trickle ICE, so send the offer with all candidates (max ~1.5 s wait)
    await new Promise((res) => {
      if (conn.iceGatheringState === "complete") return res();
      const t = setTimeout(res, 1500);
      conn.addEventListener("icegatheringstatechange", () => { if (conn.iceGatheringState === "complete") { clearTimeout(t); res(); } });
    });
    if (conn !== pc) return; // stopped meanwhile
    const q = QUALITY[settings.screenQuality] || QUALITY.medium;
    send({ t: "rtc_offer", sdp: conn.localDescription.sdp, type: conn.localDescription.type, w: q.w, fps: q.fps });
  }

  async function onRtcAnswer(m) {
    if (!pc) return;
    if (m.warn) showScreenMsg(m.warn);
    try { await pc.setRemoteDescription({ type: m.type, sdp: m.sdp }); }
    catch (e) { showScreenMsg("Screen error: " + e.message); }
  }

  function stopScreen(notify) {
    clearTimeout(rtcRetry);
    if (notify) send({ t: "rtc_stop" });
    if (pc) { const c = pc; pc = null; c.close(); }
    vid.srcObject = null;
  }

  screenBtn.addEventListener("click", () => { settings.screenOn = !settings.screenOn; saveSettings(); syncScreen(); buzz(); });
  $("#screenSize").addEventListener("click", (e) => {
    e.stopPropagation();
    settings.screenLarge = !settings.screenLarge; saveSettings(); syncScreen(); resetView();
  });
  document.addEventListener("visibilitychange", syncScreen);

  // ---- direct touch on the preview ----
  // tap = click · long-press = right click · drag = drag · double-tap = double click
  // 2 fingers: pinch = zoom the preview, move = pan (when zoomed) or scroll the laptop (when not)
  // 2-finger tap = reset zoom.  In 👁 view-only mode touches only zoom/pan the preview.
  const screenToast = $("#screenToast"), modeBtn = $("#screenMode"), fsInput = $("#fsInput");
  const view = { s: 1, tx: 0, ty: 0 };
  const LONG_MS = 500;
  let sg = null, pendingPt = null, ptRaf = false, toastTimer = null;

  function toast(msg) {
    screenToast.textContent = msg; screenToast.classList.remove("hidden");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => screenToast.classList.add("hidden"), 1200);
  }
  function applyView() {
    const W = screenEl.clientWidth, H = screenEl.clientHeight;
    view.s = Math.min(Math.max(view.s, 1), 6);
    view.tx = Math.min(0, Math.max(W - W * view.s, view.tx));
    view.ty = Math.min(0, Math.max(H - H * view.s, view.ty));
    vid.style.transform = view.s === 1 ? "" : `translate(${view.tx}px, ${view.ty}px) scale(${view.s})`;
  }
  function resetView() { view.s = 1; view.tx = view.ty = 0; applyView(); }
  window.addEventListener("resize", applyView);

  // screen coordinates -> fraction of the laptop screen (accounts for zoom and letterboxing)
  function toFrac(cx, cy, clamp) {
    if (!vid.videoWidth) return null;
    const r = screenEl.getBoundingClientRect();
    const W = screenEl.clientWidth, H = screenEl.clientHeight;
    const lx = (cx - r.left - screenEl.clientLeft - view.tx) / view.s;
    const ly = (cy - r.top - screenEl.clientTop - view.ty) / view.s;
    const k = Math.min(W / vid.videoWidth, H / vid.videoHeight); // object-fit: contain
    const cw = vid.videoWidth * k, ch = vid.videoHeight * k;
    let fx = (lx - (W - cw) / 2) / cw, fy = (ly - (H - ch) / 2) / ch;
    if (clamp) { fx = Math.min(1, Math.max(0, fx)); fy = Math.min(1, Math.max(0, fy)); }
    else if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null;
    return [fx, fy];
  }
  const point = (f, a) => send(a ? { t: "point", x: f[0], y: f[1], a } : { t: "point", x: f[0], y: f[1] }, !a);
  function queueMove(f) { // drag moves: at most one per frame
    pendingPt = f;
    if (!ptRaf) { ptRaf = true; requestAnimationFrame(() => { ptRaf = false; if (pendingPt) { point(pendingPt); pendingPt = null; } }); }
  }
  function two(e) {
    const [a, b] = e.touches;
    return { cx: (a.clientX + b.clientX) / 2, cy: (a.clientY + b.clientY) / 2, d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) };
  }
  function endDrag() {
    pendingPt = null; // the release below goes to the final position anyway; never move after it
    const f = sg.lastF || toFrac(sg.x0, sg.y0, true);
    if (f) point(f, "up");
    sg.mode = "done";
  }

  screenEl.addEventListener("touchstart", (e) => {
    if (e.target.closest("button")) return; // let the toolbar buttons work
    e.preventDefault();
    const control = settings.screenControl;
    if (e.touches.length === 1 && !sg) {
      const x = e.touches[0].clientX, y = e.touches[0].clientY;
      sg = { mode: "pending1", x0: x, y0: y, t0: performance.now(), control };
      if (control) sg.timer = setTimeout(() => {
        if (!sg || sg.mode !== "pending1") return;
        const f = toFrac(x, y);
        if (f) { point(f, "rclick"); buzz(); toast("Right click"); }
        sg.mode = "done";
      }, LONG_MS);
    } else if (e.touches.length === 2) {
      if (sg) { clearTimeout(sg.timer); if (sg.mode === "drag") endDrag(); }
      const t = two(e);
      sg = { mode: "pending2", c0: t, last: t, s0: view.s, tx0: view.tx, ty0: view.ty, t0: performance.now(), control };
    }
  }, { passive: false });

  screenEl.addEventListener("touchmove", (e) => {
    if (!sg) return;
    e.preventDefault();
    if (e.touches.length === 1 && ["pending1", "drag", "pan1"].includes(sg.mode)) {
      const x = e.touches[0].clientX, y = e.touches[0].clientY;
      if (sg.mode === "pending1") {
        if (Math.hypot(x - sg.x0, y - sg.y0) < 10) return;
        clearTimeout(sg.timer);
        if (!sg.control) { sg.mode = "pan1"; sg.tx0 = view.tx; sg.ty0 = view.ty; }
        else {
          const f0 = toFrac(sg.x0, sg.y0);
          if (!f0) { sg.mode = "done"; return; }
          point(f0, "down"); sg.mode = "drag"; buzz();
        }
      }
      if (sg.mode === "drag") { const f = toFrac(x, y, true); if (f) { sg.lastF = f; queueMove(f); } }
      else if (sg.mode === "pan1") { view.tx = sg.tx0 + x - sg.x0; view.ty = sg.ty0 + y - sg.y0; applyView(); }
      return;
    }
    if (e.touches.length === 2 && sg.c0) {
      const t = two(e);
      if (sg.mode === "pending2") {
        const dd = Math.abs(t.d - sg.c0.d), dc = Math.hypot(t.cx - sg.c0.cx, t.cy - sg.c0.cy);
        if (dd > 14) sg.mode = "zoom";
        else if (dc > 10) {
          sg.mode = view.s > 1.02 || !sg.control ? "zoom" : "scroll";
          if (sg.mode === "scroll") { const f = toFrac(sg.c0.cx, sg.c0.cy, true); if (f) point(f); } // scroll the window under the fingers
        } else return;
      }
      if (sg.mode === "zoom") {
        // keep the spot that was under the fingers under the fingers while zooming/panning
        const r = screenEl.getBoundingClientRect();
        const s = Math.min(6, Math.max(1, sg.s0 * t.d / sg.c0.d));
        const px = (sg.c0.cx - r.left - sg.tx0) / sg.s0, py = (sg.c0.cy - r.top - sg.ty0) / sg.s0;
        view.s = s; view.tx = t.cx - r.left - px * s; view.ty = t.cy - r.top - py * s;
        applyView();
      } else if (sg.mode === "scroll") {
        const k = settings.scrollSpeed * 2.5, dir = settings.natural ? 1 : -1;
        scrY += (t.cy - sg.last.cy) * k * dir;
        scrX += -(t.cx - sg.last.cx) * k * dir;
        scheduleFlush();
      }
      sg.last = t;
    }
  }, { passive: false });

  function screenTouchEnd(e) {
    if (!sg) return;
    e.preventDefault();
    if (e.touches.length) return; // wait until every finger is up
    clearTimeout(sg.timer);
    const dt = performance.now() - sg.t0;
    if (sg.mode === "pending1" && sg.control && dt < LONG_MS && e.type === "touchend") {
      const f = toFrac(sg.x0, sg.y0);
      if (f) { point(f, "click"); buzz(); }
    } else if (sg.mode === "drag") endDrag();
    else if (sg.mode === "pending2" && dt < 300) { resetView(); toast("Zoom reset"); }
    sg = null;
  }
  screenEl.addEventListener("touchend", screenTouchEnd, { passive: false });
  screenEl.addEventListener("touchcancel", screenTouchEnd, { passive: false });

  // toolbar: touch mode, keyboard (full screen), full screen
  function renderMode() { modeBtn.textContent = settings.screenControl ? "👆" : "👁"; }
  renderMode();
  modeBtn.addEventListener("click", () => {
    settings.screenControl = !settings.screenControl; saveSettings(); renderMode(); buzz();
    toast(settings.screenControl ? "Touch controls the laptop" : "View only – pinch to zoom");
  });
  $$(".screen-tools button").forEach((b) => b.addEventListener("mousedown", (e) => e.preventDefault()));
  $("#screenFull").addEventListener("click", async () => {
    if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
    try {
      await screenEl.requestFullscreen({ navigationUI: "hide" });
      await screen.orientation.lock("landscape").catch(() => {});
    } catch { toast("Full screen not available"); }
  });
  document.addEventListener("fullscreenchange", () => {
    resetView();
    if (!document.fullscreenElement) { try { screen.orientation.unlock(); } catch {} fsInput.blur(); }
  });
  $("#screenKbd").addEventListener("click", () => {
    if (document.activeElement === fsInput) fsInput.blur(); else fsInput.focus();
  });

  // ---------------- touchpad ----------------
  const pad = $("#pad");
  const fingers = new Map();      // identifier -> {x, y}
  let g = null;                   // current gesture
  let accX = 0, accY = 0, scrX = 0, scrY = 0, rafPending = false;
  let lastTap = { t: 0, x: 0, y: 0 };
  let dragPending = false, dragging = false;
  const TAP_MS = 220, TAP_MOVE = 10, DOUBLE_MS = 300;

  function scheduleFlush() {
    if (!rafPending) { rafPending = true; requestAnimationFrame(flush); }
  }
  function flush() {
    rafPending = false;
    const mx = Math.trunc(accX), my = Math.trunc(accY);
    if (mx || my) { if (send({ t: "m", x: mx, y: my }, true)) { accX -= mx; accY -= my; } else { accX = accY = 0; } }
    const sx = Math.trunc(scrX), sy = Math.trunc(scrY);
    if (sx || sy) { send({ t: "s", x: sx, y: sy }, true); scrX -= sx; scrY -= sy; }
  }

  pad.addEventListener("touchstart", (e) => {
    e.preventDefault();
    const now = performance.now();
    for (const t of e.changedTouches) fingers.set(t.identifier, { x: t.clientX, y: t.clientY, t: now });
    if (!g) {
      const t = e.changedTouches[0];
      g = { t0: now, max: 0, moved: 0 };
      // second touch shortly after a tap, near the same spot -> potential drag
      dragPending = now - lastTap.t < DOUBLE_MS && Math.hypot(t.clientX - lastTap.x, t.clientY - lastTap.y) < 60;
    }
    g.max = Math.max(g.max, fingers.size);
    if (fingers.size > 1) dragPending = false;
  }, { passive: false });

  pad.addEventListener("touchmove", (e) => {
    e.preventDefault();
    if (!g) return;
    const now = performance.now();
    let sumDx = 0, sumDy = 0, n = 0, maxDt = 1;
    for (const t of e.changedTouches) {
      const f = fingers.get(t.identifier);
      if (!f) continue;
      sumDx += t.clientX - f.x; sumDy += t.clientY - f.y; n++;
      maxDt = Math.max(maxDt, now - f.t);
      f.x = t.clientX; f.y = t.clientY; f.t = now;
    }
    if (!n) return;
    const dx = sumDx / n, dy = sumDy / n, dist = Math.hypot(dx, dy);
    g.moved += dist;

    if (fingers.size >= 2) {
      // two-finger scroll (Windows wheel units: 120 per notch)
      const k = settings.scrollSpeed * 2.5, dir = settings.natural ? 1 : -1;
      scrY += dy * k * dir;
      scrX += -dx * k * dir;
      scheduleFlush();
      return;
    }
    if (g.max > 1 && !dragging) return; // ignore the leftover finger after a scroll / right-click

    if (dragPending && g.moved > 6) { dragPending = false; dragging = true; pad.classList.add("dragging"); send({ t: "b", b: "left", a: "down" }); buzz(); }

    const v = dist / maxDt; // px per ms
    const gain = settings.speed * (1 + settings.accel * Math.min(Math.max(v - 0.15, 0), 3));
    accX += dx * gain * devicePixelRatio * 0.6;
    accY += dy * gain * devicePixelRatio * 0.6;
    scheduleFlush();
  }, { passive: false });

  function endTouch(e, cancelled) {
    e.preventDefault();
    for (const t of e.changedTouches) fingers.delete(t.identifier);
    if (fingers.size || !g) return;
    const now = performance.now();
    if (dragging) {
      send({ t: "b", b: "left", a: "up" });
      dragging = false; pad.classList.remove("dragging");
    } else if (!cancelled && now - g.t0 < TAP_MS + (g.max > 1 ? 80 : 0) && g.moved < TAP_MOVE) {
      const b = g.max === 1 ? "left" : g.max === 2 ? "right" : "middle";
      send({ t: "b", b, a: "click" }); buzz();
      if (b === "left") { const t = e.changedTouches[0]; lastTap = { t: now, x: t.clientX, y: t.clientY }; }
    }
    dragPending = false; g = null;
  }
  pad.addEventListener("touchend", (e) => endTouch(e, false), { passive: false });
  pad.addEventListener("touchcancel", (e) => endTouch(e, true), { passive: false });

  // physical-style buttons (hold Left + move on pad = drag)
  $$(".mouse-buttons button").forEach((btn) => {
    const b = btn.dataset.btn;
    let held = false;
    const up = () => { if (held) { held = false; btn.classList.remove("held"); send({ t: "b", b, a: "up" }); } };
    btn.addEventListener("pointerdown", (e) => { e.preventDefault(); held = true; btn.classList.add("held"); send({ t: "b", b, a: "down" }); buzz(); });
    btn.addEventListener("pointerup", up);
    btn.addEventListener("pointercancel", up);
    btn.addEventListener("pointerleave", up);
    btn.addEventListener("contextmenu", (e) => e.preventDefault());
  });

  // ---------------- keyboard (live typing) ----------------
  // The phone keyboard types into a real input; every change is diffed against the previous value
  // and replayed on the laptop as backspaces + new text. This works with Gboard autocorrect, swipe
  // typing, Hindi keyboards and keyboard voice input, which don't send usable key events.
  const kbdInput = $("#kbdInput"), kbdHint = $("#kbdHint");
  const SENTINEL = "​";  // invisible char, so Backspace on an "empty" field still produces an edit
  let laptopOS = "win";
  const cps = (s) => [...s].length; // code points = backspaces needed on the laptop

  const mods = { ctrl: 0, alt: 0, shift: 0, win: 0 }; // 0 off, 1 next key only, 2 locked
  const modBtns = {};
  $$("[data-mod]").forEach((b) => {
    modBtns[b.dataset.mod] = b;
    b.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus (and the keyboard) in the input
    b.addEventListener("click", () => { mods[b.dataset.mod] = (mods[b.dataset.mod] + 1) % 3; renderMods(); buzz(); });
  });
  function renderMods() {
    for (const [k, b] of Object.entries(modBtns)) {
      b.classList.toggle("mod-once", mods[k] === 1);
      b.classList.toggle("mod-lock", mods[k] === 2);
    }
  }
  const modPrefix = () => ["ctrl", "alt", "shift", "win"].filter((k) => mods[k]).map((k) => k + "+").join("");
  function releaseOnceMods() {
    for (const k in mods) if (mods[k] === 1) mods[k] = 0;
    renderMods();
  }
  function sendKey(k) { // special keys + whatever modifiers are active
    send({ t: "key", k: modPrefix() + k });
    releaseOnceMods();
  }

  // Mirrors an <input> to the laptop. Used by the Keyboard tab and the full-screen preview.
  function bindLiveTyping(el, hint) {
    let prev = SENTINEL, composing = false;
    el.value = SENTINEL;
    const reset = () => {
      el.value = prev = SENTINEL;
      if (hint) hint.classList.toggle("hidden", document.activeElement === el);
    };
    el.addEventListener("compositionstart", () => { composing = true; });
    el.addEventListener("compositionend", () => { composing = false; });
    el.addEventListener("input", () => {
      let v = el.value;
      let i = 0;
      while (i < prev.length && i < v.length && prev[i] === v[i]) i++;
      if (i > 0 && /[\ud800-\udbff]/.test(prev[i - 1])) i--; // don't split an emoji's surrogate pair
      const removed = prev.slice(i), added = v.slice(i);

      const comboMods = mods.ctrl || mods.alt || mods.win;
      if (comboMods && added && !removed) {
        // Ctrl/Alt/Win active: letters become shortcuts (Ctrl+C...) instead of text
        for (const ch of added) sendKey(ch === " " ? "space" : ch.toLowerCase());
        el.value = prev;
        return;
      }
      if (removed || added) {
        send({ t: "edit", del: cps(removed), ins: added });
        if (added && mods.shift === 1) releaseOnceMods();
      }
      if (!v.startsWith(SENTINEL)) v = SENTINEL + v;           // sentinel was deleted: put it back
      if (v.length > 400 && !composing) v = SENTINEL + v.slice(-40); // keep the field short
      if (v !== el.value) el.value = v;
      prev = v;
      if (hint) hint.classList.add("hidden");
    });
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); sendKey("enter"); reset(); }
      else if (e.key === "Tab") { e.preventDefault(); sendKey("tab"); }
    });
    // the laptop's caret is always at the end of what we've typed, so keep the phone's there too
    const caretToEnd = () => { const n = el.value.length; if (el.selectionStart !== n) el.setSelectionRange(n, n); };
    ["focus", "click", "select"].forEach((ev) => el.addEventListener(ev, () => setTimeout(caretToEnd, 0)));
    if (hint) {
      el.addEventListener("focus", () => hint.classList.add("hidden"));
      el.addEventListener("blur", () => hint.classList.toggle("hidden", el.value.length > 1));
    }
    return { reset };
  }
  const resetInput = bindLiveTyping(kbdInput, kbdHint).reset;
  bindLiveTyping(fsInput, null); // typing while the preview is full screen

  // special keys: act on press, auto-repeat while held (arrows, backspace...)
  $$("[data-k]").forEach((b) => {
    let timer = null;
    const stop = () => { clearTimeout(timer); clearInterval(timer); timer = null; };
    const fire = () => {
      let k = b.dataset.k;
      if (b.dataset.k === "backspace" || b.dataset.k === "delete") resetInput(); // field no longer mirrors the laptop
      sendKey(k);
    };
    b.addEventListener("mousedown", (e) => e.preventDefault()); // don't steal focus from the input
    b.addEventListener("pointerdown", (e) => {
      e.preventDefault(); buzz(); fire();
      if (b.hasAttribute("data-repeat")) timer = setTimeout(() => { timer = setInterval(fire, 70); }, 400);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((ev) => b.addEventListener(ev, stop));
    b.addEventListener("contextmenu", (e) => e.preventDefault());
  });

  function setLaptopOS(os) {
    laptopOS = os;
    $("#winKey").textContent = os === "mac" ? "⌘ Cmd" : "⊞ Win";
    $("#altKey").textContent = os === "mac" ? "⌥ Opt" : "Alt";
  }

  // hide the bottom tabs while the phone keyboard is up, to leave room for the screen preview
  let fullH = window.innerHeight;
  const vv = window.visualViewport;
  const onViewport = () => {
    fullH = Math.max(fullH, window.innerHeight);
    const h = vv ? vv.height : window.innerHeight;
    document.body.classList.toggle("kbd-open", document.activeElement === kbdInput && h < fullH * 0.8);
  };
  (vv || window).addEventListener("resize", onViewport);
  kbdInput.addEventListener("focus", () => setTimeout(onViewport, 300));
  kbdInput.addEventListener("blur", () => setTimeout(onViewport, 100));

  // ---------------- controls: media, volume, brightness, power ----------------
  const notifyEl = $("#toast");
  let notifyTimer = null;
  function notify(msg) {
    notifyEl.textContent = msg; notifyEl.classList.remove("hidden");
    clearTimeout(notifyTimer); notifyTimer = setTimeout(() => notifyEl.classList.add("hidden"), 1800);
  }
  const throttle = (fn, ms) => { // run at most every `ms`, always delivering the latest value
    let last = 0, timer = null;
    return (...a) => {
      const now = Date.now(); clearTimeout(timer);
      if (now - last >= ms) { last = now; fn(...a); }
      else timer = setTimeout(() => { last = Date.now(); fn(...a); }, ms - (now - last));
    };
  };

  $$("[data-media]").forEach((b) => b.addEventListener("click", () => { send({ t: "media", k: b.dataset.media }); buzz(); }));

  const volSlider = $("#volSlider"), volOut = $("#volOut"), muteBtn = $("#muteBtn");
  const brightSlider = $("#brightSlider"), brightOut = $("#brightOut");
  let volDragging = false, brightDragging = false;
  function onSys(m) {
    volSlider.disabled = m.vol == null;
    if (m.vol != null && !volDragging) { volSlider.value = m.vol; volOut.textContent = m.vol; }
    muteBtn.textContent = m.muted ? "🔇" : "🔊";
    const hasB = m.bright != null; // macOS and some external monitors: only -/+ buttons
    brightSlider.classList.toggle("hidden", !hasB);
    brightOut.classList.toggle("hidden", !hasB);
    if (hasB && !brightDragging) { brightSlider.value = m.bright; brightOut.textContent = m.bright; }
  }
  function refreshSys() { send({ t: "sys_get" }); }
  // keep sliders in sync with changes made on the laptop while the tab is open
  setInterval(() => {
    if ($("#tab-ctl").classList.contains("active") && document.visibilityState === "visible") refreshSys();
  }, 3000);

  const sendVol = throttle((v) => send({ t: "vol", v }), 120);
  volSlider.addEventListener("input", () => { volDragging = true; volOut.textContent = volSlider.value; sendVol(+volSlider.value); });
  volSlider.addEventListener("change", () => { volDragging = false; });
  muteBtn.addEventListener("click", () => { send({ t: "vol", mute: "toggle" }); buzz(); });

  const sendBright = throttle((v) => send({ t: "bright", v }), 300);
  brightSlider.addEventListener("input", () => { brightDragging = true; brightOut.textContent = brightSlider.value; sendBright(+brightSlider.value); });
  brightSlider.addEventListener("change", () => { brightDragging = false; });
  $("#brightUp").addEventListener("click", () => { send({ t: "bright", up: true }); buzz(); });
  $("#brightDown").addEventListener("click", () => { send({ t: "bright", up: false }); buzz(); });

  $$("[data-power]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.confirm && !confirm(b.dataset.confirm)) return;
    if (send({ t: "power", a: b.dataset.power })) { buzz(); notify(b.textContent.trim() + " sent"); }
  }));

  // ---------------- clipboard ----------------
  const clipList = $("#clipList"), clipAuto = $("#clipAuto");
  const clips = []; // newest first: {v, src: "laptop" | "phone"}
  clipAuto.checked = settings.clipAuto;
  clipAuto.addEventListener("change", () => { settings.clipAuto = clipAuto.checked; saveSettings(); });

  function addClip(v, src) {
    if (!v) return;
    const i = clips.findIndex((c) => c.v === v);
    if (i >= 0) clips.splice(i, 1);
    clips.unshift({ v, src });
    clips.length = Math.min(clips.length, 10);
    renderClips();
  }
  function renderClips() {
    clipList.innerHTML = "";
    for (const c of clips) {
      const row = document.createElement("div"); row.className = "clip-item";
      const body = document.createElement("div"); body.style.flex = "1"; body.style.minWidth = "0";
      const txt = document.createElement("div"); txt.className = "txt"; txt.textContent = c.v;
      const src = document.createElement("div"); src.className = "src"; src.textContent = c.src === "laptop" ? "from laptop" : "sent from phone";
      body.append(txt, src);
      const btn = document.createElement("button"); btn.textContent = "Copy";
      btn.addEventListener("click", () => copyToPhone(c.v));
      const paste = document.createElement("button"); paste.textContent = "Paste"; paste.title = "Paste on laptop";
      paste.addEventListener("click", () => send({ t: "clip_set", v: c.v, paste: true }));
      row.append(body, btn, paste);
      clipList.appendChild(row);
    }
  }
  async function copyToPhone(v, silent) {
    try { await navigator.clipboard.writeText(v); if (!silent) notify("Copied to phone"); return true; }
    catch { if (!silent) notify("Couldn't copy – long-press the text to copy it"); return false; }
  }
  function onClip(m) {
    addClip(m.v, "laptop");
    if (m.manual) return;
    if (settings.clipAuto) copyToPhone(m.v, true).then((ok) => ok && notify("📋 Laptop clipboard copied to phone"));
    else notify("📋 New laptop clipboard");
  }
  async function readPhoneClipboard() {
    try {
      const v = await navigator.clipboard.readText();
      if (!v) { notify("Phone clipboard is empty"); return null; }
      return v;
    } catch { notify("Allow clipboard access for this site to send it"); return null; }
  }
  $("#clipSend").addEventListener("click", async () => {
    const v = await readPhoneClipboard();
    if (v && send({ t: "clip_set", v })) addClip(v, "phone");
  });
  $("#clipPaste").addEventListener("click", async () => {
    const v = await readPhoneClipboard();
    if (v && send({ t: "clip_set", v, paste: true })) addClip(v, "phone");
  });
  $("#clipGet").addEventListener("click", () => send({ t: "clip_get" }));

  // ---------------- voice ----------------
  const LANGS = { "mix-roman": "en-IN", "mix-deva": "hi-IN", en: "en-IN", hi: "hi-IN" };
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#mic"), micState = $("#micState"), preview = $("#preview");
  const langSel = $("#lang"), reviewChk = $("#review"), textArea = $("#text");
  langSel.value = settings.lang;
  reviewChk.checked = settings.review;
  langSel.addEventListener("change", () => {
    settings.lang = langSel.value; saveSettings();
    if (listening) { rec && rec.abort(); } // onend restarts with the new language
  });
  reviewChk.addEventListener("change", () => { settings.review = reviewChk.checked; saveSettings(); });

  let rec = null, listening = false, wakeLock = null;
  const sentLines = [];
  let interimSpan = null;

  function renderPreview(interim) {
    preview.innerHTML = "";
    if (!sentLines.length && !interim) {
      preview.innerHTML = `<span class="placeholder">${listening ? "Listening… speak now" : "Tap the mic and speak…"}</span>`;
      return;
    }
    for (const l of sentLines.slice(-30)) {
      const s = document.createElement("span"); s.className = "sent"; s.textContent = l + " "; preview.appendChild(s);
    }
    if (interim) { interimSpan = document.createElement("span"); interimSpan.className = "interim"; interimSpan.textContent = interim; preview.appendChild(interimSpan); }
    preview.scrollTop = preview.scrollHeight;
  }

  function commit(text) {
    text = text.trim();
    if (!text) return;
    if (settings.review) {
      textArea.value = (textArea.value ? textArea.value.replace(/\s*$/, " ") : "") + text;
    } else {
      send({ t: "txt", v: text + " " });
    }
    sentLines.push(text);
    renderPreview("");
  }

  function startRec() {
    rec = new SR();
    rec.lang = LANGS[settings.lang] || "en-IN";
    rec.interimResults = true;
    rec.continuous = false;   // Android Chrome is most reliable in single-utterance mode; we auto-restart
    rec.maxAlternatives = 1;
    let committed = false;    // Android can fire the final result twice
    rec.onresult = (e) => {
      let interim = "", final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
      }
      if (final && !committed) { committed = true; commit(final); }
      else if (!committed) renderPreview(interim);
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        stopListening("Mic blocked – allow microphone for this site");
      } else if (e.error === "network") {
        micState.textContent = "Network error – speech recognition needs internet";
      }
    };
    rec.onend = () => {
      if (listening) setTimeout(() => { if (listening) startRec(); }, 120);
    };
    try { rec.start(); } catch {}
  }

  async function startListening() {
    if (!SR) { micState.textContent = "Not supported here – use your keyboard's mic in the box below"; return; }
    listening = true;
    micBtn.classList.add("listening"); micState.textContent = "Listening… tap to stop";
    renderPreview("");
    startRec();
    try { wakeLock = await navigator.wakeLock?.request("screen"); } catch {}
  }
  function stopListening(msg) {
    listening = false;
    micBtn.classList.remove("listening"); micState.textContent = msg || "Off";
    try { rec && rec.stop(); } catch {}
    renderPreview("");
    try { wakeLock && wakeLock.release(); } catch {}
    wakeLock = null;
  }
  micBtn.addEventListener("click", () => { buzz(); listening ? stopListening() : startListening(); });

  $("#send").addEventListener("click", () => {
    const v = textArea.value;
    if (v.trim() && send({ t: "txt", v })) { textArea.value = ""; buzz(); }
  });
  $$(".keys button").forEach((b) => b.addEventListener("click", () => { send({ t: "key", k: b.dataset.key }); buzz(); }));

  // ---------------- settings sheet ----------------
  const sheet = $("#sheet");
  const bindRange = (id, key, out) => {
    const el = $("#" + id), o = $("#" + out);
    el.value = settings[key]; o.textContent = settings[key];
    el.addEventListener("input", () => { settings[key] = +el.value; o.textContent = el.value; saveSettings(); });
  };
  bindRange("speed", "speed", "speedOut");
  bindRange("accel", "accel", "accelOut");
  bindRange("scrollSpeed", "scrollSpeed", "scrollOut");
  for (const k of ["natural", "haptics"]) {
    const el = $("#" + k);
    el.checked = settings[k];
    el.addEventListener("change", () => { settings[k] = el.checked; saveSettings(); });
  }
  const qualitySel = $("#screenQuality");
  qualitySel.value = settings.screenQuality;
  qualitySel.addEventListener("change", () => {
    settings.screenQuality = qualitySel.value; saveSettings();
    const q = QUALITY[settings.screenQuality];
    if (pc) send({ t: "rtc_cfg", w: q.w, fps: q.fps }); // applied live, no reconnect
  });
  $("#settingsBtn").addEventListener("click", () => sheet.classList.remove("hidden"));
  $("#closeSheet").addEventListener("click", () => sheet.classList.add("hidden"));
  sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.classList.add("hidden"); });

  // keep the screen awake while using the touchpad
  async function keepAwake() { try { if (document.visibilityState === "visible") await navigator.wakeLock?.request("screen"); } catch {} }
  document.addEventListener("visibilitychange", keepAwake);
  keepAwake();
})();
