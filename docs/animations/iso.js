/* Isometric architecture animations: an input travels through a system's
   parts, each stop explained, until it comes out as the output.

   One spec per animation (see SPEC.md). Rendering is a pure function of
   time - ISO.frame(t) draws the moment t seconds in - so the same file
   plays in a browser and renders frame-exact video. No dependencies, no
   network: SVG and plain JavaScript. */
(function () {
  "use strict";
  const W = 1080, H = 1350;
  const SCENE_TOP = 250, SCENE_BOTTOM = 980;
  const COS = Math.cos(Math.PI / 6), SIN = 0.5;
  const NS = "http://www.w3.org/2000/svg";

  const PALETTE = {
    ui: "#6366f1", api: "#0ea5e9", core: "#f59e0b", model: "#a855f7",
    store: "#10b981", guard: "#ef4444", tool: "#14b8a6", ext: "#64748b",
    data: "#22c55e", queue: "#f97316", person: "#3b82f6",
  };

  /* ------------------------------------------------------------ colour */
  function shade(hex, amt) {
    const n = parseInt(hex.slice(1), 16);
    let r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    const f = (c) => Math.max(0, Math.min(255, Math.round(
      amt >= 0 ? c + (255 - c) * amt : c * (1 + amt))));
    r = f(r); g = f(g); b = f(b);
    return "#" + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1);
  }
  function esc(s) {
    return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  const ease = (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /* ----------------------------------------------------- the timeline */
  function plan(spec) {
    const intro = spec.intro ?? 3.2;
    const outro = spec.outro ?? 4.5;
    let t = intro;
    const steps = spec.steps.map((s, i) => {
      const dur = s.dur ?? 3.4;
      const step = { ...s, i, start: t, dur, travel: s.travel ?? 1.0 };
      t += dur;
      return step;
    });
    return { intro, outro, steps, total: t + outro };
  }

  /* ---------------------------------------------------------- geometry */
  function layout(spec) {
    /* Architecture scenes leave a band at the top for each step's inset:
       what happens inside the part, down to the token. */
    const SCENE_TOP = spec.insets ? 560 : 250;
    const nodes = spec.nodes.map((n) => ({ w: 2, d: 2, h: 1, kind: "block",
                                           ...n }));
    let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
    for (const n of nodes) {
      const pts = [[n.x, n.y, 0], [n.x + n.w, n.y, 0], [n.x, n.y + n.d, 0],
                   [n.x + n.w, n.y + n.d, 0], [n.x, n.y, n.h + 1.6]];
      for (const [x, y, z] of pts) {
        const sx = (x - y) * COS, sy = (x + y) * SIN - z;
        minx = Math.min(minx, sx); maxx = Math.max(maxx, sx);
        miny = Math.min(miny, sy); maxy = Math.max(maxy, sy);
      }
    }
    const U = Math.min((W - 140) / (maxx - minx),
                       (SCENE_BOTTOM - SCENE_TOP - 40) / (maxy - miny));
    const ox = W / 2 - ((minx + maxx) / 2) * U;
    const oy = (SCENE_TOP + SCENE_BOTTOM) / 2 - ((miny + maxy) / 2) * U + 10;
    const iso = (x, y, z) => [ox + (x - y) * COS * U, oy + (x + y) * SIN * U
                                                      - z * U];
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    const centre = (n) => [n.x + n.w / 2, n.y + n.d / 2];
    const edges = (spec.edges || []).map((e) => {
      const a = byId[e.from], b = byId[e.to];
      const [ax, ay] = centre(a), [bx, by] = centre(b);
      /* Along the grid, as a conveyor runs: across x, then along y. */
      const pts = e.straight ? [[ax, ay], [bx, by]]
        : [[ax, ay], [bx, ay], [bx, by]];
      return { ...e, pts, key: e.from + ">" + e.to };
    });
    return { nodes, byId, edges, iso, U, top: SCENE_TOP };
  }

  function polyLen(pts) {
    let L = 0;
    for (let i = 1; i < pts.length; i++) {
      L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    }
    return L;
  }
  function along(pts, p) {
    const L = polyLen(pts) * p;
    let acc = 0;
    for (let i = 1; i < pts.length; i++) {
      const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
      if (acc + seg >= L || i === pts.length - 1) {
        const q = seg ? (L - acc) / seg : 0;
        return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * q,
                pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * q];
      }
      acc += seg;
    }
    return pts[pts.length - 1];
  }

  /* ----------------------------------------------------------- drawing */
  function poly(iso, pts, fill, stroke, extra = "") {
    return `<polygon points="${pts.map((p) => iso(...p).map((v) => v.toFixed(1))
      .join(",")).join(" ")}" fill="${fill}" stroke="${stroke}"
      stroke-width="1.2" stroke-linejoin="round" ${extra}/>`;
  }

  function block(iso, n, lift, colour, glow) {
    const { x, y, w, d } = n;
    const h = n.h + lift;
    const z0 = lift;
    const top = shade(colour, 0.35), left = colour, right = shade(colour, -0.22);
    const edge = shade(colour, -0.45);
    let out = "";
    if (glow > 0) {
      out += poly(iso, [[x - 0.25, y - 0.25, 0], [x + w + 0.25, y - 0.25, 0],
                        [x + w + 0.25, y + d + 0.25, 0], [x - 0.25, y + d + 0.25, 0]],
                  colour, "none", `opacity="${(0.28 * glow).toFixed(2)}"`);
    }
    if (n.kind === "cyl") return out + cylinder(iso, n, z0, h, top, left, edge);
    if (n.kind === "gate") return out + gate(iso, n, z0, h, top, left, right, edge);
    out += poly(iso, [[x, y + d, h], [x + w, y + d, h], [x + w, y + d, z0],
                      [x, y + d, z0]], left, edge);
    out += poly(iso, [[x + w, y, h], [x + w, y + d, h], [x + w, y + d, z0],
                      [x + w, y, z0]], right, edge);
    out += poly(iso, [[x, y, h], [x + w, y, h], [x + w, y + d, h],
                      [x, y + d, h]], top, edge);
    /* window strips on the front, so a block reads as a building */
    if (n.kind !== "flat" && n.h >= 0.8) {
      const rows = Math.max(1, Math.round(n.h * 1.5));
      for (let r = 0; r < rows; r++) {
        const zz = z0 + (r + 0.35) * (n.h / rows);
        out += poly(iso, [[x + 0.25, y + d, zz + 0.18], [x + w - 0.25, y + d,
          zz + 0.18], [x + w - 0.25, y + d, zz], [x + 0.25, y + d, zz]],
          shade(colour, 0.55), "none", 'opacity="0.55"');
      }
    }
    return out;
  }

  function ellipse(iso, cx, cy, r, z, n = 28) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2;
      pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r, z]);
    }
    return pts;
  }

  function cylinder(iso, n, z0, h, top, side, edge) {
    const cx = n.x + n.w / 2, cy = n.y + n.d / 2, r = Math.min(n.w, n.d) / 2;
    const roof = ellipse(iso, cx, cy, r, h);
    /* The side the viewer sees: the half facing +x and +y, which in this
       projection runs from -45 to 135 degrees. */
    const front = [];
    for (let i = 0; i <= 24; i++) {
      const a = (-45 + (180 * i) / 24) * Math.PI / 180;
      front.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
    const sidePts = [...front.map(([px, py]) => [px, py, z0]),
                     ...front.slice().reverse().map(([px, py]) => [px, py, h])];
    let out = poly(iso, sidePts, side, edge);
    for (let k = 1; k <= 2; k++) {
      const zz = z0 + (h - z0) * (k / 3);
      const ring = front.map(([px, py]) => iso(px, py, zz));
      out += `<polyline points="${ring.map((p) => p.map((v) => v.toFixed(1))
        .join(",")).join(" ")}" fill="none" stroke="${shade(side, 0.4)}"
        stroke-width="1.5" opacity="0.7"/>`;
    }
    out += poly(iso, roof, top, edge);
    return out;
  }

  function gate(iso, n, z0, h, top, left, right, edge) {
    /* two pillars and a beam: a checkpoint everything passes through */
    const { x, y, w, d } = n;
    const p = 0.45;
    let out = "";
    for (const px of [x, x + w - p]) {
      out += poly(iso, [[px, y + d, h], [px + p, y + d, h], [px + p, y + d, z0],
                        [px, y + d, z0]], left, edge);
      out += poly(iso, [[px + p, y, h], [px + p, y + d, h], [px + p, y + d, z0],
                        [px + p, y, z0]], right, edge);
      out += poly(iso, [[px, y, h], [px + p, y, h], [px + p, y + d, h],
                        [px, y + d, h]], top, edge);
    }
    out += poly(iso, [[x, y + d, h + 0.35], [x + w, y + d, h + 0.35],
                      [x + w, y + d, h], [x, y + d, h]], left, edge);
    out += poly(iso, [[x, y, h + 0.35], [x + w, y, h + 0.35],
                      [x + w, y + d, h + 0.35], [x, y + d, h + 0.35]], top, edge);
    out += poly(iso, [[x + p, y + d * 0.5, 0.02], [x + w - p, y + d * 0.5, 0.02],
                      [x + w - p, y + d * 0.5 + 0.08, 0.02],
                      [x + p, y + d * 0.5 + 0.08, 0.02]], shade(left, 0.3), "none",
                'opacity="0.8"');
    return out;
  }

  function label(iso, n, lift, active, visited, U) {
    const [cx, cy] = [n.x + n.w / 2, n.y + n.d / 2];
    const top = n.kind === "gate" ? n.h + 0.35 : n.h;
    const [sx, sy] = iso(cx, cy, top + lift + 0.15);
    const size = Math.max(15, Math.min(22, U * 0.38));
    const name = esc(n.label);
    const wpx = Math.max(name.length * size * 0.56 + (n.icon ? size * 1.5 : 0),
                         60) + 22;
    const fill = active ? "#111827" : "#ffffff";
    const ink = active ? "#ffffff" : "#111827";
    let out = `<g transform="translate(${sx.toFixed(1)},${(sy - 18).toFixed(1)})">
      <rect x="${(-wpx / 2).toFixed(1)}" y="${-size - 6}" width="${wpx.toFixed(1)}"
        height="${size + 14}" rx="${(size + 14) / 2}" fill="${fill}"
        stroke="#0f172a" stroke-opacity="0.18" filter="url(#sh)"/>
      <text x="0" y="0" text-anchor="middle" font-size="${size}"
        font-weight="700" fill="${ink}">${n.icon ? n.icon + " " : ""}${name}</text>`;
    if (visited && !active) {
      out += `<circle cx="${(wpx / 2 - 2).toFixed(1)}" cy="${-size - 4}" r="10"
        fill="#16a34a"/><path d="M${(wpx / 2 - 7).toFixed(1)} ${-size - 4}
        l4 4 l7 -8" stroke="#fff" stroke-width="2.4" fill="none"/>`;
    }
    if (n.sub) {
      out += `<text x="0" y="${size + 10}" text-anchor="middle"
        font-size="${Math.round(size * 0.72)}" fill="#475569">${esc(n.sub)}</text>`;
    }
    return out + "</g>";
  }

  function conveyor(iso, e, t, active, done) {
    const pts = e.pts.map(([x, y]) => iso(x, y, 0.02));
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " "
                                 + p[1].toFixed(1)).join(" ");
    const base = active ? "#0f172a" : done ? "#64748b" : "#cbd5e1";
    return `<path d="${d}" fill="none" stroke="${base}" stroke-width="${active
      ? 9 : 7}" stroke-linecap="round" stroke-linejoin="round" opacity="${active
      ? 0.9 : 0.7}"/>
      <path d="${d}" fill="none" stroke="#ffffff" stroke-width="2.2"
        stroke-dasharray="6 12" stroke-dashoffset="${(-t * 42).toFixed(1)}"
        stroke-linecap="round" opacity="${active ? 0.95 : 0.55}"/>`;
  }

  function packet(iso, at, text, colour, U) {
    const [x, y] = at;
    const s = 0.42;
    const n = { x: x - s / 2, y: y - s / 2, w: s, d: s, h: s, kind: "flat" };
    let out = block(iso, n, 0.25, colour, 0);
    const [px, py] = iso(x, y, 0.25 + s + 0.5);
    const size = 17;
    const t = esc(text);
    const w = Math.min(t.length * size * 0.55 + 22, 460);
    /* kept inside the frame: a block at the edge pushed its label off it */
    const cx = clamp(px, w / 2 + 8, W - w / 2 - 8);
    out += `<g transform="translate(${cx.toFixed(1)},${py.toFixed(1)})">
      <rect x="${(-w / 2).toFixed(1)}" y="-26" width="${w.toFixed(1)}" height="32"
        rx="16" fill="${colour}" filter="url(#sh)"/>
      <text x="0" y="-5" text-anchor="middle" font-size="${size}"
        font-weight="700" fill="#fff" font-family="Consolas, monospace">${t}</text></g>`;
    return out;
  }

  /* text wrapped to a width, as <tspan>s */
  function wrap(text, width, size) {
    const per = Math.max(10, Math.floor(width / (size * 0.52)));
    const words = String(text ?? "").split(/\s+/);
    const lines = [];
    let cur = "";
    for (const w of words) {
      if ((cur + " " + w).trim().length > per) { if (cur) lines.push(cur); cur = w; }
      else cur = (cur + " " + w).trim();
    }
    if (cur) lines.push(cur);
    return lines;
  }
  function tspans(lines, x, lh) {
    return lines.map((l, i) => `<tspan x="${x}" dy="${i ? lh : 0}">${esc(l)}</tspan>`)
      .join("");
  }

  function card(x, y, w, kind, head, body, colour, alpha) {
    const lines = wrap(body, w - 40, 22).slice(0, 5);
    const h = 64 + lines.length * 30;
    return `<g opacity="${alpha.toFixed(2)}">
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18" fill="#ffffff"
        stroke="${colour}" stroke-width="3" filter="url(#sh)"/>
      <rect x="${x}" y="${y}" width="${w}" height="40" rx="18" fill="${colour}"/>
      <rect x="${x}" y="${y + 22}" width="${w}" height="18" fill="${colour}"/>
      <text x="${x + 20}" y="${y + 28}" font-size="18" font-weight="800"
        fill="#fff" letter-spacing="1.5">${esc(kind)} · ${esc(head)}</text>
      <text x="${x + 20}" y="${y + 74}" font-size="22" fill="#0f172a"
        font-family="Consolas, monospace">${tspans(lines, x + 20, 30)}</text></g>`;
  }

  /* ------------------------------------------------------------ insets */
  /* What happens inside a part, drawn in the band above the scene. `p` runs
     0..1 across the step, so rows, tokens and blocks arrive in order. */
  const IX = 40, IY = 222, IW = W - 80, IH = 300;
  function inset(spec, alpha, p, accent) {
    let body = "";
    const x0 = IX + 24, y0 = IY + 64, w = IW - 48;
    if (spec.kind === "bars") {
      const rows = spec.rows;
      const max = Math.max(spec.limit || 0, ...rows.map((r) => r.value)) || 1;
      const lw = 230, bw = w - lw - 90;
      const rh = Math.min(30, (IH - 84) / rows.length);
      rows.forEach((r, i) => {
        const shown = clamp(p * rows.length * 1.15 - i, 0, 1);
        if (shown <= 0) return;
        const y = y0 + i * rh;
        const len = (r.value / max) * bw * ease(shown);
        body += `<text x="${x0}" y="${y + rh * 0.62}" font-size="${Math.min(18,
          rh * 0.62)}" fill="#0f172a">${esc(r.label)}</text>
          <rect x="${x0 + lw}" y="${y + 4}" width="${len.toFixed(1)}"
            height="${rh - 9}" rx="4" fill="${r.color || accent}"
            opacity="${r.faded ? 0.35 : 0.9}"/>
          <text x="${(x0 + lw + len + 8).toFixed(1)}" y="${y + rh * 0.62}"
            font-size="${Math.min(17, rh * 0.6)}" font-weight="700"
            fill="#0f172a" font-family="Consolas, monospace">${esc(String(
              r.value))}${r.tag ? " " + esc(r.tag) : ""}</text>`;
      });
      if (spec.limit) {
        const lx = x0 + lw + (spec.limit / max) * bw;
        body += `<line x1="${lx.toFixed(1)}" y1="${y0 - 6}" x2="${lx.toFixed(1)}"
          y2="${y0 + rows.length * rh}" stroke="#ef4444" stroke-width="2.5"
          stroke-dasharray="6 5"/><text x="${lx.toFixed(1)}" y="${y0 - 12}"
          text-anchor="end" font-size="15" font-weight="700" fill="#ef4444">${
          esc(spec.limitLabel || "limit " + spec.limit)}</text>`;
      }
    } else if (spec.kind === "tokens") {
      const items = spec.items;
      const n = Math.floor(clamp(p * 1.1, 0, 1) * items.length);
      let x = x0, y = y0 + 4;
      for (let i = 0; i < n; i++) {
        const tok = String(items[i]);
        const tw = Math.max(26, tok.length * 10.5 + 14);
        if (x + tw > x0 + w) { x = x0; y += 40; }
        if (y > IY + IH - 40) break;
        body += `<rect x="${x}" y="${y}" width="${tw}" height="32" rx="6"
          fill="${i === n - 1 ? accent : "#e0e7ff"}" stroke="#c7d2fe"/>
          <text x="${x + tw / 2}" y="${y + 22}" text-anchor="middle"
          font-size="17" font-family="Consolas, monospace" fill="${i === n - 1
            ? "#fff" : "#1e1b4b"}">${esc(tok.replace(/ /g, "·"))}</text>`;
        x += tw + 6;
      }
      body += `<text x="${x0 + w}" y="${IY + 30}" text-anchor="end"
        font-size="17" font-weight="700" fill="${accent}"
        font-family="Consolas, monospace">${n} / ${items.length} tokens</text>`;
    } else if (spec.kind === "timeline") {
      const lanes = spec.lanes;
      const max = spec.max || Math.max(...spec.blocks.map((b) => b.to));
      const lw = 120, bw = w - lw - 10;
      const lh = Math.min(56, (IH - 100) / lanes.length);
      lanes.forEach((ln, i) => {
        const y = y0 + i * lh;
        body += `<text x="${x0}" y="${y + lh * 0.6}" font-size="18"
          font-weight="700" fill="#0f172a">${esc(ln)}</text>
          <rect x="${x0 + lw}" y="${y + 4}" width="${bw}" height="${lh - 12}"
            rx="5" fill="#f1f5f9"/>`;
      });
      const order = spec.blocks.length;
      spec.blocks.forEach((b, j) => {
        const shown = clamp(p * order * 1.1 - j, 0, 1);
        if (shown <= 0) return;
        const lane = lanes.indexOf(b.lane);
        const y = y0 + lane * lh;
        const bx = x0 + lw + (b.from / max) * bw;
        const bwid = ((b.to - b.from) / max) * bw * ease(shown);
        body += `<rect x="${bx.toFixed(1)}" y="${y + 4}" width="${bwid.toFixed(1)}"
          height="${lh - 12}" rx="5" fill="${b.color || accent}"/>
          ${shown > 0.6 && bwid > String(b.label || "").length * 9 + 14 ? `<text x="${(bx + 8).toFixed(1)}" y="${y + lh * 0.6}"
          font-size="15" font-weight="700" fill="#fff">${esc(b.label || "")}</text>`
          : ""}`;
      });
      if (spec.axis) {
        body += `<text x="${x0 + lw}" y="${y0 + lanes.length * lh + 18}"
          font-size="15" fill="#64748b">${esc(spec.axis)}</text>`;
      }
    } else if (spec.kind === "focus") {
      const c = spec.colour || accent;
      body += `<rect x="${x0}" y="${y0 - 8}" width="150" height="150" rx="22"
          fill="${c}" opacity="0.15"/>
        <text x="${x0 + 75}" y="${y0 + 92}" text-anchor="middle"
          font-size="72">${esc(spec.icon || "")}</text>
        <text x="${x0 + 180}" y="${y0 + 26}" font-size="30" font-weight="800"
          fill="#0f172a">${esc(spec.label || "")}</text>
        <text x="${x0 + 180}" y="${y0 + 60}" font-size="20"
          fill="#475569">${esc(spec.sub || "")}</text>
        <rect x="${x0 + 180}" y="${y0 + 82}" width="${Math.min(w - 200,
          String(spec.value || "").length * 15 + 40)}" height="52" rx="12"
          fill="${c}"/>
        <text x="${x0 + 200}" y="${y0 + 116}" font-size="24" font-weight="700"
          fill="#fff" font-family="Consolas, monospace">${esc(
            String(spec.value || "").slice(0, 52))}</text>
        ${spec.data ? `<text x="${x0 + 180}" y="${y0 + 176}" font-size="19"
          fill="#0f172a" font-family="Consolas, monospace">${esc(
            spec.data.slice(0, 70))}</text>` : ""}`;
    } else if (spec.kind === "code") {
      const lines = spec.lines;
      const n = Math.ceil(clamp(p * 1.2, 0, 1) * lines.length);
      body += `<rect x="${x0}" y="${y0 - 8}" width="${w}" height="${IH - 80}"
        rx="10" fill="#0f172a"/>`;
      lines.slice(0, n).forEach((ln, i) => {
        body += `<text x="${x0 + 18}" y="${y0 + 22 + i * 28}" font-size="18"
          font-family="Consolas, monospace" fill="${ln.startsWith("#")
            ? "#94a3b8" : "#a5f3fc"}">${esc(ln.slice(0, 84))}</text>`;
      });
    }
    return `<g opacity="${alpha.toFixed(2)}"><rect x="${IX}" y="${IY}"
      width="${IW}" height="${IH}" rx="18" fill="#ffffff" stroke="#e2e8f0"
      stroke-width="2" filter="url(#sh)"/>
      <rect x="${IX}" y="${IY}" width="8" height="${IH}" rx="4" fill="${accent}"/>
      <text x="${IX + 24}" y="${IY + 34}" font-size="20" font-weight="800"
        fill="#0f172a">${esc(spec.title || "")}</text>${body}
      ${spec.note ? `<text x="${IX + 24}" y="${IY + IH - 16}" font-size="16"
        fill="#64748b">${esc(spec.note)}</text>` : ""}</g>`;
  }

  /* ------------------------------------------------------------ a frame */
  function frame(spec, L, P, t) {
    const { iso, U } = L;
    const accent = spec.accent || "#4338ca";
    const step = P.steps.find((s) => t >= s.start && t < s.start + s.dur)
      || (t >= P.total - P.outro ? null : null);
    const doneUpTo = P.steps.filter((s) => t >= s.start + Math.min(s.travel,
                                                                  s.dur)).length;
    const visited = new Set(P.steps.slice(0, doneUpTo).map((s) => s.node));
    const activeNode = step && t >= step.start + step.travel ? step.node : null;
    const travelling = step && t < step.start + step.travel ? step : null;
    const doneEdges = new Set();
    for (const s of P.steps) {
      if (t >= s.start + s.travel) (s.via || []).forEach((k) => doneEdges.add(k));
    }

    let svg = `<svg xmlns="${NS}" viewBox="0 0 ${W} ${H}" width="${W}"
      height="${H}" font-family="Segoe UI, Inter, Arial, sans-serif">
      <defs><filter id="sh" x="-20%" y="-20%" width="140%" height="160%">
        <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#0f172a"
          flood-opacity="0.18"/></filter>
        <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#f8fafc"/><stop offset="1"
          stop-color="#e2e8f0"/></linearGradient>
        <pattern id="grid" width="${(COS * U).toFixed(1)}"
          height="${(SIN * U).toFixed(1)}" patternUnits="userSpaceOnUse">
          <path d="M0 ${(SIN * U).toFixed(1)} L${(COS * U).toFixed(1)} 0"
            stroke="#cbd5e1" stroke-width="0.6" opacity="0.6"/></pattern></defs>
      <rect width="${W}" height="${H}" fill="url(#bg)"/>
      <rect y="${L.top - 30}" width="${W}" height="${SCENE_BOTTOM - L.top + 60}"
        fill="url(#grid)" opacity="0.7"/>`;

    /* header */
    svg += `<rect width="${W}" height="200" fill="#0f172a"/>
      <rect y="196" width="${W}" height="6" fill="${accent}"/>
      <text x="56" y="62" font-size="22" font-weight="700" fill="${shade(accent,
        0.55)}" letter-spacing="3">${esc((spec.repo || "").toUpperCase())}${
        spec.project ? "  ·  " + esc(spec.project.toUpperCase()) : ""}</text>
      <text x="56" y="116" font-size="44" font-weight="800" fill="#fff">${
        esc(spec.title)}</text>
      <text x="56" y="160" font-size="23" fill="#cbd5e1">${tspans(wrap(
        spec.subtitle, W - 112, 23).slice(0, 1), 56, 28)}</text>`;

    /* conveyors under everything */
    for (const e of L.edges) {
      const active = travelling && (travelling.via || []).includes(e.key);
      svg += conveyor(iso, e, t, active, doneEdges.has(e.key));
    }
    /* blocks, back to front */
    const order = L.nodes.slice().sort((a, b) => (a.x + a.y + a.w / 2 + a.d / 2)
                                                 - (b.x + b.y + b.w / 2 + b.d / 2));
    for (const n of order) {
      const isActive = n.id === activeNode;
      let lift = 0, glow = 0;
      if (isActive) {
        const k = clamp((t - step.start - step.travel) / 0.35, 0, 1);
        lift = 0.28 * ease(k); glow = ease(k);
      }
      const colour = PALETTE[n.role] || n.color || "#64748b";
      svg += block(iso, n, lift, colour, glow);
      svg += label(iso, n, lift, isActive, visited.has(n.id), U);
    }
    /* the travelling input */
    if (travelling) {
      const p = ease(clamp((t - travelling.start) / travelling.travel, 0, 1));
      const route = [];
      for (const k of travelling.via || []) {
        const e = L.edges.find((x) => x.key === k);
        if (!e) continue;
        const pts = e.reverse ? e.pts.slice().reverse() : e.pts;
        route.push(...(route.length ? pts.slice(1) : pts));
      }
      if (route.length >= 2) {
        svg += packet(iso, along(route, p), travelling.packet || "",
                      PALETTE[travelling.role] || accent, U);
      }
    } else if (step && step.packet && activeNode) {
      const n = L.byId[activeNode];
      svg += packet(iso, [n.x + n.w / 2, n.y + n.d / 2 + n.d / 2 + 0.35],
                    step.packet, PALETTE[step.role] || accent, U);
    }

    /* the inside of the step: an inset above the scene */
    if (step && (step.inset || spec.insets)) {
      const k = clamp((t - step.start - step.travel * 0.6) / 0.45, 0, 1);
      const span = Math.max(0.6, step.dur - step.travel - 0.6);
      const p = clamp((t - step.start - step.travel) / span, 0, 1);
      /* A step with nothing of its own to show inside shows the part in
         focus and what is passing through it, so the band is never empty. */
      const n = L.byId[step.node];
      svg += inset(step.inset || { kind: "focus", title: "At this part",
        icon: n.icon, label: n.label, sub: n.sub, value: step.packet,
        data: step.data, colour: PALETTE[n.role] || accent }, k, p, accent);
    }

    /* input and output */
    const inA = clamp((t - 0.4) / 0.6, 0, 1) * (t < P.intro + 1.2 ? 1
      : clamp(1 - (t - P.intro - 1.2) / 0.6, 0, 1));
    if (inA > 0) {
      svg += card(56, 236, 520, "INPUT", spec.input.label, spec.input.text,
                  "#2563eb", inA);
    }
    const outStart = P.total - P.outro;
    const outA = clamp((t - outStart) / 0.6, 0, 1);

    /* caption panel */
    svg += `<rect x="0" y="1000" width="${W}" height="${H - 1000}" fill="#ffffff"/>
      <rect x="0" y="1000" width="${W}" height="2" fill="#e2e8f0"/>`;
    if (step) {
      const k = clamp((t - step.start) / 0.4, 0, 1);
      const body = wrap(step.text, W - 112, 25).slice(0, 5);
      svg += `<g opacity="${k.toFixed(2)}">
        <text x="56" y="1052" font-size="20" font-weight="800"
          fill="${accent}" letter-spacing="2">STEP ${step.i + 1} OF ${
          P.steps.length}</text>
        <text x="56" y="1096" font-size="34" font-weight="800"
          fill="#0f172a">${esc(step.title)}</text>
        <text x="56" y="1142" font-size="25" fill="#334155">${tspans(body, 56,
          34)}</text></g>`;
      if (step.data) {
        svg += `<g opacity="${k.toFixed(2)}"><rect x="${W - 56 - 400}" y="1030"
          width="400" height="44" rx="10" fill="#0f172a"/>
          <text x="${W - 56 - 384}" y="1059" font-size="18" fill="#a5f3fc"
          font-family="Consolas, monospace">${esc(step.data.slice(0, 38))}</text>
          </g>`;
      }
    } else if (t < P.intro) {
      svg += `<text x="56" y="1060" font-size="20" font-weight="800"
        fill="${accent}" letter-spacing="2">HOW IT WORKS</text>
        <text x="56" y="1104" font-size="30" font-weight="700" fill="#0f172a">${
        tspans(wrap(spec.intro_text || "Follow the input through every part "
          + "until it comes out as the answer.", W - 112, 30).slice(0, 3),
          56, 40)}</text>`;
    } else {
      const lines = wrap(spec.summary || "", W - 112, 26).slice(0, 4);
      svg += `<g opacity="${outA.toFixed(2)}"><text x="56" y="1052"
        font-size="20" font-weight="800" fill="#16a34a" letter-spacing="2">
        FROM INPUT TO OUTPUT</text>
        <text x="56" y="1100" font-size="27" fill="#0f172a">${tspans(lines, 56,
          38)}</text></g>`;
    }
    if (outA > 0) {
      svg += card(W - 56 - 560, 236, 560, "OUTPUT", spec.output.label,
                  spec.output.text, "#16a34a", outA);
    }

    /* progress and footer */
    const prog = clamp(t / P.total, 0, 1);
    svg += `<rect x="56" y="${H - 58}" width="${W - 112}" height="6" rx="3"
        fill="#e2e8f0"/>
      <rect x="56" y="${H - 58}" width="${((W - 112) * prog).toFixed(1)}"
        height="6" rx="3" fill="${accent}"/>
      <text x="56" y="${H - 22}" font-size="18" fill="#64748b">${esc(
        spec.footer || "github.com/hammasbuilds")}</text>
      <text x="${W - 56}" y="${H - 22}" font-size="18" fill="#64748b"
        text-anchor="end">${esc(spec.facts || "")}</text>`;
    return svg + "</svg>";
  }

  /* ------------------------------------------------------------ player */
  function mount(spec, host) {
    const L = layout(spec);
    const P = plan(spec);
    const stage = document.createElement("div");
    stage.className = "iso-stage";
    host.append(stage);
    let t = 0, playing = !/[?&]paused/.test(location.search), last = null;
    const draw = (time) => { stage.innerHTML = frame(spec, L, P, time); };
    const api = {
      total: P.total, steps: P.steps,
      frame(time) { t = time; draw(time); },
      play() { playing = true; last = null; requestAnimationFrame(loop); },
      pause() { playing = false; },
      seek(time) { t = clamp(time, 0, P.total); draw(t); },
      get t() { return t; }, get playing() { return playing; },
    };
    function loop(now) {
      if (!playing) return;
      if (last !== null) {
        t += (now - last) / 1000;
        if (t > P.total + 1.5) t = 0;
      }
      last = now;
      draw(Math.min(t, P.total));
      if (api.ontick) api.ontick(t);
      requestAnimationFrame(loop);
    }
    draw(0);
    if (playing) requestAnimationFrame(loop);
    return api;
  }

  window.ISO = { mount, frame, plan, layout, W, H };
})();
