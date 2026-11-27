// Din — landing. Estructura + movimiento (GSAP/ScrollTrigger), voz real y Din Box 3D diferida.
// Sin JS o con prefers-reduced-motion la página queda en su estado final estático.
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DESKTOP = matchMedia("(min-width: 1024px)");
  document.documentElement.classList.add("js");
  const idle = (fn, t = 1500) => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: t }) : setTimeout(fn, 200));

  // ---------------------------------------------------------------------------
  // Soundwave: barras con la forma de la frase real "Recibiste ochenta y cinco pesos".
  // ---------------------------------------------------------------------------
  // Picos de la frase real (recibiste + n85 + pesos_fin), con el mismo recorte de silencio que la bocina.
  // Precalculados una vez a partir de app/static/voice/: decodificar el audio en el navegador costaba segundos en celular.
  const PEAKS = [0.1,0.1,0.79,1,0.73,0.32,0.2,0.15,0.54,0.54,0.33,0.47,0.53,0.52,0.32,0.1,0.1,0.38,0.7,0.65,0.32,0.71,0.64,0.37,0.1,0.39,0.28,0.61,0.54,0.46,0.31,0.1,0.86,0.77,0.5,0.39,0.22,0.19,0.47,0.51,0.49,0.45,0.25,0.17,0.71,0.67,0.12,0.1,0.1,0.1,0.89,0.76,0.64,0.22,0.23,0.13,0.39,0.33,0.25,0.1,0.13,0.1,0.1,0.1];
  function drawWave(svg) {
    const [, , w, h] = svg.getAttribute("viewBox").split(" ").map(Number);
    const n = Math.max(8, Math.floor(w / 4.5)), gap = w / n, bw = Math.max(1.5, gap * 0.55);
    let out = "";
    for (let i = 0; i < n; i++) {
      // máximo del tramo de picos que le toca a esta barra (no se pierden sílabas en barras pocas)
      const a = Math.floor((i / n) * PEAKS.length), b = Math.max(a + 1, Math.floor(((i + 1) / n) * PEAKS.length));
      const p = Math.max(...PEAKS.slice(a, b));
      const bh = Math.max(bw, p * h);
      out += `<rect x="${(i * gap + (gap - bw) / 2).toFixed(2)}" y="${((h - bh) / 2).toFixed(2)}" width="${bw.toFixed(2)}" height="${bh.toFixed(2)}" rx="${(bw / 2).toFixed(2)}"/>`;
    }
    svg.innerHTML = out;
  }
  const drawAllWaves = () => $$("svg[data-wave]").forEach(drawWave);
  drawAllWaves();

  // ---------------------------------------------------------------------------
  // Voz: solo las 3 piezas de la frase (no las 148 de la bocina). Mismo armado que common.js:
  // se recorta el silencio de las orillas y se encadenan con Web Audio, con el "ka-ching" antes.
  // ---------------------------------------------------------------------------
  const PHRASE = ["recibiste", "n85", "pesos_fin"];
  const Voice = (() => {
    let ctx = null, raw = null, decoded = null, loading = null, playing = false;
    const T = { threshold: 0.006, leadMs: 45, tailMs: 25, fadeMs: 6, gap: 0.04 };

    async function fetchRaw() {
      if (raw) return raw;
      if (!loading) loading = (async () => {
        const st = await (await fetch("/api/status")).json();
        if (!st?.voice?.clips) return (raw = []);
        const base = `/static/voice/${encodeURIComponent(st.voice.id)}/`;
        const man = await (await fetch(base + "manifest.json")).json();
        raw = await Promise.all(PHRASE.map(async (k) => {
          const c = man.clips[k];
          return (await fetch(`${base}${c.file}?v=${c.hash}`)).arrayBuffer();
        }));
        return raw;
      })().catch(() => (raw = []));
      return loading;
    }
    function trim(buf) {
      const d = buf.getChannelData(0), sr = buf.sampleRate;
      let a = 0, b = d.length - 1;
      while (a < b && Math.abs(d[a]) < T.threshold) a++;
      while (b > a && Math.abs(d[b]) < T.threshold) b--;
      return { offset: Math.max(0, a - sr * T.leadMs / 1000) / sr, end: Math.min(d.length - 1, b + sr * T.tailMs / 1000) / sr };
    }
    function chime(c, out) {
      const t0 = c.currentTime + 0.01;
      const len = Math.floor(c.sampleRate * 0.05), nb = c.createBuffer(1, len, c.sampleRate), d = nb.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
      const noise = c.createBufferSource(); noise.buffer = nb;
      const bp = c.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 2800; bp.Q.value = 1.2;
      const ng = c.createGain(); ng.gain.value = 0.5;
      noise.connect(bp); bp.connect(ng); ng.connect(out); noise.start(t0);
      const bell = (t, base, peak) => [[1, 1], [2.76, 0.35], [5.4, 0.12]].forEach(([mult, amp]) => {
        const o = c.createOscillator(), g = c.createGain();
        o.type = "sine"; o.frequency.value = base * mult;
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(peak * amp, t + 0.008);
        g.gain.exponentialRampToValueAtTime(0.0001, t + (mult === 1 ? 0.9 : 0.35));
        o.connect(g); g.connect(out); o.start(t); o.stop(t + 1);
      });
      bell(t0 + 0.05, 1318.5, 0.32);
      bell(t0 + 0.17, 1975.5, 0.26);
      return t0 + 0.75;   // la voz entra cuando la campana ya bajó
    }
    // Reproduce ka-ching + frase. onProgress(0..1) mientras habla la voz; resuelve al terminar.
    async function play({ onStart, onProgress } = {}) {
      if (playing) return;
      playing = true;
      try {
        ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
        if (ctx.state !== "running") await ctx.resume();
        const r = await fetchRaw();
        if (!r.length) { onStart?.(); await speakFallback(); return; }
        decoded = decoded || await Promise.all(r.map((ab) => ctx.decodeAudioData(ab.slice(0))));
        const out = ctx.createGain(); out.gain.value = 0.9; out.connect(ctx.destination);
        let t = chime(ctx, out);
        const vStart = t, fade = T.fadeMs / 1000;
        decoded.forEach((buf) => {
          const { offset, end } = trim(buf), len = end - offset;
          const src = ctx.createBufferSource(), g = ctx.createGain();
          src.buffer = buf; src.connect(g); g.connect(out);
          g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(1, t + fade);
          g.gain.setValueAtTime(1, t + len - fade); g.gain.linearRampToValueAtTime(0, t + len);
          src.start(t, offset, len);
          t += len + T.gap;
        });
        onStart?.();
        await new Promise((res) => {
          const tick = () => {
            const k = (ctx.currentTime - vStart) / (t - vStart);
            onProgress?.(Math.max(0, Math.min(1, k)));
            if (ctx.currentTime >= t) res(); else requestAnimationFrame(tick);
          };
          tick();
        });
      } finally { playing = false; onProgress?.(-1); }
    }
    function speakFallback() {
      return new Promise((res) => {
        try {
          const u = new SpeechSynthesisUtterance("Recibiste 85 pesos"); u.lang = "es-MX"; u.onend = res; u.onerror = res;
          speechSynthesis.speak(u);
        } catch { res(); }
      });
    }
    return { play, fetchRaw, get playing() { return playing; } };
  })();


  // ---------------------------------------------------------------------------
  // Pantallas de la app: en celular cada bloque lleva su propia copia de la pantalla.
  // ---------------------------------------------------------------------------
  $$("[data-clone]").forEach((slot) => {
    const src = $(`#ownerScr [data-screen="${slot.dataset.clone}"]`);
    if (!src) return;
    const phone = document.createElement("div"); phone.className = "phone"; phone.setAttribute("aria-hidden", "true");
    const scr = document.createElement("div"); scr.className = "scr";
    const copy = src.cloneNode(true); copy.classList.add("on");
    scr.appendChild(copy); phone.appendChild(scr); slot.appendChild(phone);
  });

  // QR real del demo: si la cuenta demo no está configurada, se manda al demo en vez de mostrar una imagen rota
  const liveQr = $(".live-qr img.qr");
  const qrOff = () => { liveQr.hidden = true; $(".qr-off").hidden = false; };
  if (liveQr.complete && liveQr.naturalWidth === 0 && liveQr.currentSrc) qrOff();
  liveQr.addEventListener("error", qrOff);

  // Carrusel "Para quién"
  const rail = $("#rail");
  $$("[data-rail]").forEach((b) => b.addEventListener("click", () => {
    const card = rail.querySelector(".who");
    rail.scrollBy({ left: Number(b.dataset.rail) * (card.offsetWidth + 12), behavior: REDUCED ? "auto" : "smooth" });
  }));

  // Nav sólida al hacer scroll
  const nav = $("#nav");
  const onScroll = () => nav.classList.toggle("solid", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true });
  requestAnimationFrame(onScroll);

  // ---------------------------------------------------------------------------
  // Hero: Din Box 3D (diferida) y el "momento del pago"
  // ---------------------------------------------------------------------------
  const stage = $("#stage"), box = $("#box"), bank = $("#bank"), toast = $("#toast"), listen = $("#listen");
  let din = null, speakUntil = 0;
  const speaking = () => Voice.playing || performance.now() < speakUntil;

  function paymentOnBox(ms = 1800) {
    speakUntil = performance.now() + ms;
    if (din) { din.sb.showPayment({ amount: 85, label: "QR fijo" }); din.sb.bump?.(); }
  }

  async function load3D() {
    if (din || REDUCED) return;
    try {
      const c = document.createElement("canvas");
      if (!(c.getContext("webgl2") || c.getContext("webgl"))) return;
      const [{ createDinStage }, svg] = await Promise.all([
        import("/static/din-stage.js"),
        fetch("/api/demo-qr.svg").then((r) => (r.ok ? r.text() : null)).catch(() => null),
      ]);
      din = createDinStage(box, { interactive: false, idleSway: true, shadows: false, maxPixelRatio: 1.75, isSpeaking: speaking, businessName: "Abarrotes Doña Mari" });
      if (svg) await din.sb.setQR(svg).catch(() => {});
      requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.add("is-3d")));
      // no gastar GPU fuera de pantalla
      new IntersectionObserver(([e]) => (e.isIntersecting ? din.start() : din.stop())).observe(stage);
    } catch (e) { console.warn("Din Box 3D no disponible:", e); }
  }
  // 3D solo en pantallas grandes con puntero fino; en celular queda la imagen (es el mismo modelo).
  if (!REDUCED && matchMedia("(min-width: 1024px) and (pointer: fine)").matches && !navigator.connection?.saveData) {
    addEventListener("load", () => idle(load3D, 2500), { once: true });
  }

  // "Toca para escuchar": voz real + onda que se ilumina al ritmo de la frase
  const chipWave = $("svg", listen);
  const said = $("#listenSaid");   // live region: lo que dijo Din, para lectores de pantalla
  listen.addEventListener("click", async () => {
    if (Voice.playing) return;
    listen.setAttribute("aria-pressed", "true");
    said.textContent = "";
    await Voice.play({
      onStart: () => { paymentOnBox(2200); heroMoment(); said.textContent = "Din dice: Recibiste 85 pesos."; },
      onProgress: (k) => {
        const rects = chipWave.children;
        chipWave.classList.toggle("is-playing", k >= 0);
        for (let i = 0; i < rects.length; i++) rects[i].classList.toggle("on", k >= 0 && i / rects.length <= k);
      },
    });
    listen.setAttribute("aria-pressed", "false");
  });
  // precarga discreta de la voz al acercarse al botón
  ["pointerenter", "focus", "touchstart"].forEach((ev) => listen.addEventListener(ev, () => Voice.fetchRaw(), { once: true, passive: true }));

  const emit = $$(".emit span"), scanline = $(".st-scan .scanline"), payBtn = $(".st-pay .pay");
  const ease = "cubic-bezier(.16, 1, .3, 1)";
  function heroMoment() {
    if (REDUCED) return;
    emit.forEach((el, i) => el.animate([{ transform: "scale(.62)", opacity: 0.9 }, { transform: "scale(1.45)", opacity: 0 }],
      { duration: 1500, delay: i * 320, easing: ease, fill: "backwards" }));
    toast.classList.add("in");
  }

  // Bucle de ~6 s: escanea → paga → Din suena → aviso. Se pausa fuera de pantalla.
  const Loop = (() => {
    let timers = [], on = false;
    const at = (ms, fn) => timers.push(setTimeout(fn, ms));
    function cycle() {
      timers = [];
      bank.dataset.st = "scan";
      toast.classList.remove("in");
      scanline.animate([{ top: "12%", opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1, offset: 0.85 }, { top: "88%", opacity: 0 }],
        { duration: 1100, delay: 200, easing: "ease-in-out" });
      at(1500, () => (bank.dataset.st = "pay"));
      at(2150, () => payBtn.animate([{ transform: "scale(1)" }, { transform: "scale(.93)" }, { transform: "scale(1)" }], { duration: 260, easing: "ease-in-out" }));
      at(2450, () => (bank.dataset.st = "done"));
      at(2650, () => { paymentOnBox(1800); heroMoment(); });
      at(5400, () => toast.classList.remove("in"));
      at(6000, cycle);
    }
    return {
      start() { if (on) return; on = true; cycle(); },
      stop() { on = false; timers.forEach(clearTimeout); timers = []; },
    };
  })();
  // Arranca después del primer render y de la carga: animar antes de pintar retrasa la primera imagen.
  if (!REDUCED) {
    const go = () => setTimeout(() => {
      stage.classList.add("live");
      new IntersectionObserver(([e]) => (e.isIntersecting ? Loop.start() : Loop.stop())).observe(stage);
    }, 600);
    if (document.readyState === "complete") go(); else addEventListener("load", go, { once: true });
  }

  // ---------------------------------------------------------------------------
  // App del dueño (escritorio): el teléfono fijo muestra la pantalla del bloque que está al centro.
  // Funciona también con movimiento reducido (cambia sin transición).
  // ---------------------------------------------------------------------------
  const screens = $$("#ownerScr .app"), feats = $$(".feat");
  let onScreenEnter = null, current = -1;
  function showScreen(i) {
    if (i === current) return;
    current = i;
    screens.forEach((s, j) => s.classList.toggle("on", j === i));
    feats.forEach((f, j) => f.classList.toggle("on", j === i));
    onScreenEnter?.(screens[i]);
  }
  const featIO = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && DESKTOP.matches && showScreen(feats.indexOf(e.target))),
    { rootMargin: "-50% 0px -50% 0px" });
  feats.forEach((f) => featIO.observe(f));
  showScreen(0);

  // ---------------------------------------------------------------------------
  // Movimiento (GSAP + ScrollTrigger). Con movimiento reducido no se carga nada.
  // ---------------------------------------------------------------------------
  if (REDUCED) return;

  function loadScript(src) {
    return new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.async = true; s.onload = res; s.onerror = rej; document.head.appendChild(s); });
  }
  // GSAP solo mueve lo que está más abajo del hero, así que llega con la primera interacción
  // (scroll, rueda, toque o tecla). Hasta entonces la página ya se ve completa en su estado final.
  let motionStarted = false;
  const TRIGGERS = ["scroll", "wheel", "touchstart", "pointerdown", "keydown"];
  function startMotion() {
    if (motionStarted) return;
    motionStarted = true;
    TRIGGERS.forEach((ev) => removeEventListener(ev, startMotion));
    loadScript("/static/vendor/gsap/gsap.min.js")
      .then(() => loadScript("/static/vendor/gsap/ScrollTrigger.min.js"))
      .then(initMotion)
      .catch((e) => console.warn("Sin animaciones:", e));
  }
  if (scrollY > 0) startMotion();
  else TRIGGERS.forEach((ev) => addEventListener(ev, startMotion, { passive: true }));

  function initMotion() {
    const { gsap, ScrollTrigger } = window;
    gsap.registerPlugin(ScrollTrigger);
    document.documentElement.classList.add("motion");
    gsap.defaults({ ease: "power3.out", duration: 0.6 });
    const money = (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    // ---- Problema: la captura se inclina y le cae el sello ----
    const stamp = $(".stamp");
    gsap.timeline({ scrollTrigger: { trigger: ".shot", start: "top 75%", once: true } })
      .from(".shot", { y: 60, rotate: 3, autoAlpha: 0, duration: 0.8 })
      .from(stamp, { scale: 2.6, rotation: -18, autoAlpha: 0, duration: 0.32, ease: "power4.in" }, "+=0.35")
      .to(".shot", { x: -5, duration: 0.05, repeat: 3, yoyo: true, ease: "none" })
      .set(".shot", { x: 0 });

    // ---- Cómo funciona: una ilustración que avanza con el scroll ----
    const flow = $("#flow"), steps = $$("#steps .step");
    const setStep = (i) => {
      if (flow.dataset.step === String(i)) return;
      flow.dataset.step = i;
      steps.forEach((s, j) => s.classList.toggle("on", j === i));
    };
    setStep(0);
    const mm = gsap.matchMedia();
    // Fijar la sección solo cuando cabe completa en pantalla; en laptops bajas cada paso se activa al pasar
    mm.add("(min-width: 1024px) and (min-height: 800px)", () => {
      ScrollTrigger.create({
        trigger: ".how", start: "top top", end: "+=150%", pin: true, scrub: true,
        onUpdate: (s) => setStep(Math.min(2, Math.floor(s.progress * 3.2))),
      });
    });
    mm.add("(max-width: 1023px), (min-width: 1024px) and (max-height: 799px)", () => {
      steps.forEach((el, i) => ScrollTrigger.create({ trigger: el, start: "top 72%", end: "bottom 72%", onToggle: (s) => s.isActive && setStep(i), onLeaveBack: () => i === 0 && setStep(0) }));
    });

    // ---- App del dueño: entrada de cada pantalla (cuenta del total, filas y mensajes en orden) ----
    function enter(scr) {
      const total = $("[data-count]", scr);
      if (total) {
        const o = { v: 0 }, to = Number(total.dataset.count);
        gsap.to(o, { v: to, duration: 1.3, ease: "power2.out", onUpdate: () => (total.textContent = money(o.v)) });
      }
      const items = $$(".app-row, .msg", scr);
      items.forEach((el) => el.classList.add("pre"));
      items.forEach((el, i) => setTimeout(() => el.classList.toggle("pre", false), 220 + i * (el.classList.contains("msg") ? 420 : 120)));
    }
    onScreenEnter = (scr) => DESKTOP.matches && enter(scr);
    if (DESKTOP.matches && current >= 0) enter(screens[current]);
    mm.add("(max-width: 1023px)", () => {
      $$(".shot-m .app").forEach((scr) => ScrollTrigger.create({ trigger: scr, start: "top 80%", once: true, onEnter: () => enter(scr) }));
    });

    // ---- Visión: la línea se dibuja y cada hito se enciende al llegar ----
    const road = $("#road"), miles = $$(".mile", road), draw = $(".draw", road);
    road.classList.add("js-road");
    const horizontal = () => DESKTOP.matches;
    gsap.set(draw, { transformOrigin: () => (horizontal() ? "left center" : "center top") });
    ScrollTrigger.create({
      trigger: road, start: "top 75%", end: () => (horizontal() ? "top 35%" : "bottom 65%"), scrub: 0.6, invalidateOnRefresh: true,
      onUpdate: (s) => {
        const p = s.progress;
        gsap.set(draw, horizontal() ? { scaleX: p, scaleY: 1 } : { scaleY: p, scaleX: 1 });
        miles.forEach((m, i) => m.classList.toggle("reached", p >= i / (miles.length - 1) - 0.02));
      },
    });
    miles[0].classList.add("reached");
    gsap.set(draw, horizontal() ? { scaleX: 0 } : { scaleY: 0 });

    // ---- Cierre: la onda "dice" la frase una vez ----
    const closeWave = $(".close .wave");
    ScrollTrigger.create({
      trigger: closeWave, start: "top 85%", once: true,
      onEnter: () => gsap.from(closeWave.children, { scaleY: 0.1, transformOrigin: "50% 50%", duration: 0.5, stagger: 0.018, ease: "power3.out" }),
    });

    // las imágenes diferidas cambian alturas: recalcular posiciones
    addEventListener("load", () => ScrollTrigger.refresh(), { once: true });
  }
})();
