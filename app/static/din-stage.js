/**
 * din-stage.js — Escena 3D de la Din Box, reutilizable (bocina /bocina y landing /).
 *
 * Arma renderer, luces, cámara y (opcional) OrbitControls alrededor de createSoundbox().
 * Requiere el importmap de "three" y "three/addons/" en la página.
 *
 *   import { createDinStage } from "/static/din-stage.js";
 *   const st = createDinStage(el, { businessName, interactive: true, isSpeaking: () => Voice.busy });
 *   st.sb.setQR(svg); st.home(); st.scanQr(); st.back();
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";
import { RoomEnvironment } from "three/addons/RoomEnvironment.js";
import { createSoundbox } from "/static/soundbox-display.js";

const TARGET = new THREE.Vector3(0, 0.05, 0);
export const HOME_DIR = new THREE.Vector3(0.38, 0.32, 1).normalize();   // 3/4 de frente, un poco desde arriba
export const BACK_DIR = new THREE.Vector3(-0.25, 0.55, -1).normalize(); // lado del comerciante: botones y LED

const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

/**
 * @param {HTMLElement} stage contenedor (el canvas ocupa todo su tamaño)
 * @param {object} o
 * @param {string}  [o.businessName]
 * @param {boolean} [o.interactive=true]  arrastrar para girar y botones 3D clicables
 * @param {boolean} [o.idleSway=false]    vaivén lento de cámara (landing, sin controles)
 * @param {boolean} [o.shadows=true]
 * @param {number}  [o.maxPixelRatio=2]
 * @param {() => boolean} [o.isSpeaking]  la rejilla late mientras devuelva true
 * @param {() => void} [o.onUserMove]     el usuario empezó a girar la cámara
 */
export function createDinStage(stage, o = {}) {
  const { businessName = "Mi negocio", interactive = true, idleSway = false, shadows = true, maxPixelRatio = 2,
    isSpeaking = () => false, onUserMove = () => {} } = o;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxPixelRatio));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(0.35, 0.6, 0.45);
  key.castShadow = shadows;
  key.shadow.mapSize.set(shadows ? 2048 : 512, shadows ? 2048 : 512);
  Object.assign(key.shadow.camera, { left: -0.2, right: 0.2, top: 0.2, bottom: -0.2, near: 0.05, far: 2 });
  key.shadow.bias = -0.0004; key.shadow.normalBias = 0.002;
  scene.add(key);
  // el modelo trae su propia sombra de contacto; no agregamos piso con sombra dura

  const camera = new THREE.PerspectiveCamera(30, 1, 0.01, 10);
  let controls = null;
  if (interactive) {
    controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(TARGET);
    controls.enableDamping = true; controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = 0.14; controls.maxDistance = 0.7;
    controls.maxPolarAngle = Math.PI * 0.53;   // no ver por debajo del piso
    controls.addEventListener("start", () => { tween = null; onUserMove(); });
  }

  const sb = createSoundbox(THREE, { businessName });
  scene.add(sb.group);
  if (interactive) sb.enableInteraction(renderer.domElement, camera);

  let homeDist = 0.34, tween = null, running = false, swayT = 0;
  const target = controls ? controls.target : TARGET.clone();

  function resize() {
    const w = stage.clientWidth || 1, h = stage.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    // distancia para que el aparato (~16 cm con margen) quepa en la vista
    const half = THREE.MathUtils.degToRad(camera.fov / 2);
    homeDist = Math.max(0.17 / 2 / Math.tan(half), 0.19 / 2 / (Math.tan(half) * camera.aspect));
    if (controls) controls.maxDistance = Math.max(0.7, homeDist * 1.6);
    if (!controls && !tween) placeHome();
  }
  function placeHome() { camera.position.copy(target).addScaledVector(HOME_DIR, homeDist); camera.lookAt(target); }

  // vuelo de cámara propio (vista 3D y botones); el QR usa focusQR del módulo
  function flyTo(dir, dist, d = 0.85) {
    const startOffset = camera.position.clone().sub(target);
    tween = { t: 0, d, startTarget: target.clone(), startOffset, endOffset: dir.clone().multiplyScalar(dist) };
    if (controls) controls.enabled = false;
  }
  const _q = new THREE.Quaternion(), _qi = new THREE.Quaternion(), _a = new THREE.Vector3(), _b = new THREE.Vector3();
  function stepTween(dt) {
    tween.t += dt;
    const k = ease(Math.min(1, tween.t / tween.d));
    target.lerpVectors(tween.startTarget, TARGET, k);
    _a.copy(tween.startOffset).normalize(); _b.copy(tween.endOffset).normalize();
    _q.setFromUnitVectors(_a, _b); _qi.identity().slerp(_q, k);
    const len = THREE.MathUtils.lerp(tween.startOffset.length(), tween.endOffset.length(), k);
    camera.position.copy(target).add(_a.applyQuaternion(_qi).multiplyScalar(len));
    camera.lookAt(target);
    if (k >= 1) { tween = null; if (controls) controls.enabled = true; }
  }

  const clock = new THREE.Clock();
  const _sway = new THREE.Vector3();
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.1);
    if (tween) stepTween(dt);
    else if (idleSway && !controls) {
      swayT += dt;
      _sway.copy(HOME_DIR).applyAxisAngle(THREE.Object3D.DEFAULT_UP, Math.sin(swayT * 0.35) * 0.18);
      camera.position.copy(target).addScaledVector(_sway, homeDist);
      camera.lookAt(target);
    }
    if (controls) controls.update();
    sb.setSpeaking(isSpeaking());
    sb.update(dt);
    renderer.render(scene, camera);
  }

  const ro = new ResizeObserver(resize);
  ro.observe(stage);
  resize();
  placeHome();

  function start() { if (running) return; running = true; clock.getDelta(); renderer.setAnimationLoop(frame); }
  function stop() { running = false; renderer.setAnimationLoop(null); }
  start();

  return {
    sb, renderer, camera, controls, canvas: renderer.domElement,
    home(d) { flyTo(HOME_DIR, homeDist, d); },
    back(d) { flyTo(BACK_DIR, homeDist * 0.95, d); },
    scanQr(fill = 0.5) { tween = null; sb.focusQR(camera, controls, { fill }); },
    start, stop,
    get running() { return running; },
    renderOnce() { frame(); },
    dispose() { stop(); ro.disconnect(); sb.dispose(); renderer.dispose(); renderer.domElement.remove(); },
  };
}
