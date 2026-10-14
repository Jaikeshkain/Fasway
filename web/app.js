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
      screenOn: false, screenLarge: false, screenQuality: "medium" },
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
  }));

  // ---------------- screen preview (WebRTC) ----------------
  const QUALITY = { low: { w: 854, fps: 20 }, medium: { w: 1280, fps: 30 }, high: { w: 1920, fps: 30 } };
  const screenEl = $("#screen"), vid = $("#screenVid"), screenMsg = $("#screenMsg"), screenBtn = $("#screenBtn");
  let pc = null, rtcRetry = null;

  function showScreenMsg(text) { screenMsg.textContent = text || ""; screenMsg.classList.toggle("hidden", !text); }

  function wantScreen() {
    return settings.screenOn && document.visibilityState === "visible" &&
      $("#tab-pad").classList.contains("active") && ws && ws.readyState === 1;
  }
  function syncScreen() {
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
    settings.screenLarge = !settings.screenLarge; saveSettings(); syncScreen();
  });
  document.addEventListener("visibilitychange", syncScreen);

  // tap on the preview -> move the laptop cursor to that spot
  vid.addEventListener("click", (e) => {
    if (!vid.videoWidth) return;
    const r = vid.getBoundingClientRect();
    const scale = Math.min(r.width / vid.videoWidth, r.height / vid.videoHeight); // object-fit: contain
    const cw = vid.videoWidth * scale, ch = vid.videoHeight * scale;
    const fx = (e.clientX - r.left - (r.width - cw) / 2) / cw, fy = (e.clientY - r.top - (r.height - ch) / 2) / ch;
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return;
    send({ t: "point", x: fx, y: fy }); buzz();
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
