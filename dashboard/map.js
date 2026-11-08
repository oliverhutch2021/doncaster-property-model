// Comparables map (version 33): a street map drawn from OS OpenMap Local and OS Open Greenspace (src/basemap.py, one
// dataset per postcode district, map_<district>), with the comparable sales on it. Drag to move; +/− or Ctrl + scroll
// (a pinch on a phone or trackpad) to zoom. Shapes are kept in metres around the property, so zooming only rescales them.
window.DPM_MAP = (h) => {
  const { gbp, tip, rows } = h;
  const R = 111320, OUT = 3, IN = 40;          // metres per degree of latitude; zoom out to 1/3 of the first view, in 40 times
  const ROAD_M = { M: 14, P: 11, A: 10, B: 9, m: 8, l: 6, x: 4 };          // drawn widths in metres, by OS road class
  const MAJOR = new Set(['M', 'P', 'A']);
  const S = { key: null, base: null, t: null, svg: null };
  const decoded = new Map();
  let boxes = null;

  // Google encoded polyline (latitude, longitude, 5 decimals) to [lon, lat] pairs
  const decode = (s) => {
    const out = []; let i = 0, lat = 0, lon = 0;
    while (i < s.length) {
      for (let j = 0; j < 2; j++) {
        let b, sh = 0, r = 0;
        do { b = s.charCodeAt(i++) - 63; r |= (b & 0x1f) << sh; sh += 5; } while (b >= 0x20);
        const d = r & 1 ? ~(r >> 1) : r >> 1; if (j) lon += d; else lat += d;
      }
      out.push([lon / 1e5, lat / 1e5]);
    }
    return out;
  };
  // a district's shapes, decoded once; named road segments that meet end to end are joined, so a street gets one label
  const shapes = (id) => {
    if (decoded.has(id)) return decoded.get(id);
    const all = [], roads = new Map();
    dash.data(id).data.forEach((r) => {
      const xy = decode(r.p); let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      xy.forEach(([x, y]) => { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; });
      const s = { k: r.k, c: r.c, n: r.n, xy, bb: [x0, y0, x1, y1] }; all.push(s);
      if (r.k === 'r' && r.n) { if (!roads.has(r.n)) roads.set(r.n, []); roads.get(r.n).push(xy); }
    });
    const lines = [];
    roads.forEach((segs, n) => {
      const key = (p) => p[0].toFixed(5) + ',' + p[1].toFixed(5), left = new Set(segs.map((_, i) => i));
      while (left.size) {
        const [i0] = left; left.delete(i0); let line = segs[i0].slice(), grew = true;
        while (grew) {
          grew = false;
          for (const i of left) {
            const s = segs[i], a = key(line[0]), b = key(line[line.length - 1]), c = key(s[0]), d = key(s[s.length - 1]);
            if (b === c) line = line.concat(s.slice(1)); else if (b === d) line = line.concat(s.slice(0, -1).reverse());
            else if (a === d) line = s.concat(line.slice(1)); else if (a === c) line = s.slice(1).reverse().concat(line); else continue;
            left.delete(i); grew = true;
          }
        }
        lines.push({ n, xy: line });
      }
    });
    const res = { all, lines }; decoded.set(id, res); return res;
  };
  // the extent of each postcode district with a map (those the comparables cover, as in src/basemap.py), from the
  // postcode centroids, to know which districts a view needs
  const districtBoxes = () => {
    if (boxes) return boxes; const b = new Map(), have = new Set(rows('comps').map((r) => String(r.postcode).split(' ')[0]));
    rows('postcodes').forEach((r) => {
      const d = r.postcode.split(' ')[0], la = +r.lat, lo = +r.lon; if (!isFinite(la) || !have.has(d)) return;
      const o = b.get(d) || [Infinity, Infinity, -Infinity, -Infinity];
      b.set(d, [Math.min(o[0], lo), Math.min(o[1], la), Math.max(o[2], lo), Math.max(o[3], la)]);
    });
    return (boxes = b.size ? b : null);
  };
  const nice = (m) => { const p = 10 ** Math.floor(Math.log10(m)), f = m / p; return (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p; };

  const draw = (v, list) => {
    const box = document.querySelector('#comps-map'); if (!box) return;
    if (!list.length) { box.querySelectorAll('svg, .map-ui').forEach((n) => n.remove()); S.key = null; return; }
    const W = Math.max(260, box.clientWidth), H = Math.max(300, box.clientHeight), kx = Math.cos(v.lat * Math.PI / 180);
    const P = (lon, lat) => [(lon - v.lon) * kx * R, (v.lat - lat) * R];
    const pts = list.map((r) => ({ ...r, xy: P(r.lonN, r.latN) }));
    const ext = Math.max(150, d3.max(pts, (p) => Math.max(Math.abs(p.xy[0]), Math.abs(p.xy[1])))) * 1.15;
    const reach = ext * OUT * 1.2, s0 = Math.min(W, H) / 2 / ext;
    const dl = reach / (kx * R), dla = reach / R, view = [v.lon - dl, v.lat - dla, v.lon + dl, v.lat + dla];
    const B = districtBoxes(), pad = 0.02;
    const ids = B ? [...B].filter(([, b]) => b[0] - pad < view[2] && b[2] + pad > view[0] && b[1] - pad < view[3] && b[3] + pad > view[1]).map(([d]) => 'map_' + d) : [];
    const st = ids.map((id) => dash.data(id).status);
    const base = JSON.stringify([v.lat, v.lon, pts.map((p) => p.postcode + p.date + p.priceN)]);
    const key = JSON.stringify([base, W, H, st, dash.colors[0]]);
    if (key === S.key && box.querySelector('svg')) return;          // nothing changed: keep the map where the viewer left it
    if (base !== S.base) S.t = null;
    S.key = key; S.base = base;
    box.querySelectorAll('svg, .map-ui').forEach((n) => n.remove());

    // ---- shapes in reach, one path per kind (and per class for roads) ----
    const by = new Map(), lines = [], named = [];
    const inView = (bb) => bb[0] < view[2] && bb[2] > view[0] && bb[1] < view[3] && bb[3] > view[1];
    ids.forEach((id, i) => {
      if (st[i] !== 'ok') return; const D = shapes(id);
      D.all.forEach((s) => {
        if (!inView(s.bb)) return;
        const g = s.k === 'r' ? 'r' + s.c : s.k, closed = s.k !== 'r' && s.k !== 't' && s.k !== 'l';
        const d = 'M' + s.xy.map(([x, y]) => P(x, y).map((c) => c.toFixed(1)).join(',')).join('L') + (closed ? 'Z' : '');
        if (!by.has(g)) by.set(g, []); by.get(g).push(d);
        if (s.n && (s.k === 'g' || s.k === 's')) named.push({ n: s.n, xy: s.xy.map(([x, y]) => P(x, y)) });
      });
      D.lines.forEach((l) => { if (l.xy.some(([x, y]) => x > view[0] && x < view[2] && y > view[1] && y < view[3])) lines.push({ n: l.n, xy: l.xy.map(([x, y]) => P(x, y)) }); });
    });
    const svg = d3.select(box).append('svg').attr('class', 'map').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
      .attr('aria-label', `Street map of the ${pts.length} comparable sales around this property`);
    svg.append('rect').attr('class', 'land').attr('width', W).attr('height', H);
    const world = svg.append('g'), labels = svg.append('g').attr('class', 'map-labels'), marks = svg.append('g');
    'gwsalbit'.split('').forEach((k) => { if (by.has(k)) world.append('path').attr('class', 'k-' + k).attr('d', by.get(k).join('')); });
    ['x', 'l', 'm', 'B', 'A', 'P', 'M'].forEach((c) => { if (by.has('r' + c)) world.append('path').attr('class', 'k-r' + (MAJOR.has(c) ? ' major' : '')).attr('stroke-width', ROAD_M[c]).attr('d', by.get('r' + c).join('')); });

    // ---- comparables (screen space, so they stay the same size); sales at one postcode share a centroid, so spread them ----
    const grp = d3.group(pts, (p) => p.xy.map((c) => c.toFixed(0)).join(','));
    grp.forEach((g) => {
      const home = Math.hypot(g[0].xy[0], g[0].xy[1]) < 5, rad = home ? 17 : 9;                     // around the property's own ring, or among themselves
      g.forEach((p, i) => { const a = 2 * Math.PI * i / g.length - Math.PI / 2; p.off = g.length > 1 || home ? [rad * Math.cos(a), rad * Math.sin(a)] : [0, 0]; });
    });
    const col = d3.scaleLinear().domain(d3.extent(pts, (p) => p.today)).range([0.35, 1]), tt = tip(box);
    const me = marks.append('g').attr('class', 'me');
    me.append('circle').attr('r', 11).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2);
    me.append('circle').attr('r', 4).attr('fill', 'var(--color-fg)');
    const dots = marks.selectAll('circle.pt').data(pts).join('circle').attr('class', 'pt').attr('r', 6)
      .attr('fill', dash.colors[0]).attr('fill-opacity', (p) => (isFinite(p.today) ? col(p.today) : 0.5)).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2)
      .on('mousemove', (e, p) => {
        const [x, y] = d3.pointer(e, box);
        tt.show([['t', (p.address ? p.address + ', ' : '') + p.postcode], ['', `${gbp(p.priceN)} (${d3.utcFormat('%b %Y')(new Date(p.date))})`], ['', `${gbp(p.today)} in today's money`],
          ...(isFinite(p.adj) ? [['', `${gbp(p.adj)} like this home`]] : [])], x, y);
      })
      .on('mouseleave', () => tt.hide());
    const scale = svg.append('g').attr('class', 'map-scale').attr('transform', `translate(10,${H - 24})`);
    svg.append('text').attr('class', 'map-attr').attr('x', W - 8).attr('y', H - 8).attr('text-anchor', 'end').text('Contains OS data © Crown copyright 2026');

    // ---- labels: street names along the longest stretch in view, park and school names inside their shape ----
    const place = (t) => {
      labels.selectAll('*').remove(); const ppm = s0 * t.k; if (ppm < 0.45) return;
      const scr = (p) => t.apply([W / 2 + s0 * p[0], H / 2 + s0 * p[1]]), seen = new Map(), taken = [];
      const free = (b) => !taken.some((o) => b[0] < o[2] && o[0] < b[2] && b[1] < o[3] && o[1] < b[3]) && taken.push(b);
      // each street split into on-screen runs without sharp turns, so a name never bends round a corner or leaves the map
      const runs = [], len = (xy) => { let s = 0; for (let i = 1; i < xy.length; i++) s += Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]); return s; };
      lines.forEach((l) => {
        let cur = [];
        const end = () => { if (cur.length > 1) runs.push({ n: l.n, xy: cur, len: len(cur) }); };
        l.xy.map(scr).forEach((q) => {
          if (q[0] < 6 || q[0] > W - 6 || q[1] < 6 || q[1] > H - 22) { end(); cur = []; return; }
          if (cur.length >= 2) {
            const [a, b] = cur.slice(-2), t1 = Math.atan2(b[1] - a[1], b[0] - a[0]), t2 = Math.atan2(q[1] - b[1], q[0] - b[0]);
            if (Math.abs(((t2 - t1 + 3 * Math.PI) % (2 * Math.PI)) - Math.PI) > 0.6) { end(); cur = [b]; }
          }
          cur.push(q);
        });
        end();
      });
      runs.filter((r) => r.len > r.n.length * 6.4 + 14).sort((a, b) => b.len - a.len).forEach((r) => {
        if ((seen.get(r.n) || 0) >= 2 || taken.length > 60) return;
        const xy = r.xy[r.xy.length - 1][0] < r.xy[0][0] ? r.xy.slice().reverse() : r.xy;
        const mid = xy[Math.floor(xy.length / 2)], w = r.n.length * 6.4;
        if (!free([mid[0] - w / 2, mid[1] - 8, mid[0] + w / 2, mid[1] + 8])) return;
        seen.set(r.n, (seen.get(r.n) || 0) + 1);
        const pid = 'mp' + Math.random().toString(36).slice(2, 8);
        labels.append('path').attr('id', pid).attr('d', 'M' + xy.map((q) => q.map((c) => c.toFixed(1)).join(',')).join('L')).attr('fill', 'none');
        labels.append('text').attr('class', 'map-road').attr('dy', 3.5).append('textPath').attr('href', '#' + pid).attr('startOffset', '50%').attr('text-anchor', 'middle').text(r.n);
      });
      named.forEach((s) => {
        const xy = s.xy.map(scr), x = d3.extent(xy, (p) => p[0]), y = d3.extent(xy, (p) => p[1]), w = s.n.length * 6.4;
        if (x[1] - x[0] < w + 10 || y[1] - y[0] < 20 || x[1] < 0 || x[0] > W || y[1] < 0 || y[0] > H) return;
        const cx = (x[0] + x[1]) / 2, cy = (y[0] + y[1]) / 2; if (!free([cx - w / 2, cy - 8, cx + w / 2, cy + 8])) return;
        labels.append('text').attr('class', 'map-place').attr('x', cx).attr('y', cy + 4).attr('text-anchor', 'middle').text(s.n);
      });
    };
    const bar = (t) => {
      const m = nice(90 / (s0 * t.k)), px = m * s0 * t.k; scale.selectAll('*').remove();
      scale.append('path').attr('d', `M0,-5V0H${px.toFixed(1)}V-5`);
      scale.append('text').attr('x', px + 6).attr('y', 0).text(m >= 1000 ? m / 1000 + ' km' : m + ' m');
    };
    const apply = (t, still) => {
      world.attr('transform', `${t} translate(${W / 2},${H / 2}) scale(${s0})`);
      const at = (p) => t.apply([W / 2 + s0 * p[0], H / 2 + s0 * p[1]]);
      me.attr('transform', `translate(${at([0, 0])})`);
      dots.attr('cx', (p) => at(p.xy)[0] + p.off[0]).attr('cy', (p) => at(p.xy)[1] + p.off[1]);
      bar(t); if (still) place(t); else labels.selectAll('*').remove();
    };
    const lim = reach * s0;
    const zoom = d3.zoom().scaleExtent([1 / OUT, IN]).translateExtent([[W / 2 - lim, H / 2 - lim], [W / 2 + lim, H / 2 + lim]]).extent([[0, 0], [W, H]])
      .filter((e) => (e.type === 'wheel' ? e.ctrlKey || e.metaKey : !e.button))
      .on('zoom', (e) => { S.t = e.transform; apply(e.transform, !e.sourceEvent || e.sourceEvent.type === 'end'); })
      .on('end', (e) => apply(e.transform, true));
    svg.call(zoom).on('dblclick.zoom', null);
    svg.on('wheel.hint', (e) => { if (e.ctrlKey || e.metaKey) return; hint.hidden = false; clearTimeout(S.h); S.h = setTimeout(() => { hint.hidden = true; }, 1400); });
    const ui = document.createElement('div'); ui.className = 'map-ui';
    const btn = (txt, label, f) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = txt; b.setAttribute('aria-label', label); b.addEventListener('click', f); ui.appendChild(b); };
    btn('+', 'Zoom in', () => svg.transition().duration(250).call(zoom.scaleBy, 2));
    btn('−', 'Zoom out', () => svg.transition().duration(250).call(zoom.scaleBy, 0.5));
    btn('⤢', 'Fit the comparables', () => svg.transition().duration(300).call(zoom.transform, d3.zoomIdentity));
    const hint = document.createElement('div'); hint.className = 'map-hint'; hint.hidden = true; hint.textContent = 'Use Ctrl + scroll to zoom, or the + and − buttons';
    box.append(ui, hint);
    const wait = st.some((s) => s === 'loading' || s === 'pending'), bad = st.some((s) => s === 'error');
    if (wait || bad || !ids.length) svg.append('text').attr('class', 'map-attr').attr('x', 10).attr('y', 18).text(bad ? 'The street map failed to load' : wait ? 'Loading the street map…' : 'No street map here');
    svg.call(zoom.transform, S.t || d3.zoomIdentity);
  };
  return { draw };
};
