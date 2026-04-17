// Frontier Web Worker
// Receives frontier points + scale params, computes pixel coords + colors off main thread.
// Sends progress every 1000 points, then 'done' with full result.

function sharpeToColor(sharpe, min, max) {
  const t = max === min ? 0.5 : Math.max(0, Math.min(1, (sharpe - min) / (max - min)));
  const r = Math.round(220 * (1 - t) + 22 * t);
  const g = Math.round(38 * (1 - t) + 163 * t);
  const b = Math.round(38 * (1 - t) + 38 * t);
  return `rgb(${r},${g},${b})`;
}

function linearScale(domain, range) {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  return (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
}

self.onmessage = function (e) {
  const { frontier, xMin, xMax, yMin, yMax, innerW, innerH, margin, minSharpe, maxSharpe } = e.data;

  const xScale = linearScale([xMin, xMax], [0, innerW]);
  const yScale = linearScale([yMin, yMax], [innerH, 0]);

  const BATCH = 1000;
  // Each point: cx, cy, r, g, b  → 5 floats
  const result = new Float32Array(frontier.length * 5);

  for (let i = 0; i < frontier.length; i++) {
    const p = frontier[i];
    const cx = margin.left + xScale(p.vol);
    const cy = margin.top + yScale(p.ret);
    const color = sharpeToColor(p.sharpe, minSharpe, maxSharpe);
    // parse rgb(r,g,b)
    const m = color.match(/(\d+),(\d+),(\d+)/);
    result[i * 5]     = cx;
    result[i * 5 + 1] = cy;
    result[i * 5 + 2] = m ? parseInt(m[1]) : 128;
    result[i * 5 + 3] = m ? parseInt(m[2]) : 128;
    result[i * 5 + 4] = m ? parseInt(m[3]) : 128;

    if ((i + 1) % BATCH === 0) {
      self.postMessage({ type: 'progress', pct: Math.round(((i + 1) / frontier.length) * 100) });
    }
  }

  self.postMessage({ type: 'done', data: result }, [result.buffer]);
};
