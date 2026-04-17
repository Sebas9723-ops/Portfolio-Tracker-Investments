// Horizon Monte Carlo Web Worker
// Runs 1000 paths off main thread to avoid UI freeze.

self.onmessage = function (e) {
  const { initial, monthly, years, ret, vol, nPaths = 1000 } = e.data;
  const months = years * 12;
  const mu = ret / 12;
  const sigma = vol / Math.sqrt(12);

  const paths = [];
  for (let i = 0; i < nPaths; i++) {
    const path = [initial];
    for (let m = 0; m < months; m++) {
      const r = mu + sigma * (Math.random() + Math.random() + Math.random() - 1.5) * Math.sqrt(2 / 3);
      path.push(path[path.length - 1] * (1 + r) + monthly);
    }
    paths.push(path);
  }

  const data = [];
  for (let y = 0; y <= years; y++) {
    const idx = y * 12;
    const vals = paths.map((p) => p[idx]).sort((a, b) => a - b);
    data.push({
      year: y,
      p10: vals[Math.floor(0.10 * nPaths)],
      p50: vals[Math.floor(0.50 * nPaths)],
      p90: vals[Math.floor(0.90 * nPaths)],
    });
  }

  self.postMessage({ type: 'result', data });
};
