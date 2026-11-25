// Bocina CoDi — utilidades compartidas entre el Mostrador (/) y la Caja (/caja).
(() => {
  // ---------- preferencias (mismo origen = compartidas entre pestañas) ----------
  const PREF_KEY = "bocina.prefs";
  const DEFAULTS = { voiceMode: "elevenlabs", expiration: null, cajaSound: false, volume: 0.8 };
  function prefs() {
    try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(PREF_KEY) || "{}") }; } catch { return { ...DEFAULTS }; }
  }
  function setPref(k, v) {
    try { const p = prefs(); p[k] = v; localStorage.setItem(PREF_KEY, JSON.stringify(p)); } catch {}
  }

  // ---------- utilidades ----------
  const $ = (id) => document.getElementById(id);
  const money = (n) => "$" + Number(n).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const PIN_KEY = "bocina.pin";
  const getPin = () => { try { return sessionStorage.getItem(PIN_KEY) || ""; } catch { return ""; } };
  const setPin = (v) => { try { v ? sessionStorage.setItem(PIN_KEY, v) : sessionStorage.removeItem(PIN_KEY); } catch {} };

  async function api(url, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    const pin = getPin(); if (pin) headers["X-Admin-Pin"] = pin;
    const r = await fetch(url, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      // El servidor manda {code, message} en errores de pey para que la página ofrezca la salida correcta
      const det = d.detail;
      const msg = typeof det === "string" ? det : det?.message || (Array.isArray(det) ? "Revisa los datos" : JSON.stringify(det || d));
      const err = new Error(msg); err.status = r.status; err.code = det?.code || null;
      throw err;
    }
    return d;
  }

  function toast(msg, ms = 3500) {
    let t = $("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
    t.textContent = msg; t.classList.add("show");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
  }

  let status = {};
  async function loadStatus() {
    try { status = await api("/api/status"); } catch { status = {}; }
    return status;
  }

  // ---------- sonido ----------
  // Chrome no deja sonar audio hasta que la persona toca la página una vez.
  // No ponemos pantalla de bloqueo: desbloqueamos con el primer toque/tecla y avisamos si hace falta.
  let audioCtx = null;
  let unlocked = !!(navigator.userActivation && navigator.userActivation.hasBeenActive);
  const soundListeners = new Set();
  const notifySound = () => soundListeners.forEach((fn) => fn(unlocked));
  function unlockAudio() {
    try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch {}
    try { speechSynthesis.speak(new SpeechSynthesisUtterance(" ")); } catch {}
    if (!unlocked) { unlocked = true; notifySound(); }
  }
  function markBlocked() { if (unlocked) { unlocked = false; notifySound(); } }
  ["pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, unlockAudio, { passive: true }));
  const volume = () => Math.max(0, Math.min(1, Number(prefs().volume ?? 0.8)));
  function setVolume(v) { setPref("volume", Math.round(Math.max(0, Math.min(1, v)) * 10) / 10); return volume(); }

  function chime() {
    try {
      audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
      const ctx = audioCtx;
      [880, 1320].forEach((f, i) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
        const t = ctx.currentTime + i * 0.12;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(Math.max(0.0002, 0.3 * volume()), t + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
        o.start(t); o.stop(t + 0.3);
      });
    } catch {}
  }

  function browserSay(text) {
    return new Promise((res) => {
      try {
        const u = new SpeechSynthesisUtterance(text); u.lang = "es-MX"; u.volume = volume();
        u.onend = res;
        u.onerror = (e) => { if (e.error === "not-allowed") markBlocked(); res(); };
        speechSynthesis.speak(u); // sin cancel(): la cola garantiza que no haya nada sonando
      } catch { res(); }
    });
  }

  async function elevenSay(text) {
    const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    const url = URL.createObjectURL(await r.blob());
    try {
      const a = new Audio(url); a.volume = volume();
      await new Promise((res, rej) => {
        a.onended = res; a.onerror = () => rej(new Error("audio"));
        a.play().catch((err) => { if (err.name === "NotAllowedError") markBlocked(); rej(err); });
      });
    } finally { URL.revokeObjectURL(url); }
  }

  // Dice UN texto completo y resuelve cuando terminó de sonar.
  async function sayNow(text) {
    const mode = prefs().voiceMode;
    if (mode === "off" || volume() === 0) { await sleep(2200); return; } // sin voz, igual damos tiempo a ver la pantalla
    const guard = sleep(Math.max(6000, text.length * 150)); // por si el audio se atora, la cola no se congela
    const speak = (async () => {
      if (mode === "elevenlabs" && status.elevenlabs) {
        try { await elevenSay(text); return; } catch (e) { console.warn("ElevenLabs falló, uso voz del navegador:", e.message); }
      }
      await browserSay(text);
    })();
    await Promise.race([speak, guard]);
  }

  // ---------- COLA DE VOZ: uno por uno, completos, en orden de llegada ----------
  const Voice = (() => {
    const queue = [];
    let busy = false;
    let idleCb = null;
    const listeners = new Set();
    const notify = () => listeners.forEach((fn) => fn(queue.length, busy));

    function enqueue(item) { queue.push(item); notify(); if (!busy) run(); }

    async function run() {
      busy = true;
      while (queue.length) {
        const it = queue.shift();
        notify();
        try {
          it.onStart?.(queue.length);
          if (it.chime) { chime(); await sleep(300); }
          await sayNow(it.text);
          await sleep(it.gap ?? 500); // pausa entre anuncios para que se distingan
          it.onEnd?.();
        } catch (e) { console.warn("Error en la cola de voz", e); }
      }
      busy = false; notify();
      idleCb?.();
    }

    return {
      enqueue,
      onIdle(fn) { idleCb = fn; },
      onChange(fn) { listeners.add(fn); },
      get pending() { return queue.length; },
      get busy() { return busy; },
    };
  })();

  // ---------- eventos en vivo ----------
  function connect(handlers) {
    const live = $("live");
    let es = null, watchdog = null, lastBeat = 0, isOn = false;
    const setLive = (on, txt) => {
      if (on !== isOn) { isOn = on; handlers.connection?.(on); }   // la página decide cómo mostrarlo
      if (!live) return; live.classList.toggle("on", on); live.querySelector("span").textContent = txt;
    };
    const beat = () => { lastBeat = Date.now(); };
    function open() {
      if (es) es.close();
      es = new EventSource("/api/events");
      es.addEventListener("hello", () => { beat(); setLive(true, "En vivo"); handlers.hello?.(); });
      es.addEventListener("ping", () => { beat(); if (!isOn) setLive(true, "En vivo"); });
      for (const type of ["payment", "history", "fixed", "pending"]) {   // history = pago recuperado o tardío, sin voz
        es.addEventListener(type, (ev) => { beat(); handlers[type]?.(JSON.parse(ev.data)); });
      }
      es.onerror = () => setLive(false, "Reconectando…");
    }
    open();
    // el servidor manda un latido cada 15 s; si pasan 35 s sin nada, la conexión murió sin avisar
    watchdog = setInterval(() => {
      if (lastBeat && Date.now() - lastBeat > 35000) { setLive(false, "Reconectando…"); lastBeat = Date.now(); open(); }
    }, 5000);
    return { close() { clearInterval(watchdog); es?.close(); } };
  }

  // ---------- dictado ----------
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  function dictate({ onStart, onPartial, onFinal, onError, onEnd }) {
    if (!SR) { toast("Tu navegador no soporta dictado. Usa Chrome."); return null; }
    const rec = new SR(); rec.lang = "es-MX"; rec.interimResults = true;
    let finalText = "";
    rec.onresult = (e) => {
      const t = [...e.results].map((r) => r[0].transcript).join(" ");
      onPartial?.(t);
      if (e.results[e.results.length - 1].isFinal) finalText = t;
    };
    rec.onerror = (e) => onError?.(e.error);
    rec.onend = () => { onEnd?.(); if (finalText) onFinal?.(finalText); };
    onStart?.(); rec.start();
    return rec;
  }

  async function askAssistant(text) {
    return api("/api/assistant", { method: "POST", body: JSON.stringify({ text }) });
  }

  // Logo Din horizontal (símbolo D-moneda + "Din") en un canvas, centrado en (cx, cy).
  // S = lado de la caja del símbolo (viewBox 120). Separación = ancho del centro de la moneda.
  const DIN_D = "M18 12H58A48 48 0 0 1 58 108H18Z M58 38A22 22 0 1 0 58 82A22 22 0 1 0 58 38Z";
  function drawDinLogo(g, cx, cy, S, { ink, coin, font }) {
    g.save();
    g.font = `800 ${S * 1.1}px ${font}`;
    const tw = g.measureText("Din").width, symW = S * 88 / 120, gap = S * 22 / 120;
    const x0 = cx - (symW + gap + tw) / 2;
    g.translate(x0 - S * 18 / 120, cy - S / 2); g.scale(S / 120, S / 120);
    g.fillStyle = ink; g.fill(new Path2D(DIN_D), "evenodd");
    g.fillStyle = coin; g.beginPath(); g.arc(58, 60, 11, 0, Math.PI * 2); g.fill();
    g.restore(); g.save();
    g.font = `800 ${S * 1.1}px ${font}`; g.fillStyle = ink; g.textAlign = "left"; g.textBaseline = "alphabetic";
    g.fillText("Din", x0 + symW + gap, cy + S * 0.4);
    g.restore();
  }

  window.Bocina = {
    drawDinLogo,
    $, money, hhmm, esc, sleep, api, toast, prefs, setPref, getPin, setPin,
    loadStatus, get status() { return status; },
    unlockAudio, chime, Voice, connect, dictate, askAssistant, volume, setVolume,
    get soundUnlocked() { return unlocked; },
    onSoundChange(fn) { soundListeners.add(fn); fn(unlocked); },
  };
})();
