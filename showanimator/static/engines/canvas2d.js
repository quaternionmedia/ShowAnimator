// Canvas 2D engine. Contract: create(canvas) -> { render(slots, t), resize(w, h), destroy() }.
// Each slot is drawn into its own layer, then composited with its blend mode and opacity.
// Scene ids and param keys must match showanimator/engines/canvas2d.py.

const SCENES = {
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
