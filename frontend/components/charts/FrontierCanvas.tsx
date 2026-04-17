"use client";
import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { scaleLinear } from "@visx/scale";
import { AxisBottom, AxisLeft } from "@visx/axis";
import type { FrontierPoint } from "@/lib/types";

interface CurrentMetrics {
  volatility: number | null;
  return: number;
  sharpe: number | null;
}

interface ProfileMetrics {
  ann_vol: number;
  ann_return: number;
  sharpe?: number;
}

interface RefDot {
  vol: number;
  ret: number;
  label: string;
  color: string;
}

interface Props {
  frontier: FrontierPoint[];
  maxSharpe: FrontierPoint;
  minVol: FrontierPoint;
  maxReturn: FrontierPoint;
  currentMetrics: CurrentMetrics;
  profileMetrics?: ProfileMetrics;
  profileColor?: string;
  sharpeToColor: (s: number, min: number, max: number) => string;
  colors: Record<string, string>;
}

const MARGIN = { top: 15, right: 24, bottom: 46, left: 56 };
const HEIGHT = 300;

export function FrontierCanvas({
  frontier, maxSharpe, minVol, maxReturn, currentMetrics,
  profileMetrics, profileColor, sharpeToColor, colors,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(800);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; point: FrontierPoint } | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      setWidth(entries[0].contentRect.width || 800);
    });
    ro.observe(containerRef.current);
    if (containerRef.current.clientWidth) setWidth(containerRef.current.clientWidth);
    return () => ro.disconnect();
  }, []);

  const innerW = width - MARGIN.left - MARGIN.right;
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;

  const { xMin, xMax, yMin, yMax, minSharpe, maxSharpeVal } = useMemo(() => {
    if (!frontier.length) return { xMin: 0, xMax: 1, yMin: 0, yMax: 1, minSharpe: 0, maxSharpeVal: 1 };
    const vols = frontier.map((p) => p.vol);
    const rets = frontier.map((p) => p.ret);
    const sharpes = frontier.map((p) => p.sharpe);
    const pad = (min: number, max: number) => { const r = max - min; return [min - r * 0.02, max + r * 0.02]; };
    const [xMin, xMax] = pad(Math.min(...vols), Math.max(...vols));
    const [yMin, yMax] = pad(Math.min(...rets), Math.max(...rets));
    return { xMin, xMax, yMin, yMax, minSharpe: Math.min(...sharpes), maxSharpeVal: Math.max(...sharpes) };
  }, [frontier]);

  const xScale = useMemo(() => scaleLinear({ domain: [xMin, xMax], range: [0, innerW] }), [xMin, xMax, innerW]);
  const yScale = useMemo(() => scaleLinear({ domain: [yMin, yMax], range: [innerH, 0] }), [yMin, yMax, innerH]);

  // Draw dots to canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !frontier.length || innerW <= 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = HEIGHT * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${HEIGHT}px`;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, HEIGHT);

    ctx.globalAlpha = 0.75;
    for (const p of frontier) {
      const cx = MARGIN.left + (xScale(p.vol) ?? 0);
      const cy = MARGIN.top + (yScale(p.ret) ?? 0);
      ctx.beginPath();
      ctx.arc(cx, cy, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = sharpeToColor(p.sharpe, minSharpe, maxSharpeVal);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }, [frontier, width, innerW, xScale, yScale, minSharpe, maxSharpeVal, sharpeToColor]);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (!containerRef.current || !frontier.length) return;
      const rect = containerRef.current.getBoundingClientRect();
      const mx = e.clientX - rect.left - MARGIN.left;
      const my = e.clientY - rect.top - MARGIN.top;
      let best: FrontierPoint | null = null;
      let bestDist = Infinity;
      for (const p of frontier) {
        const px = xScale(p.vol) ?? 0;
        const py = yScale(p.ret) ?? 0;
        const d = (px - mx) ** 2 + (py - my) ** 2;
        if (d < bestDist) { bestDist = d; best = p; }
      }
      if (best && bestDist < 400) {
        setTooltip({
          x: (xScale(best.vol) ?? 0) + MARGIN.left,
          y: (yScale(best.ret) ?? 0) + MARGIN.top,
          point: best,
        });
      } else {
        setTooltip(null);
      }
    },
    [frontier, xScale, yScale],
  );

  const refDots: RefDot[] = [
    { vol: maxSharpe.vol, ret: maxSharpe.ret, label: "★ Max Sharpe", color: colors.maxSharpe },
    { vol: minVol.vol,    ret: minVol.ret,    label: "★ Min Vol",    color: colors.minVol },
    { vol: maxReturn.vol, ret: maxReturn.ret, label: "★ Max Return", color: colors.maxReturn },
    ...(currentMetrics.volatility != null
      ? [{ vol: currentMetrics.volatility, ret: currentMetrics.return, label: "● Current", color: colors.current }]
      : []),
  ];

  // Tooltip overflow: flip if too close to right edge
  const tooltipLeft = tooltip && tooltip.x + 190 > width ? tooltip.x - 195 : (tooltip?.x ?? 0) + 12;

  return (
    <div ref={containerRef} className="relative w-full" style={{ height: HEIGHT }}>
      <canvas ref={canvasRef} className="absolute top-0 left-0 pointer-events-none" />

      <svg
        width={width}
        height={HEIGHT}
        className="absolute top-0 left-0"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* X Axis */}
        <g transform={`translate(${MARGIN.left},${MARGIN.top + innerH})`}>
          <AxisBottom
            scale={xScale}
            tickFormat={(v) => `${Number(v).toFixed(1)}%`}
            stroke="#e2e8f0"
            tickStroke="#e2e8f0"
            tickLabelProps={{ fill: "#94a3b8", fontSize: 9, fontFamily: "Inter, sans-serif" }}
            numTicks={6}
          />
        </g>
        {/* Y Axis */}
        <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
          <AxisLeft
            scale={yScale}
            tickFormat={(v) => `${Number(v).toFixed(1)}%`}
            stroke="#e2e8f0"
            tickStroke="#e2e8f0"
            tickLabelProps={{ fill: "#94a3b8", fontSize: 9, fontFamily: "Inter, sans-serif" }}
            numTicks={5}
          />
        </g>

        {/* Axis labels */}
        <text
          x={MARGIN.left + innerW / 2}
          y={HEIGHT - 4}
          textAnchor="middle"
          fontSize={10}
          fill="#64748b"
          fontFamily="Inter, sans-serif"
        >
          Volatility (%)
        </text>
        <text
          x={12}
          y={MARGIN.top + innerH / 2}
          textAnchor="middle"
          fontSize={10}
          fill="#64748b"
          fontFamily="Inter, sans-serif"
          transform={`rotate(-90,12,${MARGIN.top + innerH / 2})`}
        >
          Return (%)
        </text>

        {/* Reference dots */}
        {refDots.map(({ vol, ret, label, color }) => {
          const cx = MARGIN.left + (xScale(vol) ?? 0);
          const cy = MARGIN.top + (yScale(ret) ?? 0);
          return (
            <g key={label}>
              <circle cx={cx} cy={cy} r={7} fill={color} stroke="#fff" strokeWidth={1.5} />
              <text x={cx} y={cy - 11} textAnchor="middle" fontSize={9} fill={color} fontFamily="Inter, sans-serif">
                {label}
              </text>
            </g>
          );
        })}

        {/* Profile dot — no label, shown in summary row */}
        {profileMetrics && (
          <circle
            cx={MARGIN.left + (xScale(profileMetrics.ann_vol) ?? 0)}
            cy={MARGIN.top + (yScale(profileMetrics.ann_return) ?? 0)}
            r={8}
            fill={profileColor}
            stroke="#fff"
            strokeWidth={2}
          />
        )}

        {/* Crosshair ring on hovered point */}
        {tooltip && (
          <circle
            cx={tooltip.x}
            cy={tooltip.y}
            r={5}
            fill="none"
            stroke="#0f172a"
            strokeWidth={1.5}
          />
        )}
      </svg>

      {/* Tooltip div (outside SVG for clean styling) */}
      {tooltip && (
        <div
          className="absolute pointer-events-none z-10 bg-white border border-slate-200 rounded-lg shadow-md px-2 py-1.5 text-[10px] text-slate-700"
          style={{ left: tooltipLeft, top: Math.max(8, tooltip.y - 56) }}
        >
          <div className="font-semibold">
            Ret {tooltip.point.ret.toFixed(2)}% · Vol {tooltip.point.vol.toFixed(2)}%
          </div>
          <div className="text-slate-500">Sharpe {tooltip.point.sharpe.toFixed(3)}</div>
          {Object.entries(tooltip.point.weights)
            .sort(([, a], [, b]) => (b as number) - (a as number))
            .slice(0, 3)
            .map(([t, w]) => (
              <div key={t} className="text-slate-500">
                {t}: {((w as number) * 100).toFixed(1)}%
              </div>
            ))}
        </div>
      )}

      {/* Sharpe gradient legend */}
      <div className="absolute bottom-1 right-6 flex items-center gap-1.5 text-[9px] text-slate-400 pointer-events-none">
        <span>Low Sharpe</span>
        <div
          className="w-20 h-1.5 rounded"
          style={{ background: "linear-gradient(to right, rgb(220,38,38), rgb(22,163,74))" }}
        />
        <span>High Sharpe</span>
      </div>
    </div>
  );
}
