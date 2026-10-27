// Canvas 2D engine. Contract: create(canvas) -> { render(slots, t), resize(w, h), destroy() }.
// Each slot is drawn into its own layer, then composited with its blend mode and opacity.
// Scene ids and param keys must match showanimator/engines/canvas2d.py.

// Images are fetched once and reused. A missing or unreadable file draws nothing.
const images = new Map();
const scratch = document.createElement("canvas");

function imageFor(name) {
  if (!images.has(name)) {
    const img = new Image();
    img.src = `/animator/media/${encodeURIComponent(name)}`;
    images.set(name, img);
  }
  const img = images.get(name);
  return img.complete && img.naturalWidth > 0 ? img : null;
}

// Huge maps are drawn per frame from a bitmap at most MAX_SOURCE px on the long side.
// Drawing from the full 8670 px file ran at about 22 fps once loaded, against about 60 for a small image.
// shortcut: the first frame after load pays a one-time decode of the full file, and the cap blurs close-up zooms; pre-scale the file to skip the decode.
const MAX_SOURCE = 4096;
const bitmaps = new WeakMap();
function bitmapFor(img) {
  if (!bitmaps.has(img)) {
    const f = Math.min(1, MAX_SOURCE / Math.max(img.naturalWidth, img.naturalHeight));
    if (f === 1) {
      bitmaps.set(img, { src: img, f: 1 });
    } else {
      const cv = document.createElement("canvas");
      cv.width = Math.round(img.naturalWidth * f);
      cv.height = Math.round(img.naturalHeight * f);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      bitmaps.set(img, { src: cv, f: cv.width / img.naturalWidth });
    }
  }
  return bitmaps.get(img);
}

// Shift horizontal bands in the lower 40% by a slow wave, so water and foliage seem to breathe.
function waterSway(c, w, h, amp, t) {
  if (scratch.width !== w || scratch.height !== h) {
    scratch.width = w;
    scratch.height = h;
  }
  const sc = scratch.getContext("2d");
  sc.clearRect(0, 0, w, h);
  sc.drawImage(c.canvas, 0, 0);
  const top = Math.floor(h * 0.6);
  const band = 3;
  c.clearRect(0, top, w, h - top);
  for (let y = top; y < h; y += band) {
    const bh = Math.min(band, h - y);
    const dx = amp * Math.sin((2 * Math.PI * t) / 6 + y * 0.05);
    c.drawImage(scratch, 0, y, w, bh, dx, y, w, bh);
    // Refill the uncovered edge with the nearest column, stretched.
    if (dx > 0) c.drawImage(scratch, 0, y, 1, bh, 0, y, dx, bh);
    else if (dx < 0) c.drawImage(scratch, w - 1, y, 1, bh, w + dx, y, -dx, bh);
  }
}

// Overlay a colour only where something is already drawn (source-atop).
function wash(c, w, h, color, alpha) {
  c.save();
  c.globalCompositeOperation = "source-atop";
  c.globalAlpha = alpha;
  c.fillStyle = color;
  c.fillRect(0, 0, w, h);
  c.restore();
}

// Hex colour with alpha, for gradient stops.
function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

// Deterministic 0..1 value per (index, channel), so stars keep their places.
function rnd(i, k) {
  const x = Math.sin(i * 12.9898 + k * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

// Travel map: a plane flies a route over a map image. Stops are NAME,x,y in image pixels.
const SAMPLES = 200; // points per leg
const travel = new WeakMap(); // layer canvas -> { shown, last }: flight progress eased toward the target
const PLANE = [[30, 0], [8, 4], [2, 26], [-6, 26], [-2, 4], [-20, 3], [-26, 12], [-30, 12], [-28, 0],
  [-30, -12], [-26, -12], [-20, -3], [-2, -4], [-6, -26], [2, -26], [8, -4]];

export function parseRoute(text) {
  return text.split(";").map((s) => {
    const [name, x, y] = s.split(",");
    return { name: name.trim(), x: parseFloat(x), y: parseFloat(y) };
  });
}

// Each leg is a quadratic curve that bulges north, like a flight arc. Legs join into one polyline.
export function buildRoute(stops) {
  const pts = [];
  const stopAt = [0]; // index in pts of each stop
  for (let k = 0; k < stops.length - 1; k++) {
    const a = stops[k];
    const b = stops[k + 1];
    const cx = (a.x + b.x) / 2;
    const cy = (a.y + b.y) / 2 - Math.hypot(b.x - a.x, b.y - a.y) * 0.18;
    for (let s = k === 0 ? 0 : 1; s <= SAMPLES; s++) {
      const u = s / SAMPLES;
      const v = 1 - u;
      pts.push({ x: v * v * a.x + 2 * v * u * cx + u * u * b.x, y: v * v * a.y + 2 * v * u * cy + u * u * b.y });
    }
    stopAt.push(pts.length - 1);
  }
  const cum = [0]; // distance along the route at each point
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y));
  }
  return { stops, pts, cum, stopAt, total: cum[cum.length - 1] };
}

// Position at fraction f of the route, its heading, the point index reached, and stops passed.
export function locate(route, f) {
  const d = Math.min(1, Math.max(0, f)) * route.total;
  let lo = 1;
  let hi = route.cum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (route.cum[mid] < d) lo = mid + 1;
    else hi = mid;
  }
  const a = route.pts[lo - 1];
  const b = route.pts[lo];
  const u = (d - route.cum[lo - 1]) / (route.cum[lo] - route.cum[lo - 1] || 1);
  let passed = 0;
  while (passed < route.stopAt.length && route.cum[route.stopAt[passed]] <= d) passed++;
  return {
    x: a.x + (b.x - a.x) * u,
    y: a.y + (b.y - a.y) * u,
    ang: Math.atan2(b.y - a.y, b.x - a.x),
    index: lo,
    passed,
  };
}

// Filled plane silhouette, rotated to its heading.
function plane(c, x, y, ang, s, color) {
  const cs = Math.cos(ang);
  const sn = Math.sin(ang);
  c.beginPath();
  PLANE.forEach(([px, py], i) => {
    const X = x + s * (px * cs - py * sn);
    const Y = y + s * (px * sn + py * cs);
    if (i) c.lineTo(X, Y);
    else c.moveTo(X, Y);
  });
  c.closePath();
  c.fillStyle = color;
  c.fill();
}

const SCENES = {
  painting(c, w, h, p, t) {
    const img = p.image && imageFor(p.image);
    if (!img) return;
    // Cover the stage and zoom in, then pan on a slow sine within the spare room.
    const s = Math.max(w / img.naturalWidth, h / img.naturalHeight) * p.zoom;
    const dw = img.naturalWidth * s;
    const dh = img.naturalHeight * s;
    const phase = (2 * Math.PI * t) / p.period;
    const x = (w - dw) / 2 + Math.sin(phase) * ((dw - w) / 2) * p.drift;
    const y = (h - dh) / 2 + Math.cos(phase * 0.618) * ((dh - h) / 2) * p.drift;
    c.drawImage(img, x, y, dw, dh);
    if (p.sway > 0) waterSway(c, w, h, p.sway * w, t);
    if (p.brightness) wash(c, w, h, p.brightness > 0 ? "#fff" : "#000", Math.abs(p.brightness));
    if (p.tint_strength > 0) wash(c, w, h, p.tint, p.tint_strength);
  },
  solid(c, w, h, p) {
    c.fillStyle = p.color;
    c.fillRect(0, 0, w, h);
  },
  gradient(c, w, h, p) {
    const a = (p.angle * Math.PI) / 180;
    const r = Math.hypot(w, h) / 2;
    const cx = w / 2;
    const cy = h / 2;
    const g = c.createLinearGradient(cx - Math.cos(a) * r, cy - Math.sin(a) * r,
                                     cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    g.addColorStop(0, p.color);
    g.addColorStop(1, p.color2);
    c.fillStyle = g;
    c.fillRect(0, 0, w, h);
  },
  pulse(c, w, h, p, t) {
    const k = (Math.sin(2 * Math.PI * p.speed * t) + 1) / 2; // 0..1
    const radius = (p.size * Math.min(w, h) / 2) * (0.25 + 0.75 * k);
    c.fillStyle = p.color;
    c.beginPath();
    c.arc(w / 2, h / 2, radius, 0, 2 * Math.PI);
    c.fill();
  },
  fog(c, w, h, p, t) {
    const R = Math.max(w, h) * p.size;
    for (let i = 0; i < 6; i++) {
      const ph = 2 * Math.PI * p.speed * t * (0.5 + rnd(i, 1)) + i * 1.7;
      const x = w * (0.5 + 0.4 * Math.sin(ph));
      const y = h * (0.5 + 0.4 * Math.cos(ph * 0.7 + i));
      const r = R * (0.6 + 0.4 * rnd(i, 2));
      const g = c.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, rgba(p.color, p.density));
      g.addColorStop(1, rgba(p.color, 0));
      c.fillStyle = g;
      c.fillRect(x - r, y - r, 2 * r, 2 * r);
    }
  },
  sparkle(c, w, h, p, t) {
    const unit = Math.min(w, h) / 720; // star size follows the stage size
    c.fillStyle = p.color;
    for (let i = 0; i < Math.round(p.count); i++) {
      const phase = 2 * Math.PI * p.rate * t * (0.5 + rnd(i, 3)) + rnd(i, 4) * 2 * Math.PI;
      const b = Math.max(0, Math.sin(phase)) ** 4;
      if (b < 0.01) continue;
      c.globalAlpha = b;
      c.beginPath();
      c.arc(rnd(i, 1) * w, rnd(i, 2) * h, (0.5 + 1.5 * rnd(i, 5)) * p.size * unit, 0, 2 * Math.PI);
      c.fill();
    }
    c.globalAlpha = 1;
  },
  travelmap(c, w, h, p, t) {
    const img = p.image && imageFor(p.image);
    if (!img) return;
    const bm = bitmapFor(img);
    const route = buildRoute(parseRoute(p.route));
    const st = travel.get(c) || { shown: 0, last: t };
    travel.set(c, st);
    const dt = Math.min(0.1, Math.max(0, t - st.last)); // a stalled frame must not jump the plane
    st.last = t;
    // Ease toward the target at p.speed route-lengths per second; speed 0 jumps.
    const step = p.speed * dt;
    st.shown = p.speed > 0 ? st.shown + Math.max(-step, Math.min(step, p.progress - st.shown)) : p.progress;

    const k = w / 1920; // screen sizes scale with the stage width, as in the montage
    const sc = p.zoom * k; // screen px per image px
    const vw = w / sc;
    const vh = h / sc;
    const pos = locate(route, st.shown);
    // Follow the plane, but keep the view inside the image.
    const x0 = Math.min(Math.max(0, pos.x - vw / 2), Math.max(0, img.naturalWidth - vw));
    const y0 = Math.min(Math.max(0, pos.y - vh / 2), Math.max(0, img.naturalHeight - vh));
    c.drawImage(bm.src, x0 * bm.f, y0 * bm.f, vw * bm.f, vh * bm.f, 0, 0, w, h);
    c.save();
    const sx = (x) => (x - x0) * sc;
    const sy = (y) => (y - y0) * sc;
    const trail = (dx, dy, color, width) => {
      c.beginPath();
      for (let i = 0; i < pos.index; i++) {
        if (i) c.lineTo(sx(route.pts[i].x) + dx, sy(route.pts[i].y) + dy);
        else c.moveTo(sx(route.pts[i].x) + dx, sy(route.pts[i].y) + dy);
      }
      c.lineTo(sx(pos.x) + dx, sy(pos.y) + dy);
      c.strokeStyle = color;
      c.lineWidth = width * k;
      c.lineJoin = "round";
      c.stroke();
    };
    trail(5 * k, 6 * k, "rgb(90,70,45)", 11); // shadow, then the red line
    trail(0, 0, "rgb(185,20,15)", 10);
    c.font = `bold ${46 * k}px serif`;
    c.textAlign = "center";
    c.textBaseline = "top";
    route.stops.slice(0, pos.passed).forEach((stop) => {
      const X = sx(stop.x);
      const Y = sy(stop.y);
      c.beginPath();
      c.arc(X, Y, 12 * k, 0, 2 * Math.PI);
      c.fillStyle = "rgb(40,25,15)";
      c.fill();
      c.lineWidth = 3 * k;
      c.strokeStyle = "rgb(230,210,170)";
      c.stroke();
      c.fillStyle = "rgb(80,60,40)";
      c.fillText(stop.name, X + 3 * k, Y + 33 * k);
      c.fillStyle = "rgb(30,15,5)";
      c.fillText(stop.name, X, Y + 30 * k);
    });
    plane(c, sx(pos.x) + 14 * k, sy(pos.y) + 18 * k, pos.ang, 1.6 * k, "rgb(90,70,45)");
    plane(c, sx(pos.x), sy(pos.y), pos.ang, 1.6 * k, "rgb(45,40,35)");
    // Film look: sepia tone (colour blend keeps the light and dark), vignette, grain.
    if (p.sepia > 0) {
      c.globalCompositeOperation = "color";
      c.globalAlpha = p.sepia;
      c.fillStyle = "rgb(140,100,50)";
      c.fillRect(0, 0, w, h);
    }
    c.globalCompositeOperation = "source-over";
    c.globalAlpha = 1;
    c.drawImage(vignetteFor(w, h), 0, 0);
    for (let i = 0; i < Math.round(p.grain * 800); i++) {
      c.fillStyle = Math.random() < 0.5 ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)";
      c.fillRect(Math.random() * w, Math.random() * h, 2 * k, 2 * k);
    }
    c.restore();
  },
};

// The vignette depends only on size; a gradient fill per frame cost about 16 ms in software rendering.
let vignetteCache = null;
function vignetteFor(w, h) {
  if (vignetteCache && vignetteCache.width === w && vignetteCache.height === h) return vignetteCache;
  vignetteCache = document.createElement("canvas");
  vignetteCache.width = w;
  vignetteCache.height = h;
  const v = vignetteCache.getContext("2d");
  const g = v.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.35, w / 2, h / 2, Math.hypot(w, h) / 2);
  g.addColorStop(0, "rgba(0,0,0,0)");
  g.addColorStop(1, "rgba(0,0,0,0.55)");
  v.fillStyle = g;
  v.fillRect(0, 0, w, h);
  return vignetteCache;
}

export function create(canvas) {
  const ctx = canvas.getContext("2d");
  const layers = []; // one reusable offscreen canvas per slot index

  function layer(i) {
    if (!layers[i]) layers[i] = document.createElement("canvas");
    return layers[i];
  }

  function compose(blend, src, opacity) {
    ctx.globalAlpha = opacity;
    if (blend === "add") {
      ctx.globalCompositeOperation = "lighter";
      ctx.drawImage(src, 0, 0);
    } else if (blend === "subtract") {
      // dst - src == 1 - ((1 - dst) + src), so invert, add, invert back.
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "difference";
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = opacity;
      ctx.globalCompositeOperation = "lighter";
      ctx.drawImage(src, 0, 0);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "difference";
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    } else if (blend === "mask") {
      // Knockout: the slot's shape erases what is beneath it, scaled by opacity.
      ctx.globalCompositeOperation = "destination-out";
      ctx.drawImage(src, 0, 0);
    } else {
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(src, 0, 0);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  return {
    resize(w, h) {
      canvas.width = w;
      canvas.height = h;
    },
    render(slots, t) {
      const w = canvas.width;
      const h = canvas.height;
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, w, h);
      slots.forEach((s, i) => {
        const draw = SCENES[s.scene];
        if (!draw) return;
        const L = layer(i);
        if (L.width !== w || L.height !== h) {
          L.width = w;
          L.height = h;
        }
        const lc = L.getContext("2d");
        lc.setTransform(1, 0, 0, 1, 0, 0);
        lc.clearRect(0, 0, w, h);
        draw(lc, w, h, s.params, t);
        compose(s.blend, L, s.opacity);
      });
    },
    destroy() {
      layers.length = 0;
    },
  };
}
