/**
 * dashboard.js – lightweight canvas bar chart (no external dependencies).
 */
function initUsageChart(labels, data) {
  const canvas = document.getElementById("usageChart");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth  || 800;
  const H = canvas.offsetHeight || 260;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  ctx.scale(dpr, dpr);

  const PAD   = { top: 20, right: 20, bottom: 50, left: 55 };
  const cW    = W - PAD.left - PAD.right;
  const cH    = H - PAD.top  - PAD.bottom;

  const maxVal = Math.max(...data, 1);
  const n      = labels.length;
  const barW   = cW / n * 0.65;
  const gap    = cW / n;

  // Background
  ctx.fillStyle = "#1a1d27";
  ctx.fillRect(0, 0, W, H);

  // Grid lines + Y labels
  const steps = 5;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  ctx.font = "11px Inter,system-ui,sans-serif";
  ctx.fillStyle = "#8892aa";
  ctx.strokeStyle = "#2e3245";
  ctx.lineWidth = 1;
  for (let i = 0; i <= steps; i++) {
    const y = PAD.top + cH - (i / steps) * cH;
    const v = Math.round((i / steps) * maxVal);
    ctx.fillText(v >= 1000 ? (v / 1000).toFixed(0) + "k" : v, PAD.left - 8, y);
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(PAD.left + cW, y);
    ctx.stroke();
  }

  // Bars
  data.forEach((val, i) => {
    const x = PAD.left + i * gap + (gap - barW) / 2;
    const h = (val / maxVal) * cH;
    const y = PAD.top + cH - h;

    const grad = ctx.createLinearGradient(0, y, 0, y + h);
    grad.addColorStop(0,   "rgba(108,99,255,0.9)");
    grad.addColorStop(1,   "rgba(108,99,255,0.4)");
    ctx.fillStyle = grad;
    const r = Math.min(4, barW / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + barW - r, y);
    ctx.arcTo(x + barW, y, x + barW, y + r, r);
    ctx.lineTo(x + barW, y + h);
    ctx.lineTo(x, y + h);
    ctx.arcTo(x, y, x + r, y, r);
    ctx.closePath();
    ctx.fill();
  });

  // X labels (show every ~5th to avoid crowding)
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillStyle = "#8892aa";
  ctx.font = "10px Inter,system-ui,sans-serif";
  const step = Math.max(1, Math.ceil(n / 10));
  labels.forEach((label, i) => {
    if (i % step !== 0) return;
    const x = PAD.left + i * gap + gap / 2;
    ctx.fillText(label, x, PAD.top + cH + 8);
  });

  // Axis lines
  ctx.strokeStyle = "#2e3245";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD.left, PAD.top);
  ctx.lineTo(PAD.left, PAD.top + cH);
  ctx.lineTo(PAD.left + cW, PAD.top + cH);
  ctx.stroke();
}
