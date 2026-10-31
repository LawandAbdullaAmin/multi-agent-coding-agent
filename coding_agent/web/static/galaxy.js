// Galaxie-Szene (WebGL, Three.js) für das Agenten-Team.
//
// Der Supervisor ist ein strahlender Kern im Zentrum einer Spiralgalaxie, die fünf Fach-Agenten kreisen als
// Energiekugeln um ihn. Erteilt der Supervisor einen Auftrag, schießt ein Energiestrahl zum Agenten und hält
// die Verbindung, solange dieser arbeitet. Der Bericht fliegt als Lichtblitz zurück.
//
// Bewusst leichtgewichtig: keine Nachbearbeitung (Bloom) und kein Raymarching. Das Leuchten entsteht
// durch additive Shader, so läuft die Szene auch auf schwacher Grafik flüssig.
//
// Ein einziger Canvas liegt hinter der ganzen Seite. Das System wird mit einer verschobenen Kamera
// genau unter ein HTML-Element gelegt (Startseite: Vorschau, Laufansicht: Bühne).

import * as THREE from "three";

export const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const AGENTS = {
  explorer: { name: "Explorer", role: "Analysiert den Code", color: "#5fd4f0", icon: "search", kind: 0 },
  test_writer: { name: "Test-Autor", role: "Schreibt Tests aus der Anforderung", color: "#ffb45e", icon: "flask", kind: 1 },
  developer: { name: "Entwickler", role: "Setzt die Lösung um", color: "#ff6f9a", icon: "code", kind: 2 },
  tester: { name: "Tester", role: "Führt alle Tests aus", color: "#62e09a", icon: "play", kind: 3 },
  reviewer: { name: "Reviewer", role: "Prüft gegen die Anforderung", color: "#9b8cff", icon: "shield", kind: 4 },
};
export const SUPERVISOR = { name: "Supervisor", role: "Steuert das Team", color: "#ffb36b", icon: "compass" };

const TAU = Math.PI * 2;
const ORBIT = 10;            // Bahnradius der Agenten
const ORB_SIZE = 0.85;       // Radius einer Agenten-Kugel
const ELEVATION = 0.42;      // Blickwinkel über der Galaxieebene (rad)
const FOV = 32;
const GOLD = new THREE.Color("#ffc27a");
const ALARM = new THREE.Color("#ff4d4d");

// ---- GLSL ------------------------------------------------------------------------------------

const NOISE_1D = /* glsl */ `
  float hash(float n) { return fract(sin(n) * 43758.5453); }
  // Wertrauschen mit Periode, damit es um einen Kreis herum nahtlos ist
  float noiseP(float x, float period) {
    float i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(hash(mod(i, period)), hash(mod(i + 1.0, period)), f);
  }`;

const QUAD_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

// Kern des Supervisors: weißglühende Mitte, Korona und flackernde Strahlen
const CORE_FRAGMENT = /* glsl */ `
  uniform float uTime, uEnergy, uAlarm;
  uniform vec3 uWarm, uAlarmColor;
  varying vec2 vUv;
  ${NOISE_1D}
  void main() {
    vec2 p = (vUv - 0.5) * 16.0;            // Fläche ist 16 Einheiten groß
    float r = length(p);
    float angle = atan(p.y, p.x) / 6.28318 + 0.5;
    vec3 warm = mix(uWarm, uAlarmColor, uAlarm);
    float pulse = 1.0 + 0.06 * sin(uTime * 2.2) + 0.25 * uEnergy;

    float core = smoothstep(0.9 * pulse, 0.78 * pulse, r) + smoothstep(1.3, 0.0, r) * 0.35;
    float halo = 1.0 / (1.0 + r * r * 1.6);
    float corona = exp(-r * 0.9) * 0.9;
    float rays = noiseP(angle * 32.0 + uTime * 0.25, 32.0) * noiseP(angle * 19.0 - uTime * 0.18 + 7.0, 19.0);
    rays = pow(rays, 2.5) * 2.2 / (1.0 + r * 0.9);
    float fade = smoothstep(8.0, 3.0, r);

    vec3 color = vec3(1.0, 0.97, 0.92) * core * 2.2
               + warm * (halo * 1.4 + corona + rays * (0.7 + uEnergy * 0.9)) * (0.85 + uEnergy * 0.5);
    gl_FragColor = vec4(color * fade, 1.0);
  }`;

// Plasmawirbel um den Kern, in der Galaxieebene
const SWIRL_FRAGMENT = /* glsl */ `
  uniform float uTime, uEnergy, uAlarm;
  uniform vec3 uWarm, uAlarmColor;
  varying vec2 vUv;
  ${NOISE_1D}
  void main() {
    vec2 p = (vUv - 0.5) * 9.0;
    float r = length(p);
    float angle = atan(p.y, p.x) / 6.28318 + 0.5;
    float band = exp(-pow((r - 2.1) / 0.55, 2.0)) + 0.5 * exp(-pow((r - 3.3) / 0.35, 2.0));
    float streaks = noiseP(angle * 48.0 + r * 6.0 - uTime * 2.4 / r, 48.0);
    streaks = 0.35 + 0.65 * pow(streaks, 2.0);
    vec3 warm = mix(uWarm, uAlarmColor, uAlarm);
    gl_FragColor = vec4(warm * band * streaks * (0.45 + uEnergy * 0.7) * smoothstep(1.0, 1.6, r), 1.0);
  }`;

// Ring in der Ebene: Schockwelle (wachsend) oder gestrichelter Markierungsring unter einem Agenten
const RING_FRAGMENT = /* glsl */ `
  uniform float uTime, uRadius, uWidth, uAlpha, uDash;
  uniform vec3 uColor;
  varying vec2 vUv;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    float r = length(p);
    float band = exp(-pow((r - uRadius) / uWidth, 2.0));
    float angle = atan(p.y, p.x) / 6.28318;
    float dash = mix(1.0, smoothstep(0.35, 0.5, abs(fract(angle * 36.0 + uTime * 0.4) - 0.5) * 2.0), uDash);
    gl_FragColor = vec4(uColor * band * dash * uAlpha, 1.0);
  }`;

// Energiestrahl: Band entlang einer Bézierkurve, das sich immer zur Kamera dreht
const BEAM_VERTEX = /* glsl */ `
  uniform vec3 uA, uB, uC;
  uniform float uWidth;
  attribute float aU, aSide;
  varying float vU, vSide;
  vec3 bezier(float t) { float s = 1.0 - t; return s * s * uA + 2.0 * s * t * uB + t * t * uC; }
  void main() {
    vec4 p = modelViewMatrix * vec4(bezier(aU), 1.0);
    vec3 ahead = (modelViewMatrix * vec4(bezier(min(aU + 0.01, 1.0)), 1.0)).xyz;
    vec3 behind = (modelViewMatrix * vec4(bezier(max(aU - 0.01, 0.0)), 1.0)).xyz;
    vec3 side = normalize(cross(normalize(ahead - behind), normalize(-p.xyz)));
    p.xyz += side * aSide * uWidth * (1.0 - 0.35 * aU);
    gl_Position = projectionMatrix * p;
    vU = aU;
    vSide = aSide;
  }`;

const BEAM_FRAGMENT = /* glsl */ `
  uniform float uTime, uReach, uPower, uSeed;
  uniform vec3 uColorA, uColorB;
  varying float vU, vSide;
  ${NOISE_1D}
  void main() {
    float u = vU, d = abs(vSide);
    if (u > uReach + 0.06) discard;
    float head = smoothstep(uReach + 0.02, uReach - 0.03, u);
    float flicker = 0.7 + 0.3 * noiseP(u * 30.0 - uTime * 24.0 + uSeed, 997.0);

    float core = exp(-d * d * 140.0) * flicker;                   // weißglühender Kern
    float glow = exp(-d * 4.0) * 0.5;                             // weiter Schein
    float phase = u * 42.0 - uTime * 11.0 + uSeed;                // zwei umeinander gewundene Fäden
    float strands = exp(-pow((vSide - 0.34 * sin(phase)) * 10.0, 2.0))
                  + exp(-pow((vSide - 0.34 * sin(phase + 3.14159)) * 10.0, 2.0));
    float pulse = pow(0.5 + 0.5 * sin(u * 24.0 - uTime * 16.0), 10.0);  // Energiepakete zum Ziel

    vec3 color = mix(uColorA, uColorB, smoothstep(0.05, 0.9, u));
    vec3 c = vec3(1.0, 0.98, 0.95) * core * (1.3 + pulse * 1.5)
           + color * (glow * (0.8 + pulse) + strands * (0.5 + 0.4 * pulse));
    // Gleißende Spitze, solange der Strahl noch wächst
    float tip = exp(-pow((u - uReach) * 30.0, 2.0)) * (1.0 - step(0.999, uReach));
    c += (vec3(1.0) * exp(-d * d * 25.0) + color * exp(-d * 2.5)) * tip * 2.0;
    gl_FragColor = vec4(c * head * smoothstep(0.0, 0.06, u) * uPower, 1.0);
  }`;

// Agent als Energiekugel: farbiger Rand, bewegte Bänder, beleuchtet vom Supervisor
const ORB_VERTEX = /* glsl */ `
  varying vec3 vNormal, vView, vWorldNormal, vWorld, vLocal;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vec4 view = viewMatrix * world;
    vNormal = normalize(normalMatrix * normal);
    vView = -view.xyz;
    vWorldNormal = normalize(mat3(modelMatrix) * normal);
    vWorld = world.xyz;
    vLocal = position;
    gl_Position = projectionMatrix * view;
  }`;

// 3D-Simplex-Rauschen (Ashima Arts, MIT) für die Planetenoberflächen
const SIMPLEX = /* glsl */ `
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
  vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
  float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0)) + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    vec3 ns = 0.142857142857 * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x), p1 = vec3(a0.zw, h.y), p2 = vec3(a1.xy, h.z), p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
  }
  float fbm(vec3 p) {
    float sum = 0.0, amp = 0.5;
    for (int i = 0; i < 4; i++) { sum += amp * snoise(p); p *= 2.03; amp *= 0.5; }
    return sum;
  }`;

// Jeder Agent ist eine eigene Welt, beleuchtet vom Kern: Tag- und Nachtseite, Atmosphärensaum
const ORB_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform float uTime, uGlow, uFlash, uKind;
  varying vec3 vNormal, vView, vWorldNormal, vWorld, vLocal;
  ${SIMPLEX}
  void main() {
    vec3 n = normalize(vLocal);
    float spin = uTime * 0.12;
    vec3 p = vec3(n.x * cos(spin) - n.z * sin(spin), n.y, n.x * sin(spin) + n.z * cos(spin));
    vec3 albedo, emissive = vec3(0.0);
    float clouds = 0.0, wet = 0.0, nightOnly = 0.0;

    if (uKind < 0.5) {            // Explorer: Ozean- und Eiswelt
      float h = fbm(p * 2.2);
      vec3 ocean = mix(vec3(0.01, 0.07, 0.2), vec3(0.04, 0.33, 0.55), smoothstep(-0.4, 0.05, h));
      vec3 land = mix(vec3(0.62, 0.74, 0.8), vec3(0.95, 0.98, 1.0), smoothstep(0.1, 0.5, h));
      albedo = mix(ocean, land, smoothstep(0.05, 0.12, h));
      albedo = mix(albedo, vec3(0.95, 0.98, 1.0), smoothstep(0.62, 0.8, abs(n.y) + h * 0.15));
      wet = 1.0 - smoothstep(0.03, 0.08, h);
      clouds = smoothstep(0.1, 0.6, fbm(p * 3.0 + vec3(uTime * 0.05, 0.0, 0.0)));
    } else if (uKind < 1.5) {     // Test-Autor: Gasriese mit Sturmauge
      float w = fbm(p * vec3(2.0, 6.0, 2.0) + vec3(uTime * 0.03, 0.0, 0.0));
      albedo = mix(vec3(0.5, 0.22, 0.07), vec3(1.0, 0.84, 0.58), 0.5 + 0.5 * sin(n.y * 16.0 + w * 3.0));
      albedo = mix(albedo, vec3(0.92, 0.52, 0.2), smoothstep(0.3, 0.6, w));
      float storm = smoothstep(0.3, 0.0, length(vec2(atan(p.z, p.x) - 1.0, (n.y + 0.3) * 2.5)) + w * 0.1);
      albedo = mix(albedo, vec3(0.75, 0.25, 0.1), storm * 0.85);
    } else if (uKind < 2.5) {     // Entwickler: Lavaplanet mit glühenden Rissen
      float h = fbm(p * 2.5);
      float cracks = pow(1.0 - abs(snoise(p * 1.8 + h * 0.6)), 7.0) * smoothstep(0.35, -0.1, h);
      albedo = mix(vec3(0.05, 0.03, 0.04), vec3(0.2, 0.11, 0.1), smoothstep(-0.3, 0.4, h));
      emissive = mix(vec3(1.0, 0.2, 0.35), vec3(1.0, 0.75, 0.4), cracks) * cracks * (1.5 + 0.5 * sin(uTime * 2.0 + h * 6.0));
    } else if (uKind < 3.5) {     // Tester: Dschungelwelt mit Stadtlichtern auf der Nachtseite
      float h = fbm(p * 2.0);
      vec3 ocean = mix(vec3(0.0, 0.07, 0.11), vec3(0.0, 0.3, 0.32), smoothstep(-0.4, 0.0, h));
      vec3 land = mix(vec3(0.07, 0.3, 0.11), vec3(0.45, 0.55, 0.25), smoothstep(0.1, 0.6, h));
      albedo = mix(ocean, land, smoothstep(0.0, 0.05, h));
      wet = 1.0 - smoothstep(-0.02, 0.04, h);
      clouds = smoothstep(0.15, 0.65, fbm(p * 2.6 - vec3(uTime * 0.04, 0.0, 0.0)));
      emissive = vec3(1.0, 0.78, 0.4) * smoothstep(0.45, 0.8, snoise(p * 22.0)) * smoothstep(0.05, 0.2, h);
      nightOnly = 1.0;
    } else {                      // Reviewer: violetter Eisriese (mit Ringen)
      float w = fbm(p * vec3(1.5, 5.0, 1.5) - vec3(uTime * 0.02, 0.0, 0.0));
      albedo = mix(vec3(0.2, 0.16, 0.52), vec3(0.78, 0.74, 1.0), 0.5 + 0.5 * sin(n.y * 10.0 + w * 2.5));
    }

    vec3 N = normalize(vWorldNormal), L = normalize(-vWorld), V = normalize(cameraPosition - vWorld);
    float light = dot(N, L);
    float diffuse = max(light, 0.0);
    float night = 1.0 - smoothstep(-0.15, 0.25, light);
    vec3 sun = vec3(1.0, 0.86, 0.68);
    albedo = mix(albedo, vec3(1.0), clouds * 0.85);
    vec3 c = albedo * sun * diffuse * 1.3 + albedo * (0.07 + uColor * 0.1);
    c += sun * pow(max(dot(N, normalize(L + V)), 0.0), 70.0) * wet * diffuse * 0.8;   // Glanz auf dem Wasser
    c += emissive * mix(1.0, night, nightOnly) * (1.0 - clouds * 0.7);
    float rim = 1.0 - max(dot(N, V), 0.0);
    c += uColor * pow(rim, 2.5) * (0.55 + 1.4 * smoothstep(-0.3, 0.6, light) + uGlow * 1.6);   // Atmosphäre
    c += uColor * uGlow * 0.1 * (1.0 + 0.3 * sin(uTime * 4.0));
    c += vec3(1.0) * uFlash * 0.35;
    gl_FragColor = vec4(c, 1.0);
  }`;

// Ringsystem des Reviewers mit Lücken wie bei Saturn
const PLANET_RING_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  varying vec2 vUv;
  float hash(float n) { return fract(sin(n) * 43758.5453); }
  void main() {
    float r = length(vUv - 0.5) * 2.0;
    float t = (r - 0.58) / 0.42;
    if (t < 0.0 || t > 1.0) discard;
    float fine = 0.65 + 0.35 * hash(floor(t * 90.0));
    float gaps = smoothstep(0.02, 0.05, abs(t - 0.62)) * smoothstep(0.01, 0.03, abs(t - 0.3));
    float alpha = smoothstep(0.0, 0.08, t) * smoothstep(1.0, 0.85, t) * fine * gaps * 0.8;
    vec3 color = mix(vec3(0.85, 0.82, 1.0), uColor, t * 0.8) * (0.55 + 0.45 * fine);
    gl_FragColor = vec4(color * alpha, alpha);
  }`;

// Galaxie: Sterne auf Spiralarmen, die sich differenziell drehen (innen schneller als außen)
const GALAXY_VERTEX = /* glsl */ `
  uniform float uTime, uPixelRatio;
  attribute float aRadius, aAngle, aHeight, aSize;
  attribute vec3 aColor;
  varying vec3 vColor;
  void main() {
    float angle = aAngle + uTime * 1.6 / (aRadius + 4.0);
    vec4 view = modelViewMatrix * vec4(cos(angle) * aRadius, aHeight, sin(angle) * aRadius, 1.0);
    gl_Position = projectionMatrix * view;
    gl_PointSize = aSize * uPixelRatio * (44.0 / -view.z);
    vColor = aColor;
  }`;

const STARS_VERTEX = /* glsl */ `
  uniform float uTime, uPixelRatio;
  attribute float aSize, aPhase;
  attribute vec3 aColor;
  varying vec3 vColor;
  void main() {
    vColor = aColor * (0.75 + 0.25 * sin(uTime * (0.6 + aPhase * 1.4) + aPhase * 40.0));
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * uPixelRatio;
  }`;

const POINT_FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    float a = exp(-d * d * 14.0) + 0.25 * exp(-d * d * 3.0) * smoothstep(1.0, 0.6, d);
    gl_FragColor = vec4(vColor * a, 1.0);
  }`;

// ---------------------------------------------------------------------------------------------

const additive = (extra) => ({
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...extra,
});

function glowTexture() {
  const size = 128, canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.2, "rgba(255,255,255,0.45)");
  gradient.addColorStop(0.5, "rgba(255,255,255,0.1)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

const gauss = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

// ---------------------------------------------------------------------------------------------

export class Universe {
  constructor(canvas, labelLayer) {
    this.canvas = canvas;
    this.labelLayer = labelLayer;
    this.anchorElement = null;
    this.energy = 0;
    this.alarm = 0;
    this.rotation = 0;
    this.queueEnd = 0;
    this.generation = 0;   // erhöht sich bei reset(), damit alte geplante Ereignisse verfallen
    this.beams = [];
    this.waves = [];
    this.flashes = [];
    this.idleTimer = null;
    this.clock = new THREE.Clock();
    this.time = 0;
    this.quality = 1;

    try {
      this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    } catch (error) {
      console.error("WebGL nicht verfügbar", error);
      canvas.classList.add("no-webgl");
      return;
    }
    this.renderer.setClearColor(0x03040b, 1);
    canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); this.lost = true; });
    canvas.addEventListener("webglcontextrestored", () => { this.lost = false; this.resize(); });

    this.glow = glowTexture();
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(FOV, 1, 0.5, 3000);
    this.uniforms = { uTime: { value: 0 }, uPixelRatio: { value: 1 } };
    this.buildSky();
    this.buildGalaxy();
    this.buildSupervisor();
    this.buildAgents();
    this.buildLabels();
    if (new URLSearchParams(location.search).has("debug")) {  // ?debug zeigt Grafikkarte und Bildrate
      this.debug = document.createElement("pre");
      this.debug.className = "space-debug";
      document.body.appendChild(this.debug);
      const gl = this.renderer.getContext(), info = gl.getExtension("WEBGL_debug_renderer_info");
      this.gpu = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : "unbekannt";
    }
    window.addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
  }

  // ---- Aufbau --------------------------------------------------------------------------

  buildSky() {
    // Ferne Sterne auf einer großen Kugel
    const count = 3500, positions = [], sizes = [], colors = [], phases = [];
    const direction = new THREE.Vector3(), color = new THREE.Color();
    const tints = ["#9fb4ff", "#c8d4ff", "#ffffff", "#fff1e0", "#ffd9b0"];
    for (let i = 0; i < count; i++) {
      direction.randomDirection().multiplyScalar(900);
      positions.push(direction.x, direction.y, direction.z);
      const bright = Math.random() ** 6;
      sizes.push(1.5 + bright * 4.5);
      color.set(tints[i % tints.length]).multiplyScalar(0.35 + bright * 1.1);
      colors.push(color.r, color.g, color.b);
      phases.push(Math.random());
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute("aSize", new THREE.Float32BufferAttribute(sizes, 1));
    geometry.setAttribute("aColor", new THREE.Float32BufferAttribute(colors, 3));
    geometry.setAttribute("aPhase", new THREE.Float32BufferAttribute(phases, 1));
    this.sky = new THREE.Points(geometry, new THREE.ShaderMaterial(additive({
      vertexShader: STARS_VERTEX, fragmentShader: POINT_FRAGMENT, uniforms: this.uniforms,
    })));
    this.scene.add(this.sky);

    // Zarte Nebelschleier im Hintergrund
    for (const [x, y, z, size, tint, opacity] of [
      [-260, 90, -600, 700, "#3b2a7a", 0.22], [320, -60, -650, 800, "#123c66", 0.2], [40, 220, -700, 600, "#5a2448", 0.12],
    ]) {
      const nebula = new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: this.glow, color: tint, opacity })));
      nebula.position.set(x, y, z);
      nebula.scale.setScalar(size);
      this.scene.add(nebula);
    }
  }

  buildGalaxy() {
    const count = 22000, arms = 3, extent = ORBIT * 2.1;
    const radii = [], angles = [], heights = [], sizes = [], colors = [];
    const inner = new THREE.Color("#ffd2a0"), mid = new THREE.Color("#c58cff"), outer = new THREE.Color("#5f8dff");
    const color = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const t = Math.random() ** 1.6;
      const radius = 1.6 + t * extent;
      const arm = (i % arms) / arms * TAU;
      const spread = (0.25 + t * 0.55) * gauss();
      const dust = i % 7 === 0;   // ein Teil der Sterne liegt zwischen den Armen
      radii.push(radius);
      angles.push(arm + radius * 0.32 + (dust ? Math.random() * TAU : spread));
      heights.push(gauss() * (0.5 - t * 0.35));
      sizes.push((dust ? 0.8 : 1) * (1 + Math.random() ** 8 * 4 + Math.random() * 0.6));
      if (t < 0.4) color.copy(inner).lerp(mid, t / 0.4);
      else color.copy(mid).lerp(outer, (t - 0.4) / 0.6);
      color.multiplyScalar((dust ? 0.25 : 0.55) * (1.15 - t * 0.6) * (0.6 + Math.random() * 0.6));
      colors.push(color.r, color.g, color.b);
    }
    const geometry = new THREE.BufferGeometry();
    const attribute = (name, values, size) => geometry.setAttribute(name, new THREE.Float32BufferAttribute(values, size));
    attribute("position", new Array(count * 3).fill(0), 3);
    attribute("aRadius", radii, 1);
    attribute("aAngle", angles, 1);
    attribute("aHeight", heights, 1);
    attribute("aSize", sizes, 1);
    attribute("aColor", colors, 3);
    this.galaxy = new THREE.Points(geometry, new THREE.ShaderMaterial(additive({
      vertexShader: GALAXY_VERTEX, fragmentShader: POINT_FRAGMENT, uniforms: this.uniforms,
    })));
    this.galaxy.frustumCulled = false;   // Positionen entstehen erst im Shader
    this.scene.add(this.galaxy);

    // Dünne Umlaufbahn der Agenten
    const points = [];
    for (let i = 0; i <= 256; i++) points.push(new THREE.Vector3(Math.cos(i / 256 * TAU) * ORBIT, 0, Math.sin(i / 256 * TAU) * ORBIT));
    this.orbit = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineBasicMaterial(additive({ color: "#ffcf9a", opacity: 0.14 })));
    this.scene.add(this.orbit);
  }

  buildSupervisor() {
    this.coreUniforms = { uTime: this.uniforms.uTime, uEnergy: { value: 0 }, uAlarm: { value: 0 },
      uWarm: { value: GOLD }, uAlarmColor: { value: ALARM } };
    this.core = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), new THREE.ShaderMaterial(additive({
      vertexShader: QUAD_VERTEX, fragmentShader: CORE_FRAGMENT, uniforms: this.coreUniforms,
    })));
    this.core.renderOrder = 2;
    this.scene.add(this.core);

    this.swirl = new THREE.Mesh(new THREE.PlaneGeometry(9, 9), new THREE.ShaderMaterial(additive({
      vertexShader: QUAD_VERTEX, fragmentShader: SWIRL_FRAGMENT, uniforms: this.coreUniforms, side: THREE.DoubleSide,
    })));
    this.swirl.rotation.x = -Math.PI / 2;
    this.swirl.renderOrder = 1;
    this.scene.add(this.swirl);
  }

  buildAgents() {
    const sphere = new THREE.SphereGeometry(ORB_SIZE, 64, 40);
    this.planets = Object.entries(AGENTS).map(([key, agent], i) => {
      const color = new THREE.Color(agent.color);
      const uniforms = { uColor: { value: color }, uTime: this.uniforms.uTime, uGlow: { value: 0 }, uFlash: { value: 0 },
        uKind: { value: agent.kind } };
      const group = new THREE.Group();
      group.add(new THREE.Mesh(sphere, new THREE.ShaderMaterial({ vertexShader: ORB_VERTEX, fragmentShader: ORB_FRAGMENT, uniforms })));
      const halo = new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: this.glow, color })));
      halo.scale.setScalar(ORB_SIZE * 5);
      group.add(halo);
      if (agent.kind === 4) {
        const rings = new THREE.Mesh(new THREE.PlaneGeometry(ORB_SIZE * 4.6, ORB_SIZE * 4.6), new THREE.ShaderMaterial({
          vertexShader: QUAD_VERTEX, fragmentShader: PLANET_RING_FRAGMENT, uniforms: { uColor: { value: color } },
          transparent: true, depthWrite: false, side: THREE.DoubleSide,
          blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
        }));
        rings.rotation.set(-Math.PI / 2 + 0.42, 0.3, 0);
        rings.renderOrder = 3;
        group.add(rings);
      }
      const ring = this.ringMesh(color, ORB_SIZE * 6.2, { uRadius: 0.62, uWidth: 0.03, uDash: 1 });
      group.add(ring.mesh);
      this.scene.add(group);
      return { key, ...agent, color3: color, group, halo, ring, uniforms, phase: (i / 5) * TAU + 0.6,
        active: false, done: false, glow: 0, flash: 0, model: "", beam: null };
    });
  }

  ringMesh(color, size, values) {
    const uniforms = { uTime: this.uniforms.uTime, uColor: { value: color.clone() }, uRadius: { value: 0.5 },
      uWidth: { value: 0.02 }, uAlpha: { value: 0 }, uDash: { value: 0 } };
    for (const [name, value] of Object.entries(values)) uniforms[name].value = value;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.ShaderMaterial(additive({
      vertexShader: QUAD_VERTEX, fragmentShader: RING_FRAGMENT, uniforms, side: THREE.DoubleSide,
    })));
    mesh.rotation.x = -Math.PI / 2;
    return { mesh, uniforms };
  }

  buildLabels() {
    const label = (cls) => {
      const el = document.createElement("div");
      el.className = `space-label ${cls}`;
      this.labelLayer.appendChild(el);
      return el;
    };
    this.supervisorLabel = label("supervisor");
    this.supervisorLabel.innerHTML = `<strong>Supervisor</strong><span>${SUPERVISOR.role}</span>`;
    for (const planet of this.planets) {
      planet.label = label("planet");
      planet.label.innerHTML = `<strong>${planet.name}</strong><span></span>`;
      planet.label.style.setProperty("--c", planet.color);
    }
  }

  // ---- Ausrichtung auf ein HTML-Element ------------------------------------------------------

  anchor(element) {
    this.anchorElement = element;
  }

  idle(on) {
    clearTimeout(this.idleTimer);
    if (!on) return;
    const keys = Object.keys(AGENTS);
    let i = 0;
    const step = () => {
      const key = keys[i++ % keys.length];
      this.dispatch(key);
      this.idleTimer = setTimeout(() => {
        this.report(key);
        this.idleTimer = setTimeout(step, 1800);
      }, 2600);
    };
    this.idleTimer = setTimeout(step, 900);
  }

  // Erst bei unter 30 Bildern pro Sekunde etwas weniger Pixel rechnen, aber nie so wenig, dass es unscharf wird
  adaptQuality(dt) {
    this.frameTimes = (this.frameTimes || []).concat(dt).slice(-40);
    this.fps = this.frameTimes.length / this.frameTimes.reduce((a, b) => a + b, 0.0001);
    if (this.frameTimes.length < 40 || this.time < 3 || performance.now() < (this.nextQualityCheck || 0)) return;
    this.nextQualityCheck = performance.now() + 2000;
    if (this.fps < 30 && this.quality > 0.75) {
      this.quality = Math.max(0.75, this.quality * 0.88);
      this.frameTimes = [];
      this.resize();
    }
  }

  resize() {
    const width = window.innerWidth, height = window.innerHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2) * this.quality;
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(width, height, false);
    this.uniforms.uPixelRatio.value = ratio;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  fitCamera() {
    const rect = this.anchorElement?.getBoundingClientRect();
    const visible = rect && rect.width > 0 && rect.height > 0;
    this.labelLayer.style.visibility = visible ? "visible" : "hidden";
    if (!visible) return false;
    const W = window.innerWidth, H = window.innerHeight;
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height * 0.5;
    // Bahn so groß wie möglich, aber mit Platz für Kugeln und Beschriftungen
    const orbitPx = Math.min(rect.width * 0.42, (rect.height * 0.34) / Math.sin(ELEVATION));
    const distance = (ORBIT * H) / (2 * Math.tan(THREE.MathUtils.degToRad(FOV / 2)) * orbitPx);
    const sway = REDUCED_MOTION ? 0 : Math.sin(this.time * 0.06) * 0.08;
    this.camera.position.set(Math.sin(sway) * distance * Math.cos(ELEVATION), Math.sin(ELEVATION) * distance,
      Math.cos(sway) * distance * Math.cos(ELEVATION));
    this.camera.lookAt(0, 0, 0);
    this.camera.setViewOffset(W, H, W / 2 - cx, H / 2 - cy, W, H);
    return true;
  }

  // ---- Ablaufsteuerung --------------------------------------------------------------------

  // Ereignisse nacheinander abspielen, auch wenn der Server sie schneller schickt
  schedule(duration, action) {
    const now = performance.now(), generation = this.generation;
    const start = Math.max(now, this.queueEnd);
    this.queueEnd = start + (REDUCED_MOTION ? 50 : duration);
    setTimeout(() => { if (generation === this.generation) action(); }, start - now);
  }

  later(ms, action) {
    const generation = this.generation;
    setTimeout(() => { if (generation === this.generation) action(); }, REDUCED_MOTION ? 0 : ms);
  }

  planet(key) { return this.planets?.find((p) => p.key === key); }

  planetPosition(planet, target = new THREE.Vector3()) {
    const angle = planet.phase + this.rotation;
    return target.set(Math.cos(angle) * ORBIT, Math.sin(angle * 2 + planet.phase) * 0.25, Math.sin(angle) * ORBIT);
  }

  // Strahl von from() nach to(). sustain: bleibt stehen, bis release() aufgerufen wird.
  beam(from, to, colorA, colorB, { grow = 550, hold = 0, width = 0.95, power = 1, sustain = false } = {}) {
    const segments = 120, u = [], side = [], index = [];
    for (let i = 0; i <= segments; i++) {
      u.push(i / segments, i / segments);
      side.push(-1, 1);
      if (i < segments) index.push(2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 1, 2 * i + 3, 2 * i + 2);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(new Array(u.length * 3).fill(0), 3));
    geometry.setAttribute("aU", new THREE.Float32BufferAttribute(u, 1));
    geometry.setAttribute("aSide", new THREE.Float32BufferAttribute(side, 1));
    geometry.setIndex(index);
    const uniforms = { uTime: this.uniforms.uTime, uA: { value: new THREE.Vector3() }, uB: { value: new THREE.Vector3() },
      uC: { value: new THREE.Vector3() }, uWidth: { value: width }, uReach: { value: 0 }, uPower: { value: 0 },
      uSeed: { value: Math.random() * 100 }, uColorA: { value: colorA.clone() }, uColorB: { value: colorB.clone() } };
    const mesh = new THREE.Mesh(geometry, new THREE.ShaderMaterial(additive({
      vertexShader: BEAM_VERTEX, fragmentShader: BEAM_FRAGMENT, uniforms, side: THREE.DoubleSide,
    })));
    mesh.frustumCulled = false;
    mesh.renderOrder = 3;
    this.scene.add(mesh);
    const beam = { mesh, uniforms, from, to, grow: REDUCED_MOTION ? 1 : grow, hold, power, sustain,
      start: performance.now(), released: null };
    beam.release = () => { beam.released ??= performance.now(); };
    this.beams.push(beam);
    return beam;
  }

  wave(color, strength = 1) {
    const ring = this.ringMesh(color, ORBIT * 2.6, {});
    ring.mesh.renderOrder = 1;
    this.scene.add(ring.mesh);
    this.waves.push({ ...ring, strength, start: performance.now() });
  }

  flash(position, color, scale, duration = 900) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial(additive({ map: this.glow, color })));
    sprite.position.copy(position);
    sprite.renderOrder = 4;
    this.scene.add(sprite);
    this.flashes.push({ sprite, scale, duration, start: performance.now() });
  }

  // ---- Ereignisse aus dem Lauf ---------------------------------------------------------------

  dispatch(key) {
    const planet = this.planet(key);
    if (!planet) return;
    this.schedule(1100, () => {
      for (const other of this.planets) {
        if (other !== planet && other.active) { other.active = false; other.beam?.release(); }
      }
      planet.beam?.release();
      this.energy = 1.2;
      this.wave(GOLD, 0.9);
      planet.beam = this.beam(() => new THREE.Vector3(0, 0, 0), () => this.planetPosition(planet), GOLD, planet.color3,
        { grow: 600, sustain: true, power: 1.25 });
      this.later(600, () => {
        planet.active = true;
        planet.flashAt = performance.now();
        this.flash(this.planetPosition(planet), planet.color3, ORB_SIZE * 9);
      });
    });
  }

  report(key, model) {
    const planet = this.planet(key);
    if (!planet) return;
    if (model) planet.model = model;
    this.schedule(900, () => {
      planet.beam?.release();
      planet.beam = null;
      this.beam(() => this.planetPosition(planet), () => new THREE.Vector3(0, 0, 0), planet.color3, GOLD,
        { grow: 450, hold: 120, width: 0.6, power: 1.1 });
      this.later(450, () => {
        planet.active = false;
        planet.done = true;
        this.energy = Math.max(this.energy, 0.8);
        this.flash(new THREE.Vector3(0, 0, 0), planet.color3, 5, 700);
      });
    });
  }

  guardrail() {
    this.schedule(600, () => {
      this.alarm = 1;
      this.energy = 1;
      this.wave(ALARM, 1);
    });
  }

  finish() {
    this.schedule(2200, () => {
      this.energy = 2;
      this.wave(GOLD, 1.4);
      this.later(250, () => this.wave(new THREE.Color("#ffe6c4"), 0.8));
      this.flash(new THREE.Vector3(0, 0, 0), new THREE.Color("#fff2e0"), 22, 1600);
      for (const planet of this.planets) {
        planet.active = false;
        planet.beam?.release();
        planet.beam = null;
        this.beam(() => new THREE.Vector3(0, 0, 0), () => this.planetPosition(planet), GOLD, planet.color3,
          { grow: 700, hold: 900, power: 1 });
        this.later(700, () => { planet.flashAt = performance.now(); });
      }
    });
  }

  reset() {
    if (!this.planets) return;
    this.generation++;
    this.planets.forEach((p) => Object.assign(p, { active: false, done: false, glow: 0, flash: 0, flashAt: null, model: "", beam: null }));
    for (const b of this.beams) this.dispose(b.mesh);
    for (const w of this.waves) this.dispose(w.mesh);
    for (const f of this.flashes) this.dispose(f.sprite);
    this.beams = [];
    this.waves = [];
    this.flashes = [];
    this.queueEnd = 0;
    this.alarm = 0;
  }

  dispose(object) {
    this.scene.remove(object);
    object.geometry?.dispose();
    object.material?.dispose();
  }

  // ---- Jedes Bild ---------------------------------------------------------------------------

  frame() {
    if (document.hidden || this.lost) return;
    const dt = Math.min(this.clock.getDelta(), 0.05);
    this.time += REDUCED_MOTION ? 0 : dt;
    if (!REDUCED_MOTION) this.rotation += dt * 0.045;
    this.energy += (0 - this.energy) * Math.min(1, dt * 0.9);
    this.alarm = Math.max(0, this.alarm - dt * 0.45);

    const visible = this.fitCamera();
    this.uniforms.uTime.value = this.time;
    this.coreUniforms.uEnergy.value = this.energy;
    this.coreUniforms.uAlarm.value = this.alarm;
    this.core.quaternion.copy(this.camera.quaternion);
    this.sky.rotation.y = this.time * 0.003;
    for (const object of [this.galaxy, this.orbit, this.core, this.swirl]) object.visible = visible;

    for (const planet of this.planets) {
      planet.group.visible = visible;
      this.planetPosition(planet, planet.group.position);
      planet.glow += ((planet.active ? 1 : 0) - planet.glow) * Math.min(1, dt * 3);
      planet.flash = Math.max(0, 1 - (performance.now() - (planet.flashAt ?? -1e9)) / 700);
      planet.uniforms.uGlow.value = planet.glow;
      planet.uniforms.uFlash.value = planet.flash;
      planet.halo.material.opacity = 0.1 + planet.glow * 0.35 + planet.flash * 0.5;
      planet.halo.scale.setScalar(ORB_SIZE * (4.5 + planet.glow * 1.5 + Math.sin(this.time * 5) * planet.glow * 0.4));
      planet.ring.uniforms.uAlpha.value = planet.glow * 0.9;
      planet.ring.mesh.rotation.z = this.time * 0.6;
    }
    this.updateBeams();
    this.updateWaves();
    this.updateFlashes();
    this.renderer.render(this.scene, this.camera);
    if (visible) this.updateLabels();
    this.adaptQuality(dt);
    if (this.debug) {
      this.debug.textContent = `${this.gpu}\n${Math.round(this.fps || 0)} FPS · Qualität ${Math.round(this.quality * 100)} % · ` +
        `${this.renderer.domElement.width}×${this.renderer.domElement.height} px`;
    }
  }

  updateBeams() {
    const now = performance.now();
    this.beams = this.beams.filter((beam) => {
      const elapsed = now - beam.start;
      const reach = Math.min(1, elapsed / beam.grow);
      if (!beam.sustain && !beam.released && elapsed > beam.grow + beam.hold) beam.release();
      // Beim Auftreffen kurz gleißend, danach eine ruhigere, gehaltene Verbindung
      let power = beam.power * (reach < 1 ? 1 : (beam.sustain ? 0.55 + 0.45 * Math.exp(-(elapsed - beam.grow) / 400) : 1));
      if (beam.released) {
        const fade = (now - beam.released) / 450;
        if (fade >= 1) {
          this.dispose(beam.mesh);
          return false;
        }
        power *= (1 - fade) ** 2;
      }
      const a = beam.from(), c = beam.to();
      const b = a.clone().add(c).multiplyScalar(0.5);
      b.y += a.distanceTo(c) * 0.16;
      beam.uniforms.uA.value.copy(a);
      beam.uniforms.uB.value.copy(b);
      beam.uniforms.uC.value.copy(c);
      beam.uniforms.uReach.value = easeOut(reach);
      beam.uniforms.uPower.value = power;
      beam.mesh.visible = this.galaxy.visible;
      return true;
    });
  }

  updateWaves() {
    const now = performance.now();
    this.waves = this.waves.filter((wave) => {
      const p = (now - wave.start) / 1500;
      if (p >= 1) {
        this.dispose(wave.mesh);
        return false;
      }
      const e = easeOut(p);
      wave.uniforms.uRadius.value = 0.05 + e * 0.9;
      wave.uniforms.uWidth.value = 0.006 + e * 0.02;
      wave.uniforms.uAlpha.value = wave.strength * (1 - p) ** 1.5 * 1.6;
      wave.mesh.visible = this.galaxy.visible;
      return true;
    });
  }

  updateFlashes() {
    const now = performance.now();
    this.flashes = this.flashes.filter((f) => {
      const p = (now - f.start) / f.duration;
      if (p >= 1) {
        this.dispose(f.sprite);
        return false;
      }
      f.sprite.scale.setScalar(f.scale * (0.3 + easeOut(p) * 0.9));
      f.sprite.material.opacity = (1 - p) ** 2;
      return true;
    });
  }

  updateLabels() {
    const W = window.innerWidth, H = window.innerHeight;
    const toScreen = (v) => {
      const p = v.clone().project(this.camera);
      return { x: (p.x + 1) / 2 * W, y: (1 - p.y) / 2 * H };
    };
    const above = toScreen(new THREE.Vector3(0, 1.9, 0));
    this.supervisorLabel.style.transform = `translate(${above.x}px, ${above.y}px) translate(-50%, -100%)`;

    const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    for (const planet of this.planets) {
      const center = planet.group.position;
      const c = toScreen(center);
      const radius = Math.abs(toScreen(center.clone().addScaledVector(right, ORB_SIZE)).x - c.x);
      const depth = (Math.sin(planet.phase + this.rotation) + 1) / 2;  // 1 = vorne
      planet.label.style.transform = `translate(${c.x}px, ${c.y + radius + 12}px) translate(-50%, 0)`;
      planet.label.style.opacity = (0.55 + 0.45 * depth).toFixed(2);
      planet.label.classList.toggle("active", planet.active);
      planet.label.classList.toggle("done", planet.done && !planet.active);
      const status = planet.active ? "arbeitet" : planet.done ? "✓ erledigt" : "";
      const detail = [status, planet.model].filter(Boolean).join(" · ");
      const span = planet.label.querySelector("span");
      if (span.textContent !== detail) span.textContent = detail;
    }
  }
}
