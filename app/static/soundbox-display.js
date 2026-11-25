/**
 * soundbox-display.js — Bocina de pagos para mostrador, variante "display".
 *
 * Cuerpo curvo redondeado; al frente un bisel claro con la tarjeta del QR;
 * atrás 3 botones y LED (versión básica, sin pantalla ni micrófono); perforaciones de bocina a los lados.
 *
 * Todo se construye con código: geometrías, materiales y CanvasTexture
 * (los logos pey | CoDi van incrustados como SVG). Sin dependencias aparte
 * de three, que se recibe como parámetro.
 *
 * Unidades: metros. Origen en el centro de la base, a nivel del piso (y = 0).
 * El frente (cara del QR, lado del cliente) mira hacia +Z; la pantalla y los
 * botones (lado del comerciante) quedan atrás.
 *
 * Uso:
 *   import { createSoundbox } from './soundbox-display.js';
 *   const sb = createSoundbox(THREE, { qr: svgString, businessName: 'Taquería' });
 *   scene.add(sb.group);
 *   sb.enableInteraction(renderer.domElement, camera); // clic en los botones
 *   // en cada frame, DESPUÉS de controls.update():
 *   sb.update(dt);
 */

// Logo pey | CoDi proporcionado por el cliente (versión clara y versión inversa), sin metadatos.
const LOGO_SVG_LIGHT = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-24.00 43.33 671.73 219.42" width="1343" height="439" fill="none">
<title>Pey | CoDi</title>
<g id="pey" fill="#0067F1" transform="translate(0 197.0) scale(0.31632) translate(-279 -842)">
<path d="M365.504 599.659C365.498 600.22 366.23 600.441 366.534 599.97C374.958 586.913 386.777 570.054 401.095 562.231C416.017 554.077 433.484 550 453.493 550C476.895 550 498.092 555.946 517.084 567.837C536.077 579.728 551 596.715 561.852 618.798C573.044 640.881 578.64 666.532 578.64 695.75C578.64 724.968 573.044 750.788 561.852 773.212C551 795.295 536.077 812.452 517.084 824.683C498.092 836.574 476.895 842.519 453.493 842.519C433.823 842.519 416.356 838.442 401.095 830.288C386.773 822.463 375.42 812.448 367.033 800.242C366.72 799.785 365.992 800.005 365.992 800.559V971.211C365.992 972.751 364.728 974 363.186 974C316.945 974 279 936.533 279 890.316V556.866C279 555.326 280.25 554.077 281.791 554.077H301.327C323.826 554.077 354.931 571.089 364.595 593.919C365.272 595.518 365.53 597.255 365.512 598.992L365.504 599.659ZM490.122 695.75C490.122 674.006 484.017 657.019 471.808 644.788C459.937 632.218 445.184 625.933 427.548 625.933C410.252 625.933 395.499 632.218 383.289 644.788C371.419 657.359 365.484 674.516 365.484 696.26C365.484 718.003 371.419 735.16 383.289 747.731C395.499 760.301 410.252 766.587 427.548 766.587C444.845 766.587 459.598 760.301 471.808 747.731C484.017 734.821 490.122 717.494 490.122 695.75Z"/>
<path d="M889.398 691.673C889.398 706.228 876.881 717.154 862.319 717.154H691.597C691.272 717.154 691.016 717.433 691.043 717.757C692.48 735.13 698.06 748.519 707.783 757.923C717.957 767.096 730.336 771.683 744.92 771.683C765.981 771.683 780.816 763.046 789.424 745.773C789.909 744.799 790.893 744.163 791.982 744.163H879.197C881.017 744.163 882.35 745.877 881.854 747.627C876.946 764.933 868.608 780.596 856.84 794.615C844.63 809.564 829.199 821.285 810.546 829.779C791.892 838.272 771.035 842.519 747.972 842.519C720.162 842.519 695.404 836.574 673.698 824.683C651.992 812.792 635.035 795.805 622.825 773.721C610.616 751.638 604.511 725.817 604.511 696.26C604.511 666.702 610.446 640.881 622.317 618.798C634.526 596.715 651.484 579.728 673.189 567.837C694.895 555.946 719.823 550 747.972 550C775.444 550 799.862 555.776 821.229 567.327C842.595 578.878 859.214 595.356 871.084 616.76C883.294 638.163 889.398 663.135 889.398 691.673ZM797.58 668.74C799.122 668.74 800.378 667.491 800.311 665.952C799.71 652.306 794.643 641.344 785.109 633.067C774.935 624.234 762.217 619.817 746.955 619.817C732.371 619.817 719.992 624.064 709.818 632.558C700.664 640.462 694.742 651.457 692.051 665.541C691.731 667.218 693.042 668.74 694.75 668.74H797.58Z"/>
<path d="M1217.21 554.077C1219.21 554.077 1220.56 556.116 1219.78 557.956L1065.02 922.494C1051.89 953.411 1021.54 973.49 987.941 973.49H954.077C952.052 973.49 950.701 971.403 951.531 969.557L1014.78 828.981C1014.84 828.84 1014.84 828.679 1014.78 828.536L901.025 557.947C900.252 556.109 901.603 554.077 903.598 554.077H938.203C973.271 554.077 1004.62 575.92 1016.76 608.805L1061.66 730.508C1061.84 730.995 1062.53 730.994 1062.71 730.507L1107.2 609.003C1119.28 576.015 1150.68 554.077 1185.83 554.077H1217.21Z"/>
</g>
<g id="divider" stroke="#999999" stroke-width="4" stroke-linecap="round">
<path d="M327.66 119.45V183.45"/></g>
<g id="codi" transform="translate(337.91 0)">
<path fill="#000000" d="M179.660339,142.999527 C179.660355,130.704590 179.660355,118.909668 179.660355,105.777809 C193.213425,106.603577 206.742813,105.752113 219.456055,108.575562 C241.258652,113.417656 254.837357,135.710403 251.863632,158.194763 C248.966980,180.096313 229.653702,196.878906 207.315430,196.898331 C198.335434,196.906128 189.355438,196.899612 179.660309,196.899612 C179.660309,178.960648 179.660309,161.230103 179.660339,142.999527 M200.775146,178.672424 C209.662689,179.228760 218.036850,178.056747 224.974945,171.739914 C234.080231,163.449982 236.530472,150.121414 230.852005,139.418304 C224.721512,127.863159 211.852615,122.428650 197.890747,125.699883 C197.890747,142.402420 197.860336,159.178711 197.974136,175.954010 C197.980286,176.860779 199.195023,177.759369 200.775146,178.672424 z"/>
<path fill="#999999" d="M130.000900,127.014679 C134.833435,110.710411 142.903870,96.460281 156.015106,85.279457 C186.909378,58.933834 238.414307,62.003311 265.854645,91.760826 C267.322632,93.352791 269.898407,94.511803 272.081238,94.750618 C280.060730,95.623611 286.446899,102.654449 285.769989,110.384438 C285.075500,118.315628 277.996674,124.484711 270.079468,124.058449 C261.718048,123.608261 255.102463,116.650215 256.246521,108.394127 C256.805420,104.360840 255.283569,102.282387 252.807281,99.927277 C221.796463,70.433838 164.040665,76.475876 146.449554,124.335159 C146.014694,125.518242 146.006516,126.858154 145.615295,128.686508 C144.189865,134.503372 142.663712,139.715942 141.865952,145.037720 C141.597031,146.831619 142.636642,149.486771 144.002029,150.748810 C151.010574,157.226944 151.689758,167.627045 145.194962,174.359741 C138.909134,180.875763 128.427139,180.645416 122.073799,173.851654 C115.840218,167.185913 116.612473,156.870529 123.684402,150.744568 C124.963844,149.636261 126.465248,148.173538 126.768944,146.655350 C128.069641,140.153152 128.960571,133.568970 130.000900,127.014679 z"/>
<path fill="#000000" d="M46.234642,132.232758 C35.296688,144.558426 35.263584,160.331787 45.897930,171.680527 C56.883106,183.403671 72.607109,183.647491 87.523224,172.007599 C90.656746,177.081131 93.764420,182.112839 96.850426,187.109436 C84.735023,200.563248 55.588482,205.097977 35.637634,187.269562 C15.432365,169.213806 14.348455,138.646622 33.243198,119.135796 C50.238899,101.585938 81.537315,100.400078 96.910545,116.902771 C93.841248,121.937546 90.738853,127.026611 87.629066,132.127808 C71.182892,120.809769 58.823597,120.809677 46.234642,132.232758 z"/>
<path fill="#000000" d="M129.599548,127.040680 C128.960571,133.568970 128.069641,140.153152 126.768944,146.655350 C126.465248,148.173538 124.963844,149.636261 123.684402,150.744568 C116.612473,156.870529 115.840218,167.185913 122.073799,173.851654 C128.427139,180.645416 138.909134,180.875763 145.194962,174.359741 C151.689758,167.627045 151.010574,157.226944 144.002029,150.748810 C142.636642,149.486771 141.597031,146.831619 141.865952,145.037720 C142.663712,139.715942 144.189865,134.503372 145.763031,129.074921 C162.997681,135.453766 171.804047,153.187302 167.333038,171.669495 C163.115784,189.102768 147.490768,199.870636 129.161972,197.974777 C113.073181,196.310623 99.608841,181.252625 99.212746,164.480698 C98.745621,144.700699 110.619629,129.885056 129.599548,127.040680 z"/>
<path fill="#000000" d="M279.803528,132.387680 C279.803223,153.982239 279.803223,175.111786 279.803223,196.576813 C273.888916,196.576813 268.318085,196.576813 262.388031,196.576813 C262.388031,174.394287 262.388031,152.173172 262.388031,129.349579 C267.442810,129.349579 272.565308,129.246048 277.674042,129.464172 C278.417572,129.495911 279.095520,131.064987 279.803528,132.387680 z"/>
</g></svg>`;
const LOGO_SVG_DARK = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-24.00 43.33 671.73 219.42" width="1343" height="439" fill="none">
<title>Pey | CoDi (inverse)</title>
<g id="pey" fill="#FFFFFF" transform="translate(0 197.0) scale(0.31632) translate(-279 -842)">
<path d="M365.504 599.659C365.498 600.22 366.23 600.441 366.534 599.97C374.958 586.913 386.777 570.054 401.095 562.231C416.017 554.077 433.484 550 453.493 550C476.895 550 498.092 555.946 517.084 567.837C536.077 579.728 551 596.715 561.852 618.798C573.044 640.881 578.64 666.532 578.64 695.75C578.64 724.968 573.044 750.788 561.852 773.212C551 795.295 536.077 812.452 517.084 824.683C498.092 836.574 476.895 842.519 453.493 842.519C433.823 842.519 416.356 838.442 401.095 830.288C386.773 822.463 375.42 812.448 367.033 800.242C366.72 799.785 365.992 800.005 365.992 800.559V971.211C365.992 972.751 364.728 974 363.186 974C316.945 974 279 936.533 279 890.316V556.866C279 555.326 280.25 554.077 281.791 554.077H301.327C323.826 554.077 354.931 571.089 364.595 593.919C365.272 595.518 365.53 597.255 365.512 598.992L365.504 599.659ZM490.122 695.75C490.122 674.006 484.017 657.019 471.808 644.788C459.937 632.218 445.184 625.933 427.548 625.933C410.252 625.933 395.499 632.218 383.289 644.788C371.419 657.359 365.484 674.516 365.484 696.26C365.484 718.003 371.419 735.16 383.289 747.731C395.499 760.301 410.252 766.587 427.548 766.587C444.845 766.587 459.598 760.301 471.808 747.731C484.017 734.821 490.122 717.494 490.122 695.75Z"/>
<path d="M889.398 691.673C889.398 706.228 876.881 717.154 862.319 717.154H691.597C691.272 717.154 691.016 717.433 691.043 717.757C692.48 735.13 698.06 748.519 707.783 757.923C717.957 767.096 730.336 771.683 744.92 771.683C765.981 771.683 780.816 763.046 789.424 745.773C789.909 744.799 790.893 744.163 791.982 744.163H879.197C881.017 744.163 882.35 745.877 881.854 747.627C876.946 764.933 868.608 780.596 856.84 794.615C844.63 809.564 829.199 821.285 810.546 829.779C791.892 838.272 771.035 842.519 747.972 842.519C720.162 842.519 695.404 836.574 673.698 824.683C651.992 812.792 635.035 795.805 622.825 773.721C610.616 751.638 604.511 725.817 604.511 696.26C604.511 666.702 610.446 640.881 622.317 618.798C634.526 596.715 651.484 579.728 673.189 567.837C694.895 555.946 719.823 550 747.972 550C775.444 550 799.862 555.776 821.229 567.327C842.595 578.878 859.214 595.356 871.084 616.76C883.294 638.163 889.398 663.135 889.398 691.673ZM797.58 668.74C799.122 668.74 800.378 667.491 800.311 665.952C799.71 652.306 794.643 641.344 785.109 633.067C774.935 624.234 762.217 619.817 746.955 619.817C732.371 619.817 719.992 624.064 709.818 632.558C700.664 640.462 694.742 651.457 692.051 665.541C691.731 667.218 693.042 668.74 694.75 668.74H797.58Z"/>
<path d="M1217.21 554.077C1219.21 554.077 1220.56 556.116 1219.78 557.956L1065.02 922.494C1051.89 953.411 1021.54 973.49 987.941 973.49H954.077C952.052 973.49 950.701 971.403 951.531 969.557L1014.78 828.981C1014.84 828.84 1014.84 828.679 1014.78 828.536L901.025 557.947C900.252 556.109 901.603 554.077 903.598 554.077H938.203C973.271 554.077 1004.62 575.92 1016.76 608.805L1061.66 730.508C1061.84 730.995 1062.53 730.994 1062.71 730.507L1107.2 609.003C1119.28 576.015 1150.68 554.077 1185.83 554.077H1217.21Z"/>
</g>
<g id="divider" stroke="#999999" stroke-width="4" stroke-linecap="round">
<path d="M327.66 119.45V183.45"/></g>
<g id="codi" transform="translate(337.91 0)">
<path fill="#FFFFFF" d="M179.660339,142.999527 C179.660355,130.704590 179.660355,118.909668 179.660355,105.777809 C193.213425,106.603577 206.742813,105.752113 219.456055,108.575562 C241.258652,113.417656 254.837357,135.710403 251.863632,158.194763 C248.966980,180.096313 229.653702,196.878906 207.315430,196.898331 C198.335434,196.906128 189.355438,196.899612 179.660309,196.899612 C179.660309,178.960648 179.660309,161.230103 179.660339,142.999527 M200.775146,178.672424 C209.662689,179.228760 218.036850,178.056747 224.974945,171.739914 C234.080231,163.449982 236.530472,150.121414 230.852005,139.418304 C224.721512,127.863159 211.852615,122.428650 197.890747,125.699883 C197.890747,142.402420 197.860336,159.178711 197.974136,175.954010 C197.980286,176.860779 199.195023,177.759369 200.775146,178.672424 z"/>
<path fill="#999999" d="M130.000900,127.014679 C134.833435,110.710411 142.903870,96.460281 156.015106,85.279457 C186.909378,58.933834 238.414307,62.003311 265.854645,91.760826 C267.322632,93.352791 269.898407,94.511803 272.081238,94.750618 C280.060730,95.623611 286.446899,102.654449 285.769989,110.384438 C285.075500,118.315628 277.996674,124.484711 270.079468,124.058449 C261.718048,123.608261 255.102463,116.650215 256.246521,108.394127 C256.805420,104.360840 255.283569,102.282387 252.807281,99.927277 C221.796463,70.433838 164.040665,76.475876 146.449554,124.335159 C146.014694,125.518242 146.006516,126.858154 145.615295,128.686508 C144.189865,134.503372 142.663712,139.715942 141.865952,145.037720 C141.597031,146.831619 142.636642,149.486771 144.002029,150.748810 C151.010574,157.226944 151.689758,167.627045 145.194962,174.359741 C138.909134,180.875763 128.427139,180.645416 122.073799,173.851654 C115.840218,167.185913 116.612473,156.870529 123.684402,150.744568 C124.963844,149.636261 126.465248,148.173538 126.768944,146.655350 C128.069641,140.153152 128.960571,133.568970 130.000900,127.014679 z"/>
<path fill="#FFFFFF" d="M46.234642,132.232758 C35.296688,144.558426 35.263584,160.331787 45.897930,171.680527 C56.883106,183.403671 72.607109,183.647491 87.523224,172.007599 C90.656746,177.081131 93.764420,182.112839 96.850426,187.109436 C84.735023,200.563248 55.588482,205.097977 35.637634,187.269562 C15.432365,169.213806 14.348455,138.646622 33.243198,119.135796 C50.238899,101.585938 81.537315,100.400078 96.910545,116.902771 C93.841248,121.937546 90.738853,127.026611 87.629066,132.127808 C71.182892,120.809769 58.823597,120.809677 46.234642,132.232758 z"/>
<path fill="#FFFFFF" d="M129.599548,127.040680 C128.960571,133.568970 128.069641,140.153152 126.768944,146.655350 C126.465248,148.173538 124.963844,149.636261 123.684402,150.744568 C116.612473,156.870529 115.840218,167.185913 122.073799,173.851654 C128.427139,180.645416 138.909134,180.875763 145.194962,174.359741 C151.689758,167.627045 151.010574,157.226944 144.002029,150.748810 C142.636642,149.486771 141.597031,146.831619 141.865952,145.037720 C142.663712,139.715942 144.189865,134.503372 145.763031,129.074921 C162.997681,135.453766 171.804047,153.187302 167.333038,171.669495 C163.115784,189.102768 147.490768,199.870636 129.161972,197.974777 C113.073181,196.310623 99.608841,181.252625 99.212746,164.480698 C98.745621,144.700699 110.619629,129.885056 129.599548,127.040680 z"/>
<path fill="#FFFFFF" d="M279.803528,132.387680 C279.803223,153.982239 279.803223,175.111786 279.803223,196.576813 C273.888916,196.576813 268.318085,196.576813 262.388031,196.576813 C262.388031,174.394287 262.388031,152.173172 262.388031,129.349579 C267.442810,129.349579 272.565308,129.246048 277.674042,129.464172 C278.417572,129.495911 279.095520,131.064987 279.803528,132.387680 z"/>
</g></svg>`;
const LOGO_ASPECT = 671.73 / 219.42;

// ═════════════════════════════════════════════════════════════════════════
// Utilidades
// ═════════════════════════════════════════════════════════════════════════

const FONT = '"Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
const COLOR_BODY = '#17161a';
const COLOR_LIGHT = '#f6f4ef';
const LED_COLORS = { green: '#25e07e', red: '#ff3b30', amber: '#ffb01f' };
const LED_STATES = ['off', 'idle', 'talking', 'listening', 'error'];
const PRESS_DEPTH = 0.0025;   // 2.5 mm de recorrido
const PRESS_DOWN = 0.07;      // s
const PRESS_UP = 0.16;        // s
const DEG = Math.PI / 180;
const CARD_INSTRUCTION = 'Abre tu app de banco, ve a CoDi, escanea y paga.';
// Marca Din (tokens.css): tinta, azul Din y símbolo D-moneda (viewBox 120)
const DIN_INK = '#0B1A33', DIN_BRAND = '#154781';
const DIN_D = 'M18 12H58A48 48 0 0 1 58 108H18Z M58 38A22 22 0 1 0 58 82A22 22 0 1 0 58 38Z';

function makeCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return c;
}

/** Textura desde canvas, en sRGB. `crisp` = sin mipmaps y magFilter Nearest (para el QR). */
function canvasTexture(THREE, canvas, crisp = false) {
  const t = new THREE.CanvasTexture(canvas);
  t.colorSpace = THREE.SRGBColorSpace;
  if (crisp) {
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.LinearFilter;
    t.generateMipmaps = false;
  } else {
    t.anisotropy = 8;
  }
  return t;
}

/** Carga un string SVG como imagen (data URL: no "ensucia" el canvas para WebGL). */
function loadSvgImage(svg) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('No se pudo cargar el SVG del logo'));
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  });
}

/** Contorno de rectángulo redondeado centrado en (cx, cy). */
function roundedRectShape(THREE, w, h, r, cx = 0, cy = 0) {
  r = Math.max(1e-5, Math.min(r, w / 2 - 1e-6, h / 2 - 1e-6));
  const s = new THREE.Shape();
  const x0 = cx - w / 2, y0 = cy - h / 2, x1 = cx + w / 2, y1 = cy + h / 2;
  s.moveTo(x0 + r, y0);
  s.lineTo(x1 - r, y0); s.absarc(x1 - r, y0 + r, r, -Math.PI / 2, 0, false);
  s.lineTo(x1, y1 - r); s.absarc(x1 - r, y1 - r, r, 0, Math.PI / 2, false);
  s.lineTo(x0 + r, y1); s.absarc(x0 + r, y1 - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(x0, y0 + r); s.absarc(x0 + r, y0 + r, r, Math.PI, Math.PI * 1.5, false);
  return s;
}

/** Plano con esquinas redondeadas y UV normalizadas 0–1 (para tarjetas impresas). */
function roundedPlane(THREE, w, h, r) {
  const g = new THREE.ShapeGeometry(roundedRectShape(THREE, w, h, r), 8);
  const pos = g.attributes.position, uv = g.attributes.uv;
  for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) / w + 0.5, pos.getY(i) / h + 0.5);
  uv.needsUpdate = true;
  return g;
}

/**
 * Recalcula normales "con pliegue": suaviza entre caras con ángulo menor a
 * `creaseDeg` y deja aristas vivas por encima. ExtrudeGeometry trae normales
 * planas por triángulo, lo que haría ver facetados los biseles.
 */
function creaseNormals(THREE, geo, creaseDeg = 40) {
  const g = geo.index ? geo.toNonIndexed() : geo;
  const pos = g.attributes.position;
  const tris = pos.count / 3;
  const cosT = Math.cos(creaseDeg * DEG);
  const fn = new Float32Array(tris * 3);   // normal unitaria por cara
  const fw = new Float32Array(tris * 3);   // normal ponderada por área
  const buckets = new Map();
  const keys = new Array(pos.count);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const e1 = new THREE.Vector3(), e2 = new THREE.Vector3();
  const key = (i) => `${Math.round(pos.getX(i) * 1e5)}|${Math.round(pos.getY(i) * 1e5)}|${Math.round(pos.getZ(i) * 1e5)}`;
  for (let t = 0; t < tris; t++) {
    a.fromBufferAttribute(pos, t * 3); b.fromBufferAttribute(pos, t * 3 + 1); c.fromBufferAttribute(pos, t * 3 + 2);
    e1.subVectors(c, b); e2.subVectors(a, b); e1.cross(e2);
    fw[t * 3] = e1.x; fw[t * 3 + 1] = e1.y; fw[t * 3 + 2] = e1.z;
    const len = e1.length() || 1;
    fn[t * 3] = e1.x / len; fn[t * 3 + 1] = e1.y / len; fn[t * 3 + 2] = e1.z / len;
    for (let k = 0; k < 3; k++) {
      const i = t * 3 + k, kk = key(i);
      keys[i] = kk;
      let list = buckets.get(kk);
      if (!list) buckets.set(kk, (list = []));
      list.push(t);
    }
  }
  const normals = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const t = (i / 3) | 0;
    let nx = 0, ny = 0, nz = 0;
    for (const s of buckets.get(keys[i])) {
      const d = fn[t * 3] * fn[s * 3] + fn[t * 3 + 1] * fn[s * 3 + 1] + fn[t * 3 + 2] * fn[s * 3 + 2];
      if (d > cosT) { nx += fw[s * 3]; ny += fw[s * 3 + 1]; nz += fw[s * 3 + 2]; }
    }
    const l = Math.hypot(nx, ny, nz) || 1;
    normals[i * 3] = nx / l; normals[i * 3 + 1] = ny / l; normals[i * 3 + 2] = nz / l;
  }
  g.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  return g;
}

/** Caja con todas las aristas redondeadas, centrada; w/h/d en X/Y/Z. */
function roundedBox(THREE, w, h, d, r, bevel, curveSegments = 8, bevelSegments = 4) {
  const b = Math.min(bevel, d / 2 - 1e-5, w / 2 - 1e-5, h / 2 - 1e-5);
  const shape = roundedRectShape(THREE, w - 2 * b, h - 2 * b, Math.max(r - b, 2e-4));
  const g = new THREE.ExtrudeGeometry(shape, {
    depth: d - 2 * b, bevelEnabled: true, bevelThickness: b, bevelSize: b,
    bevelSegments, curveSegments,
  });
  g.translate(0, 0, -(d - 2 * b) / 2);
  return creaseNormals(THREE, g);
}

/** Desplaza hacia adentro una distancia d un polígono convexo en sentido antihorario. */
function insetConvex(THREE, pts, d) {
  const n = pts.length, lines = [];
  for (let i = 0; i < n; i++) {
    const a = pts[i], b = pts[(i + 1) % n];
    const dir = b.clone().sub(a).normalize();
    lines.push({ p: a.clone().addScaledVector(new THREE.Vector2(-dir.y, dir.x), d), dir });
  }
  const cross = (u, v) => u.x * v.y - u.y * v.x;
  return pts.map((_, i) => {
    const l1 = lines[(i - 1 + n) % n], l2 = lines[i];
    const t = cross(l2.p.clone().sub(l1.p), l2.dir) / cross(l1.dir, l2.dir);
    return l1.p.clone().addScaledVector(l1.dir, t);
  });
}

/** Polígono con esquinas fileteadas; `r` puede ser un número o un radio por vértice. */
function roundedPolygonShape(THREE, pts, r) {
  const s = new THREE.Shape(), n = pts.length;
  for (let i = 0; i < n; i++) {
    const ri = Array.isArray(r) ? r[i] : r;
    const prev = pts[(i - 1 + n) % n], cur = pts[i], next = pts[(i + 1) % n];
    const a = cur.clone().add(prev.clone().sub(cur).normalize().multiplyScalar(ri));
    const b = cur.clone().add(next.clone().sub(cur).normalize().multiplyScalar(ri));
    if (i === 0) s.moveTo(a.x, a.y); else s.lineTo(a.x, a.y);
    s.quadraticCurveTo(cur.x, cur.y, b.x, b.y);
  }
  s.closePath();
  return s;
}

/**
 * Sólido a partir de un perfil lateral convexo en el plano (z, y), en sentido
 * antihorario, extruido a lo ancho (eje X, centrado). El perfil dado es la
 * superficie EXTERIOR: se encoge `bevel` y el bisel lo devuelve redondeado.
 */
function profileSolid(THREE, outer, width, radii, bevel, bevelSegments = 5, curveSegments = 10) {
  const inner = insetConvex(THREE, outer, bevel);
  const shape = roundedPolygonShape(THREE, inner, radii);
  const g = new THREE.ExtrudeGeometry(shape, {
    depth: width - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel, bevelSegments, curveSegments,
  });
  g.translate(0, 0, -(width - 2 * bevel) / 2);
  g.rotateY(-Math.PI / 2);   // perfil (z, y) → mundo; extrusión → eje X
  return creaseNormals(THREE, g);
}

/** Lámina de grosor `t` que sigue una polilínea (z, y), extruida a lo ancho. */
function sheetAlongPath(THREE, path, t, width, bevel = 0.0015) {
  const V = THREE.Vector2, A = [], B = [];
  for (let i = 0; i < path.length; i++) {
    const p0 = path[Math.max(0, i - 1)], p1 = path[Math.min(path.length - 1, i + 1)];
    const tg = p1.clone().sub(p0).normalize();
    const nL = new V(-tg.y, tg.x).multiplyScalar(t / 2);
    A.push(path[i].clone().add(nL)); B.push(path[i].clone().sub(nL));
  }
  const pts = A.concat(B.reverse());
  const s = new THREE.Shape(pts);
  const g = new THREE.ExtrudeGeometry(s, {
    depth: width - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * 0.6, bevelSegments: 3, curveSegments: 4,
  });
  g.translate(0, 0, -(width - 2 * bevel) / 2);
  g.rotateY(-Math.PI / 2);
  return creaseNormals(THREE, g, 35);
}

/**
 * Marco local alineado a una cara plana de un perfil: origen en `a` (z, y),
 * local Y sube de `a` hacia `b`, local Z es la normal exterior.
 * facing 'front' (mira a +Z) o 'back' (mira a −Z, con el texto legible desde atrás).
 */
function faceFrame(THREE, a, b, facing = 'front', x = 0) {
  const g = new THREE.Group();
  const Y = new THREE.Vector3(0, b.y - a.y, b.x - a.x).normalize();
  const X = new THREE.Vector3(facing === 'front' ? 1 : -1, 0, 0);
  const Z = new THREE.Vector3().crossVectors(X, Y);
  g.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(X, Y, Z));
  g.position.set(x, a.y, a.x);
  return g;
}

/** Tapa de botón por torno: cara superior plana con filete suave. Base en y = 0. */
function buttonCapGeometry(THREE, R, H) {
  const e = Math.min(0.0013, R * 0.22);
  const V = THREE.Vector2;
  const pts = [
    new V(0, H), new V(R - e * 1.25, H), new V(R - e * 0.55, H - e * 0.12),
    new V(R - e * 0.15, H - e * 0.5), new V(R, H - e * 1.1), new V(R, 0),
  ];
  return new THREE.LatheGeometry(pts, 40);
}

/** Ajusta el tamaño de fuente hasta que `text` quepa en `maxW`. Devuelve el tamaño usado. */
function fitFont(g, text, maxW, size, weight = 600) {
  let s = size;
  for (let i = 0; i < 40; i++) {
    g.font = `${weight} ${s}px ${FONT}`;
    if (g.measureText(text).width <= maxW) break;
    s *= 0.94;
  }
  return s;
}

/** Parte un texto en líneas que quepan en `maxW` (con la fuente actual de `g`). */
function wrapLines(g, text, maxW) {
  const words = text.split(/\s+/), lines = [];
  let line = '';
  for (const w of words) {
    const test = line ? `${line} ${w}` : w;
    if (g.measureText(test).width <= maxW || !line) line = test;
    else { lines.push(line); line = w; }
  }
  if (line) lines.push(line);
  return lines;
}

function roundRectPath(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/** Íconos vectoriales para las tapas de los botones (sin depender de glifos de fuentes). */
function drawButtonIcon(canvas, name, color) {
  const g = canvas.getContext('2d');
  const s = canvas.width, c = s / 2;
  g.clearRect(0, 0, s, s);
  g.strokeStyle = color; g.fillStyle = color;
  g.lineCap = 'round'; g.lineJoin = 'round';
  g.lineWidth = s * 0.075;
  if (name === 'vol-' || name === 'vol+') {
    g.beginPath(); g.moveTo(c - s * 0.2, c); g.lineTo(c + s * 0.2, c); g.stroke();
    if (name === 'vol+') { g.beginPath(); g.moveTo(c, c - s * 0.2); g.lineTo(c, c + s * 0.2); g.stroke(); }
  } else if (name === 'last') {
    // ↺ : arco con punta de flecha en sentido antihorario
    const r = s * 0.19, a0 = -0.62 * Math.PI, a1 = 1.08 * Math.PI;
    g.beginPath(); g.arc(c, c + s * 0.02, r, a0, a1, false); g.stroke();
    const px = c + r * Math.cos(a0), py = c + s * 0.02 + r * Math.sin(a0);
    const tx = Math.sin(a0), ty = -Math.cos(a0);
    const nx = -ty, ny = tx, L = s * 0.13, W = s * 0.09;
    g.beginPath();
    g.moveTo(px + tx * L * 0.9, py + ty * L * 0.9);
    g.lineTo(px - tx * L * 0.3 + nx * W, py - ty * L * 0.3 + ny * W);
    g.lineTo(px - tx * L * 0.3 - nx * W, py - ty * L * 0.3 - ny * W);
    g.closePath(); g.fill();
  } else if (name === 'talk') {
    // Micrófono
    const w = s * 0.17, h = s * 0.3, top = c - s * 0.25;
    roundRectPath(g, c - w / 2, top, w, h, w / 2); g.fill();
    g.lineWidth = s * 0.06;
    g.beginPath(); g.arc(c, top + h * 0.55, s * 0.16, 0.05 * Math.PI, 0.95 * Math.PI, false); g.stroke();
    g.beginPath(); g.moveTo(c, top + h * 0.55 + s * 0.16); g.lineTo(c, c + s * 0.25); g.stroke();
    g.beginPath(); g.moveTo(c - s * 0.1, c + s * 0.25); g.lineTo(c + s * 0.1, c + s * 0.25); g.stroke();
  }
}

/** Gradiente radial blanco→transparente para halos de luz (se tiñe con material.color). */
function glowCanvas(size = 128) {
  const c = makeCanvas(size, size), g = c.getContext('2d');
  const gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gr.addColorStop(0, 'rgba(255,255,255,1)');
  gr.addColorStop(0.35, 'rgba(255,255,255,0.45)');
  gr.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = gr; g.fillRect(0, 0, size, size);
  return c;
}

/** Sombra de contacto: mancha oscura difusa para apoyar el aparato en el piso. */
function contactShadowCanvas() {
  const s = 256, c = makeCanvas(s, s), g = c.getContext('2d');
  const gr = g.createRadialGradient(s / 2, s / 2, s * 0.05, s / 2, s / 2, s / 2);
  gr.addColorStop(0, 'rgba(0,0,0,0.55)');
  gr.addColorStop(0.45, 'rgba(0,0,0,0.28)');
  gr.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = gr; g.fillRect(0, 0, s, s);
  return c;
}

function formatAmount(a) {
  const n = typeof a === 'number' ? a : Number(String(a ?? '').replace(/[^0-9.\-]/g, ''));
  if (a !== '' && a != null && Number.isFinite(n)) {
    return new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN' }).format(n);
  }
  return String(a ?? '');
}

// ─── QR: normalización a una matriz limpia con quiet zone de 4 módulos ───

/** Convierte un string SVG (o canvas/imagen) en un canvas rasterizado grande. */
async function sourceToCanvas(src) {
  if (!src) return null;
  if (typeof HTMLCanvasElement !== 'undefined' && src instanceof HTMLCanvasElement) return src;
  if (typeof OffscreenCanvas !== 'undefined' && src instanceof OffscreenCanvas) return src;
  let img = src;
  let url = null;
  if (typeof src === 'string') {
    // Forzamos un tamaño grande para rasterizar el vector con detalle.
    const doc = new DOMParser().parseFromString(src.trim(), 'image/svg+xml');
    const svg = doc.documentElement;
    if (!svg || svg.nodeName.toLowerCase() !== 'svg') throw new Error('setQR: el string no es un SVG válido');
    svg.setAttribute('width', '1024');
    svg.setAttribute('height', '1024');
    svg.setAttribute('shape-rendering', 'crispEdges');
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], { type: 'image/svg+xml' });
    url = URL.createObjectURL(blob);
    img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = () => rej(new Error('setQR: no se pudo cargar el SVG')); img.src = url; });
  }
  const w = img.naturalWidth || img.width || 1024, h = img.naturalHeight || img.height || 1024;
  const scale = Math.max(1, Math.ceil(1024 / Math.max(w, h)));
  const c = makeCanvas(w * scale, h * scale), g = c.getContext('2d');
  g.imageSmoothingEnabled = false;
  g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
  g.drawImage(img, 0, 0, c.width, c.height);
  if (url) URL.revokeObjectURL(url);
  return c;
}

/**
 * Detecta la cuadrícula del QR en un canvas: caja de módulos oscuros + ancho del
 * patrón localizador (7 módulos). Devuelve { n, cells } o null si no lo reconoce.
 */
function extractQRMatrix(canvas) {
  const w = canvas.width, h = canvas.height;
  const data = canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, w, h).data;
  const dark = (x, y) => {
    const i = (y * w + x) * 4;
    return data[i + 3] > 127 && (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) < 128;
  };
  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (dark(x, y)) { if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; }
  }
  if (maxX < 0) return null;
  const bw = maxX - minX + 1, bh = maxY - minY + 1;
  if (Math.abs(bw - bh) > bw * 0.03) return null;
  const yRow = Math.min(maxY, minY + Math.max(1, Math.round(bw / 120)));
  let run = 0;
  while (minX + run <= maxX && dark(minX + run, yRow)) run++;
  const moduleGuess = run / 7;
  if (moduleGuess < 1) return null;
  let n = Math.round(bw / moduleGuess);
  n = 21 + Math.round((n - 21) / 4) * 4;   // versiones válidas: 21, 25, ... 177
  if (n < 21 || n > 177) return null;
  const m = bw / n;
  const cells = new Uint8Array(n * n);
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const x = Math.min(maxX, Math.floor(minX + (i + 0.5) * m));
    const y = Math.min(maxY, Math.floor(minY + (j + 0.5) * m));
    cells[j * n + i] = dark(x, y) ? 1 : 0;
  }
  const finderOk = (ox, oy) => cells[(oy + 3) * n + ox + 3] && cells[oy * n + ox] && !cells[(oy + 1) * n + ox + 1];
  if (!finderOk(0, 0) || !finderOk(n - 7, 0) || !finderOk(0, n - 7)) return null;
  return { n, cells };
}

/**
 * Pinta el QR en `target` (≥ 1024 px): píxeles enteros por módulo y 4 módulos
 * de margen blanco. Si no se reconoce la cuadrícula, dibuja la fuente escalada
 * con margen blanco generoso como respaldo.
 */
async function renderQRInto(target, src) {
  const g = target.getContext('2d');
  const source = await sourceToCanvas(src);
  if (!source) return;
  const mtx = extractQRMatrix(source);
  if (mtx) {
    const total = mtx.n + 8;
    const px = Math.ceil(1024 / total);
    target.width = target.height = total * px;
    g.imageSmoothingEnabled = false;
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, target.width, target.height);
    g.fillStyle = '#000000';
    for (let j = 0; j < mtx.n; j++) for (let i = 0; i < mtx.n; i++) {
      if (mtx.cells[j * mtx.n + i]) g.fillRect((i + 4) * px, (j + 4) * px, px, px);
    }
  } else {
    console.warn('[soundbox] No se reconoció la cuadrícula del QR; se dibuja escalado con margen.');
    target.width = target.height = 1024;
    g.imageSmoothingEnabled = false;
    g.fillStyle = '#ffffff'; g.fillRect(0, 0, 1024, 1024);
    const m = 110;
    g.drawImage(source, m, m, 1024 - 2 * m, 1024 - 2 * m);
  }
}

function drawQRPlaceholder(target) {
  target.width = target.height = 1024;
  const g = target.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, 1024, 1024);
  g.strokeStyle = '#c9c5bc'; g.lineWidth = 8; g.setLineDash([28, 20]);
  g.strokeRect(120, 120, 784, 784);
  g.setLineDash([]); g.fillStyle = '#9b978f'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.font = `600 64px ${FONT}`; g.fillText('QR', 512, 512);
}

/** Logo Din horizontal (símbolo + "Din") centrado en (cx, cy); S = caja del símbolo. */
function drawDinLogo(g, cx, cy, S) {
  g.save();
  g.font = `800 ${S * 1.1}px ${FONT}`;
  const tw = g.measureText('Din').width, symW = S * 88 / 120, gap = S * 22 / 120;
  const x0 = cx - (symW + gap + tw) / 2;
  g.translate(x0 - S * 18 / 120, cy - S / 2); g.scale(S / 120, S / 120);
  g.fillStyle = DIN_INK; g.fill(new Path2D(DIN_D), 'evenodd');
  g.fillStyle = DIN_BRAND; g.beginPath(); g.arc(58, 60, 11, 0, Math.PI * 2); g.fill();
  g.restore(); g.save();
  g.font = `800 ${S * 1.1}px ${FONT}`; g.fillStyle = DIN_INK; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
  g.fillText('Din', x0 + symW + gap, cy + S * 0.4);
  g.restore();
}

/**
 * Tarjeta impresa: arriba la marca Din, "Aceptado aquí", instrucción, hueco del QR
 * y abajo el logo pey | CoDi. Coordenadas en milímetros (L.ppm px por mm).
 */
function drawCard(canvas, L, logoImg) {
  const g = canvas.getContext('2d');
  g.setTransform(L.ppm, 0, 0, L.ppm, 0, 0);
  g.fillStyle = '#ffffff'; g.fillRect(0, 0, L.W, L.H);
  // Marca Din
  drawDinLogo(g, L.W / 2, L.dinY, L.dinS);
  g.textAlign = 'center'; g.textBaseline = 'middle';
  // Aceptado aquí
  g.fillStyle = DIN_INK;
  fitFont(g, 'Aceptado aquí', L.W - 10, L.accSize, 800);
  g.fillText('Aceptado aquí', L.W / 2, L.accY);
  // Instrucción (una o dos líneas)
  g.fillStyle = '#3A4660';
  g.font = `600 ${L.insSize}px ${FONT}`;
  const lines = wrapLines(g, CARD_INSTRUCTION, L.W - 2 * L.pad);
  lines.forEach((ln, i) => g.fillText(ln, L.W / 2, L.insY + i * L.insSize * 1.28));
  // Marco del QR (la textura del QR ya incluye su quiet zone blanca)
  const qx = (L.W - L.qrSize) / 2;
  g.strokeStyle = 'rgba(11,26,51,0.14)'; g.lineWidth = 0.3;
  roundRectPath(g, qx - 0.8, L.qrTop - 0.8, L.qrSize + 1.6, L.qrSize + 1.6, 1.6); g.stroke();
  // Abajo: pey | CoDi
  const lw = L.logoH * LOGO_ASPECT;
  if (logoImg) g.drawImage(logoImg, (L.W - lw) / 2, L.logoTop, lw, L.logoH);
  g.setTransform(1, 0, 0, 1, 0, 0);
}

/**
 * Pantalla LCD del comerciante. Escala todo según la altura del canvas.
 * s = { payment, businessName, volume, volOverlay, time }
 */
function drawScreen(canvas, s, accent) {
  const g = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.textAlign = 'center'; g.textBaseline = 'middle';
  if (s.payment) {
    g.fillStyle = accent; g.fillRect(0, 0, W, H);
    const hl = g.createLinearGradient(0, 0, 0, H);
    hl.addColorStop(0, 'rgba(255,255,255,0.16)'); hl.addColorStop(0.6, 'rgba(255,255,255,0)'); hl.addColorStop(1, 'rgba(0,0,0,0.12)');
    g.fillStyle = hl; g.fillRect(0, 0, W, H);
    const cy = H * 0.25, r = H * 0.12;
    g.fillStyle = '#ffffff';
    g.beginPath(); g.arc(W / 2, cy, r, 0, Math.PI * 2); g.fill();
    g.strokeStyle = accent; g.lineWidth = r * 0.25; g.lineCap = 'round'; g.lineJoin = 'round';
    g.beginPath(); g.moveTo(W / 2 - r * 0.45, cy + r * 0.02); g.lineTo(W / 2 - r * 0.11, cy + r * 0.36); g.lineTo(W / 2 + r * 0.48, cy - r * 0.32); g.stroke();
    g.fillStyle = '#ffffff';
    fitFont(g, s.payment.amountText, W - 40, H * 0.25, 800);
    g.fillText(s.payment.amountText, W / 2, H * 0.545);
    g.font = `600 ${H * 0.1}px ${FONT}`;
    g.fillText('Recibido', W / 2, H * 0.71);
    if (s.payment.label) {
      g.fillStyle = 'rgba(255,255,255,0.8)';
      fitFont(g, s.payment.label, W - 60, H * 0.07, 500);
      g.fillText(s.payment.label, W / 2, H * 0.85);
    }
  } else {
    g.fillStyle = '#0b100e'; g.fillRect(0, 0, W, H);
    const rg = g.createRadialGradient(W / 2, H * 0.45, 10, W / 2, H * 0.45, W * 0.6);
    rg.addColorStop(0, 'rgba(18,148,90,0.20)'); rg.addColorStop(1, 'rgba(18,148,90,0)');
    g.fillStyle = rg; g.fillRect(0, 0, W, H);
    // Barra superior: negocio + señal
    g.textAlign = 'left'; g.fillStyle = '#8f9c95';
    fitFont(g, s.businessName, W * 0.68, H * 0.058, 600);
    g.fillText(s.businessName, W * 0.045, H * 0.09);
    const bw = H * 0.022;
    for (let i = 0; i < 4; i++) {
      g.fillStyle = i < 3 ? '#cfd8d3' : '#46514b';
      const bh = (i + 1) * H * 0.017;
      g.fillRect(W * 0.855 + i * bw * 1.5, H * 0.11 - bh, bw, bh);
    }
    g.textAlign = 'center';
    const now = new Date();
    const hhmm = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    g.fillStyle = '#ffffff';
    g.font = `600 ${H * 0.33}px ${FONT}`;
    g.fillText(hhmm, W / 2, H * 0.43);
    const ok = s.statusOk !== false;
    g.fillStyle = ok ? '#63e3a5' : '#ffb01f';
    fitFont(g, s.statusText || 'Escuchando pagos', W - 40, H * 0.083, 600);
    g.fillText(s.statusText || 'Escuchando pagos', W / 2, H * 0.665);
    for (let i = 0; ok && i < 3; i++) {
      const a = 0.25 + 0.75 * Math.max(0, Math.sin(s.time * 4 - i * 0.7));
      g.fillStyle = `rgba(99,227,165,${a.toFixed(3)})`;
      g.beginPath(); g.arc(W / 2 + (i - 1) * H * 0.067, H * 0.795, H * 0.017, 0, Math.PI * 2); g.fill();
    }
  }
  // Indicador de volumen superpuesto
  if (s.volOverlay > 0) {
    g.globalAlpha = Math.min(1, s.volOverlay / 0.3);
    const ph = H * 0.22, py = H - ph - H * 0.07, k = ph / 76;
    g.fillStyle = 'rgba(0,0,0,0.82)';
    roundRectPath(g, 26, py, W - 52, ph, 16 * k); g.fill();
    g.fillStyle = '#ffffff';
    const sx = 52, sy = py + ph / 2;
    g.beginPath();
    g.moveTo(sx, sy - 8 * k); g.lineTo(sx + 10 * k, sy - 8 * k); g.lineTo(sx + 24 * k, sy - 20 * k); g.lineTo(sx + 24 * k, sy + 20 * k);
    g.lineTo(sx + 10 * k, sy + 8 * k); g.lineTo(sx, sy + 8 * k); g.closePath(); g.fill();
    const x0 = 100, segW = 22, gap = 6;
    for (let i = 0; i < 10; i++) {
      g.fillStyle = i < s.volume ? '#3fe08f' : '#3a3d3c';
      roundRectPath(g, x0 + i * (segW + gap), sy - 14 * k, segW, 28 * k, 5); g.fill();
    }
    g.fillStyle = '#ffffff'; g.font = `700 ${30 * k}px ${FONT}`; g.textAlign = 'center';
    g.fillText(String(s.volume), W - 64, sy + 1);
    g.globalAlpha = 1;
  }
}

/** Brillo del LED de estado según el modo. */
function ledIntensity(state, t) {
  switch (state) {
    case 'off': return 0;
    case 'idle': return 0.35 + 0.45 * (0.5 + 0.5 * Math.sin(t * Math.PI * 2 / 3.2));    // respiración lenta
    case 'talking': return (t * 4) % 1 < 0.55 ? 2.4 : 0.15;                             // parpadeo 4 Hz
    case 'listening': return 0.4 + 2.0 * (0.5 + 0.5 * Math.sin(t * Math.PI * 2 * 1.3)); // pulso rojo
    case 'error': return 1.8;                                                            // ámbar fijo
    default: return 0;
  }
}
function ledColor(state) {
  return state === 'listening' ? LED_COLORS.red : state === 'error' ? LED_COLORS.amber : LED_COLORS.green;
}

const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

// ─── Piezas reutilizables ───

/** Crea un botón físico en `parent` (su local +Y = hacia afuera de la superficie). */
function makeButton(THREE, own, parent, name, x, y, R, mats, isTalk) {
  const holder = new THREE.Group();
  holder.position.set(x, y, 0);
  holder.rotation.x = Math.PI / 2;          // local Y del botón = normal de la cara (Z del padre)
  parent.add(holder);
  const ring = new THREE.Mesh(own(new THREE.RingGeometry(R + 0.0002, R + 0.0013, 40)), mats.ring);
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.00008;
  holder.add(ring);
  const mover = new THREE.Group();
  holder.add(mover);
  const H = 0.0055;
  const cap = new THREE.Mesh(own(buttonCapGeometry(THREE, R, H)), isTalk ? mats.talk : mats.button);
  cap.position.y = -0.0025;                 // 3 mm sobresalen de la carcasa
  cap.castShadow = true;
  mover.add(cap);
  const iconCanvas = makeCanvas(256, 256);
  drawButtonIcon(iconCanvas, name, isTalk ? '#ffffff' : '#d8d5cf');
  const icon = new THREE.Mesh(own(new THREE.CircleGeometry(R * 0.78, 32)),
    own(new THREE.MeshStandardMaterial({ map: own(canvasTexture(THREE, iconCanvas)), transparent: true, roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2 })));
  icon.rotation.x = -Math.PI / 2;
  icon.position.y = cap.position.y + H + 0.00003;
  mover.add(icon);
  cap.userData.button = name; icon.userData.button = name;
  return { mover, t: 0, pressing: false, meshes: [cap, icon] };
}

/** Rejilla: placa + perforaciones en patrón hexagonal (InstancedMesh). */
function makeGrille(THREE, own, parent, x0, x1, y0, y1, mats, radius = 0.005, plate = true) {
  if (plate) {
    const p = new THREE.Mesh(own(new THREE.ShapeGeometry(roundedRectShape(THREE, x1 - x0, y1 - y0, radius, (x0 + x1) / 2, (y0 + y1) / 2), 6)), mats.grille);
    p.position.z = 0.00012;
    parent.add(p);
  }
  const r = 0.00092, sx = 0.0036, sy = sx * 0.866, pts = [];
  for (let row = 0, y = y0 + 0.0024; y <= y1 - 0.0022; row++, y += sy) {
    for (let x = x0 + 0.0026 + (row % 2) * sx / 2; x <= x1 - 0.0024; x += sx) pts.push([x, y]);
  }
  const holes = new THREE.InstancedMesh(own(new THREE.CircleGeometry(r, 12)), mats.hole, pts.length);
  const m4 = new THREE.Matrix4();
  pts.forEach(([x, y], i) => holes.setMatrixAt(i, m4.makeTranslation(x, y, 0.00026)));
  parent.add(holes);
  return holes;
}

/** Pantalla LCD con bisel brillante sobre una cara (local Z = normal). */
function makeScreen(THREE, own, parent, cx, cy, sw, sh, px, mats) {
  const bezel = new THREE.Mesh(own(roundedBox(THREE, sw + 0.008, sh + 0.008, 0.0014, 0.003, 0.0005, 6, 2)), mats.bezel);
  bezel.position.set(cx, cy, 0.0005);
  parent.add(bezel);
  const canvas = makeCanvas(px, Math.round(px * sh / sw));
  const tex = own(canvasTexture(THREE, canvas));
  const screen = new THREE.Mesh(own(new THREE.PlaneGeometry(sw, sh)),
    own(new THREE.MeshBasicMaterial({ map: tex, toneMapped: false, color: new THREE.Color(0.92, 0.92, 0.92) })));
  screen.position.set(cx, cy, 0.00125);
  parent.add(screen);
  return { canvas, tex };
}

/** LED de estado (domo + aro + halo) sobre una cara (local Z = normal). */
function makeLed(THREE, own, parent, x, y, glowTex, mats) {
  const ledMat = own(new THREE.MeshStandardMaterial({ color: '#101211', roughness: 0.25, emissive: new THREE.Color(LED_COLORS.green), emissiveIntensity: 0 }));
  const led = new THREE.Mesh(own(new THREE.SphereGeometry(0.0021, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2)), ledMat);
  led.rotation.x = Math.PI / 2; led.scale.y = 0.55;
  led.position.set(x, y, 0);
  parent.add(led);
  const ring = new THREE.Mesh(own(new THREE.RingGeometry(0.0021, 0.003, 24)), mats.ring);
  ring.position.set(x, y, 0.00008);
  parent.add(ring);
  const haloMat = own(new THREE.MeshBasicMaterial({ map: glowTex, color: LED_COLORS.green, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
  const halo = new THREE.Mesh(own(new THREE.PlaneGeometry(0.015, 0.015)), haloMat);
  halo.position.set(x, y, 0.0012);
  halo.raycast = () => {};
  parent.add(halo);
  return { ledMat, haloMat };
}

/** Materiales comunes. */
function makeMaterials(THREE, own, accent) {
  return {
    body: own(new THREE.MeshPhysicalMaterial({ color: COLOR_BODY, roughness: 0.62, clearcoat: 0.12, clearcoatRoughness: 0.55 })),
    light: own(new THREE.MeshPhysicalMaterial({ color: COLOR_LIGHT, roughness: 0.55, clearcoat: 0.18, clearcoatRoughness: 0.5 })),
    accent: own(new THREE.MeshPhysicalMaterial({ color: accent, roughness: 0.6 })),
    trim: own(new THREE.MeshPhysicalMaterial({ color: '#0d0c0f', roughness: 0.8 })),
    grille: own(new THREE.MeshPhysicalMaterial({ color: '#232227', roughness: 0.42, metalness: 0.35 })),
    hole: own(new THREE.MeshBasicMaterial({ color: '#040405' })),
    bezel: own(new THREE.MeshPhysicalMaterial({ color: '#050506', roughness: 0.14, clearcoat: 1, clearcoatRoughness: 0.08 })),
    button: own(new THREE.MeshPhysicalMaterial({ color: '#2b2a30', roughness: 0.55, clearcoat: 0.2, clearcoatRoughness: 0.5 })),
    talk: own(new THREE.MeshPhysicalMaterial({ color: accent, roughness: 0.48, clearcoat: 0.25, clearcoatRoughness: 0.45 })),
    ring: own(new THREE.MeshBasicMaterial({ color: '#070708' })),
  };
}

/**
 * Tarjeta del QR: plano impreso (redondeado) + plano del QR encima, sin luz
 * ni reflejos. Devuelve { qrMesh, qrSize, redraw, setLogo }.
 */
function makeQRCard(THREE, own, parent, L, cx, cy, z, cornerMm = 5) {
  const cardCanvas = makeCanvas(L.W * L.ppm, L.H * L.ppm);
  const cardTex = own(canvasTexture(THREE, cardCanvas));
  const face = new THREE.Mesh(own(roundedPlane(THREE, L.W / 1000, L.H / 1000, cornerMm / 1000)),
    own(new THREE.MeshStandardMaterial({ map: cardTex, roughness: 0.85 })));
  face.position.set(cx, cy, z);
  parent.add(face);
  const qrCanvas = makeCanvas(1024, 1024);
  drawQRPlaceholder(qrCanvas);
  const qrTex = own(canvasTexture(THREE, qrCanvas, true));
  const qrSize = L.qrSize / 1000;
  const qrMesh = new THREE.Mesh(own(new THREE.PlaneGeometry(qrSize, qrSize)),
    own(new THREE.MeshBasicMaterial({ map: qrTex, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 })));
  qrMesh.name = 'qr';
  qrMesh.position.set(cx, cy + (L.H / 2 - (L.qrTop + L.qrSize / 2)) / 1000, z + 0.00015);
  parent.add(qrMesh);
  let logo = null;
  const redraw = () => { drawCard(cardCanvas, L, logo); cardTex.needsUpdate = true; };
  redraw();
  // La tipografía de marca llega de Google Fonts: se vuelve a pintar cuando carga
  document.fonts?.load(`800 40px ${FONT}`).then(redraw).catch(() => {});
  return {
    qrMesh, qrSize, qrCanvas, qrTex, redraw,
    setLogo(img) { logo = img; redraw(); },
  };
}

/** Plano con el logo sobre fondo transparente (para superficies del cuerpo). */
function makeLogoPlane(THREE, own, widthM) {
  const c = makeCanvas(1024, Math.round(1024 / LOGO_ASPECT));
  const tex = own(canvasTexture(THREE, c));
  const mesh = new THREE.Mesh(own(new THREE.PlaneGeometry(widthM, widthM / LOGO_ASPECT)),
    own(new THREE.MeshStandardMaterial({ map: tex, transparent: true, roughness: 0.6, polygonOffset: true, polygonOffsetFactor: -2 })));
  mesh.raycast = () => {};
  return {
    mesh,
    setImage(img) { const g = c.getContext('2d'); g.clearRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height); tex.needsUpdate = true; },
  };
}

/**
 * Lógica del aparato: estado, temporizadores, LED, pantalla,
 * botones, interacción con raycaster, focusQR y dispose.
 * parts = { group, owned, opts, card, buttons(Map), led, screen, onUpdate(state, dt) }
 */
function createCore(THREE, parts) {
  const { group, owned, opts, card, buttons, led, screen } = parts;
  const state = {
    time: 0, led: 'idle', ledTimer: 0,
    payment: null, paymentTimer: 0, paymentAge: 0,
    volume: 6, volOverlay: 0,
    businessName: opts.businessName,
    statusText: 'Escuchando pagos', statusOk: true,
    screenDirty: true, screenClock: 0,
    focus: null,
  };
  const listeners = new Set();
  const interactionOffs = new Set();
  const pickables = [];
  for (const b of buttons.values()) pickables.push(...b.meshes);

  function redrawScreen() {
    if (!screen) return;
    drawScreen(screen.canvas, state, opts.accent);
    screen.tex.needsUpdate = true;
    state.screenDirty = false;
  }

  async function setQR(svgOrCanvas) {
    await renderQRInto(card.qrCanvas, svgOrCanvas);
    card.qrTex.dispose();          // el canvas pudo cambiar de tamaño: recrear en GPU
    card.qrTex.image = card.qrCanvas;
    card.qrTex.needsUpdate = true;
  }

  /** El nombre del negocio solo aparece en la pantalla del comerciante (no en la tarjeta). */
  function setBusinessName(text) {
    state.businessName = String(text ?? '').trim() || ' ';
    state.screenDirty = true;
  }

  function setLed(s) {
    if (!LED_STATES.includes(s)) { console.warn(`[soundbox] estado de LED desconocido: ${s}`); return; }
    state.led = s; state.ledTimer = 0;
  }

  function showPayment({ amount, label } = {}) {
    state.payment = { amountText: formatAmount(amount), label: label ? String(label) : '' };
    state.paymentTimer = opts.paymentHoldSeconds;
    state.paymentAge = 0;
    state.led = 'talking';
    state.ledTimer = opts.talkSeconds;
    state.screenDirty = true;
  }

  /** Estado real de la bocina (conexión y configuración) en la pantalla del comerciante. */
  function setStatus({ text, ok } = {}) {
    state.statusText = String(text || 'Escuchando pagos');
    state.statusOk = ok !== false;
    state.screenDirty = true;
  }

  function setIdle() {
    state.payment = null; state.paymentTimer = 0;
    state.led = 'idle'; state.ledTimer = 0;
    state.screenDirty = true;
  }

  function setVolume(level) {
    state.volume = Math.max(0, Math.min(10, Math.round(Number(level) || 0)));
    state.volOverlay = 2;
    state.screenDirty = true;
  }

  function onButton(cb) {
    listeners.add(cb);
    return () => listeners.delete(cb);
  }

  /** Simula la pulsación (animación + callback). También la usa el raycaster. */
  function pressButton(name) {
    const b = buttons.get(name);
    if (!b) return;
    b.t = 0; b.pressing = true;
    for (const cb of listeners) { try { cb(name); } catch (e) { console.error(e); } }
  }

  /** Clic/tap y cursor "pointer" sobre los botones (fase de captura: OrbitControls no rota). */
  function enableInteraction(domElement, camera) {
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    let hovering = false;
    const pick = (e) => {
      const r = domElement.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      const hit = ray.intersectObject(group, true)[0];   // respeta oclusión
      return hit && hit.object.userData.button ? hit.object.userData.button : null;
    };
    const onMove = (e) => {
      const name = pick(e);
      if (!!name !== hovering) { hovering = !!name; domElement.style.cursor = hovering ? 'pointer' : ''; }
    };
    const onDown = (e) => {
      const name = pick(e);
      if (!name) return;
      e.stopImmediatePropagation();
      e.preventDefault();
      pressButton(name);
    };
    domElement.addEventListener('pointermove', onMove);
    domElement.addEventListener('pointerdown', onDown, { capture: true });
    const off = () => {
      domElement.removeEventListener('pointermove', onMove);
      domElement.removeEventListener('pointerdown', onDown, { capture: true });
      if (hovering) domElement.style.cursor = '';
    };
    interactionOffs.add(off);
    return off;
  }

  /**
   * Anima la cámara hasta dejar el QR de frente, perpendicular y grande.
   * opciones: { duration = 0.9 s, fill = 0.62 (fracción del lado menor de la vista) }
   */
  function focusQR(camera, controls, { duration = 0.9, fill = 0.62 } = {}) {
    group.updateWorldMatrix(true, true);
    const qrMesh = card.qrMesh;
    const center = qrMesh.getWorldPosition(new THREE.Vector3());
    const normal = new THREE.Vector3(0, 0, 1).transformDirection(qrMesh.matrixWorld);
    const worldScale = new THREE.Vector3().setFromMatrixScale(qrMesh.matrixWorld).x;
    const size = card.qrSize * worldScale;
    const vfov = THREE.MathUtils.degToRad(camera.fov);
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    let dist = Math.max((size / fill) / 2 / Math.tan(vfov / 2), (size / fill) / 2 / Math.tan(hfov / 2));
    if (controls) dist = THREE.MathUtils.clamp(dist, controls.minDistance ?? 0, controls.maxDistance ?? Infinity);
    const startTarget = controls ? controls.target.clone() : center.clone();
    if (state.focus) state.focus.resolve();
    if (controls) { controls.autoRotate = false; controls.enabled = false; }
    return new Promise((resolve) => {
      state.focus = {
        t: 0, duration: Math.max(0.01, duration), camera, controls,
        startTarget, endTarget: center,
        startOffset: camera.position.clone().sub(startTarget),
        endOffset: normal.multiplyScalar(dist),
        resolve,
      };
    });
  }

  const _q = new THREE.Quaternion(), _qi = new THREE.Quaternion(), _d0 = new THREE.Vector3(), _d1 = new THREE.Vector3(), _tg = new THREE.Vector3();

  function update(dt) {
    dt = Math.min(Math.max(dt || 0, 0), 0.1);
    state.time += dt;
    const t = state.time;

    // Botones: bajan rápido y regresan suave
    for (const b of buttons.values()) {
      if (!b.pressing) continue;
      b.t += dt;
      let k;
      if (b.t < PRESS_DOWN) k = easeInOut(b.t / PRESS_DOWN);
      else if (b.t < PRESS_DOWN + PRESS_UP) k = 1 - easeInOut((b.t - PRESS_DOWN) / PRESS_UP);
      else { k = 0; b.pressing = false; }
      b.mover.position.y = -PRESS_DEPTH * k;
    }

    // Temporizadores de pago
    if (state.ledTimer > 0) {
      state.ledTimer -= dt;
      if (state.ledTimer <= 0 && state.led === 'talking') state.led = 'idle';
    }
    if (state.payment) {
      state.paymentAge += dt;
      if (state.paymentTimer > 0) {
        state.paymentTimer -= dt;
        if (state.paymentTimer <= 0) setIdle();
      }
    }

    // LED de estado
    const li = ledIntensity(state.led, t), lc = ledColor(state.led);
    led.ledMat.emissive.set(lc); led.ledMat.emissiveIntensity = li;
    led.haloMat.color.set(lc); led.haloMat.opacity = Math.min(1, li * 0.32);

    // Pantalla: ~8 fps en reposo (hora y puntos animados) o cuando cambia algo
    if (state.volOverlay > 0) { state.volOverlay = Math.max(0, state.volOverlay - dt); state.screenDirty = true; }
    state.screenClock += dt;
    if (state.screenDirty || (!state.payment && state.screenClock > 0.125)) {
      state.screenClock = 0;
      redrawScreen();
    }

    if (parts.onUpdate) parts.onUpdate(state, dt);

    // Cámara (focusQR): dirección por interpolación esférica, distancia lineal
    const f = state.focus;
    if (f) {
      f.t += dt;
      const k = easeInOut(Math.min(1, f.t / f.duration));
      _tg.lerpVectors(f.startTarget, f.endTarget, k);
      _d0.copy(f.startOffset).normalize(); _d1.copy(f.endOffset).normalize();
      _q.setFromUnitVectors(_d0, _d1); _qi.identity().slerp(_q, k);
      const len = THREE.MathUtils.lerp(f.startOffset.length(), f.endOffset.length(), k);
      f.camera.position.copy(_tg).add(_d0.applyQuaternion(_qi).multiplyScalar(len));
      f.camera.lookAt(_tg);
      if (f.controls) f.controls.target.copy(_tg);
      if (k >= 1) {
        state.focus = null;
        if (f.controls) { f.controls.enabled = true; f.controls.update(); }
        f.resolve();
      }
    }
  }

  function dispose() {
    for (const off of interactionOffs) off();
    interactionOffs.clear();
    listeners.clear();
    group.removeFromParent();
    for (const x of owned) x.dispose?.();
    owned.clear();
  }

  if (opts.qr) setQR(opts.qr).catch((e) => console.error(e));
  setIdle();
  redrawScreen();

  return {
    group,
    setQR, setBusinessName, showPayment, setIdle, setLed, setVolume, setStatus,
    focusQR, onButton, update, dispose,
    // Extras útiles para la demo
    enableInteraction, pressButton,
    get qrMesh() { return card.qrMesh; },
    get buttonMeshes() { return pickables.slice(); },
    get state() { return { led: state.led, payment: !!state.payment, volume: state.volume, businessName: state.businessName }; },
  };
}

/** Opciones por defecto + carga de logos (claro para la tarjeta, inverso para el cuerpo). */
function resolveOptions(options) {
  return {
    qr: null,
    businessName: 'Mi negocio',      // se muestra en la pantalla del comerciante
    accent: '#12945a',               // botón de hablar, pantalla de pago, luces
    cardAccent: '#154781',           // banda de color de la tarjeta (azul Din)
    logoSvg: LOGO_SVG_LIGHT,         // logo de la tarjeta (fondo claro)
    logoSvgDark: LOGO_SVG_DARK,      // logo sobre el plástico oscuro
    paymentHoldSeconds: 8,           // tras showPayment vuelve solo a reposo; 0 = manual con setIdle()
    talkSeconds: 2.8,                // tiempo que el LED parpadea "hablando"
    ...options,
  };
}

// ═════════════════════════════════════════════════════════════════════════
// Variante B — display (referencia: soundbox de cuerpo curvo)
//
//   · Cuerpo redondeado en todas sus aristas, perfil trapezoidal: la cara
//     frontal se inclina 10° hacia atrás y el techo se curva hacia la espalda.
//   · Al frente: bisel claro y delgado con banda azul abajo y la tarjeta del QR.
//   · Atrás (lado del comerciante): pantalla LCD, LED y 4 botones.
//   · Costados: perforaciones de la bocina.
// ═════════════════════════════════════════════════════════════════════════

export function createSoundbox(THREE, options = {}) {
  const opts = resolveOptions(options);
  const group = new THREE.Group();
  group.name = 'Soundbox (display)';
  const owned = new Set();
  const own = (x) => { owned.add(x); return x; };
  const M = makeMaterials(THREE, own, opts.accent);
  const V = THREE.Vector2;
  const glowTex = own(canvasTexture(THREE, glowCanvas()));

  // ── Cuerpo: perfil lateral (z, y) con radios generosos ──
  const BW = 0.110, BH = 0.105, BEV = 0.011;
  const BB = new V(-0.045, 0);
  const FB = new V(0.035, 0);
  const FT = new V(0.035 - BH * Math.tan(10 * DEG), BH);
  const BT = new V(-0.045 + BH * Math.tan(5 * DEG), BH);
  const body = new THREE.Mesh(own(profileSolid(THREE, [BB, FB, FT, BT], BW, [0.005, 0.004, 0.012, 0.016], BEV, 6, 12)), M.body);
  body.castShadow = true; body.receiveShadow = true;
  group.add(body);

  // ── Frente: bisel claro + banda de color + tarjeta del QR ──
  const front = faceFrame(THREE, FB, FT, 'front');
  group.add(front);
  const LF = FB.distanceTo(FT);
  const CAP_T = 0.0065;   // bisel blanco delgado (6.5 mm)
  const cap = new THREE.Mesh(own(roundedBox(THREE, 0.114, 0.104, CAP_T, 0.018, 0.0025, 10, 4)), M.light);
  cap.position.set(0, LF / 2, CAP_T / 2);
  // No recibe sombras: en un bisel tan delgado aparecen marquitas ("shadow acne")
  cap.castShadow = true; cap.receiveShadow = false;
  front.add(cap);
  const bandMat = own(new THREE.MeshPhysicalMaterial({ color: opts.cardAccent, roughness: 0.6 }));
  const band = new THREE.Mesh(own(roundedPlane(THREE, 0.104, 0.046, 0.012)), bandMat);
  band.position.set(0, LF / 2 - 0.052 + 0.005 + 0.023, CAP_T + 0.00008);
  front.add(band);
  const L = {
    W: 94, H: 82, ppm: 10, pad: 3,
    dinY: 7.5, dinS: 8,          // arriba: marca Din
    accY: 16.2, accSize: 3.6,
    insY: 20.6, insSize: 2.7,
    qrTop: 24, qrSize: 46,
    logoTop: 72.5, logoH: 6.5,   // abajo: pey | CoDi
  };
  const card = makeQRCard(THREE, own, front, L, 0, LF / 2 + 0.004, CAP_T + 0.00018, 5);

  // ── Espalda: pantalla, LED y botones ──
  const back = faceFrame(THREE, BB, BT, 'back');
  group.add(back);
  // Versión básica: sin pantalla. El estado se comunica con el LED y la voz.
  const screen = null;
  // 3 botones (vol −, vol +, último pago) y el LED en la cuarta posición, alineado con ellos
  const buttons = new Map();
  [['vol-', -0.027, 0.0055], ['vol+', -0.009, 0.0055], ['last', 0.009, 0.0055]]
    .forEach(([name, x, R]) => buttons.set(name, makeButton(THREE, own, back, name, x, 0.024, R, M, false)));
  const led = makeLed(THREE, own, back, 0.027, 0.024, glowTex, M);

  // ── Costados: perforaciones circulares de la bocina ──
  const grillePivots = [];
  {
    const zc = -0.0072, yc = 0.050, rad = 0.019;
    const pts = [];
    const sx = 0.0034, sy = sx * 0.866;
    for (let row = -8; row <= 8; row++) {
      for (let col = -8; col <= 8; col++) {
        const u = col * sx + (row & 1) * sx / 2, v = row * sy;
        if (Math.hypot(u, v) <= rad) pts.push([u, v]);
      }
    }
    const holeGeo = own(new THREE.CircleGeometry(0.00085, 10));
    for (const side of [-1, 1]) {
      const g = new THREE.Group();
      g.position.x = side * (BW / 2 + 0.0001);
      g.rotation.y = side * Math.PI / 2;      // local Z → ±X (hacia afuera)
      group.add(g);
      // Pivote en el centro de la rejilla: al escalarlo, las perforaciones "laten" sin desplazarse
      const pivot = new THREE.Group();
      pivot.position.set(-side * zc, yc, 0);  // en este marco local, X apunta a −Z (lado +) o +Z (lado −)
      g.add(pivot);
      grillePivots.push(pivot);
      const holes = new THREE.InstancedMesh(holeGeo, M.hole, pts.length);
      const m4 = new THREE.Matrix4();
      pts.forEach(([u, v], i) => holes.setMatrixAt(i, m4.makeTranslation(u, v, 0)));
      pivot.add(holes);
    }
  }

  // Sombra de contacto
  const shadow = new THREE.Mesh(own(new THREE.PlaneGeometry(0.18, 0.15)),
    own(new THREE.MeshBasicMaterial({ map: own(canvasTexture(THREE, contactShadowCanvas())), transparent: true, depthWrite: false, toneMapped: false })));
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.set(0, 0.0004, -0.003);
  shadow.renderOrder = -1;
  shadow.raycast = () => {};
  group.add(shadow);

  loadSvgImage(opts.logoSvg).then((img) => card.setLogo(img)).catch((e) => console.warn('[soundbox]', e.message));

  // Animación de sonido: la rejilla late mientras habla y el aparato da un saltito al llegar un pago
  const fx = { speaking: false, level: 0, phase: 0, bumpT: -1 };
  const baseY = group.position.y, shadowY = shadow.position.y;
  function onUpdate(state, dt) {
    fx.level += ((fx.speaking ? 1 : 0) - fx.level) * Math.min(1, dt * 10);   // entra y sale suave
    fx.phase += dt;
    const beat = fx.level * (0.5 + 0.5 * Math.sin(fx.phase * Math.PI * 2 * 5.5)) * (0.75 + 0.25 * Math.sin(fx.phase * 13.1));
    const k = 1 + 0.06 * beat;
    for (const p of grillePivots) { p.scale.set(k, k, 1); p.position.z = 0.0003 * beat; }
    let hop = 0;
    if (fx.bumpT >= 0) {
      fx.bumpT += dt;
      const t = fx.bumpT;
      if (t < 0.16) hop = 0.0018 * Math.sin(Math.PI * t / 0.16);                 // salto
      else if (t < 0.28) hop = 0.0005 * Math.sin(Math.PI * (t - 0.16) / 0.12);  // rebote pequeño
      else fx.bumpT = -1;
    }
    group.position.y = baseY + hop;
    shadow.position.y = shadowY - hop;   // la sombra se queda en el piso
  }

  const core = createCore(THREE, { group, owned, opts, card, buttons, led, screen, onUpdate });
  /** true mientras la voz está sonando (la rejilla late). */
  core.setSpeaking = (on) => { fx.speaking = !!on; };
  /** Saltito único del aparato (al llegar un pago). */
  core.bump = () => { fx.bumpT = 0; };
  return core;
}
