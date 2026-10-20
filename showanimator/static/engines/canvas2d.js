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
};

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
