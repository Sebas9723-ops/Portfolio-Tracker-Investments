"use client";
import { useRef, useEffect } from "react";
import { createChart, LineSeries, ColorType } from "lightweight-charts";

interface DataPoint {
  year: number;
  p10: number;
  p50: number;
  p90: number;
}

interface Props {
  data: DataPoint[];
  ccy: string;
  baseYear?: number;
}

export function HorizonLWChart({ data, ccy, baseYear }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p10Ref = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p50Ref = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p90Ref = useRef<any>(null);

  const base = baseYear ?? new Date().getFullYear();

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#64748b",
        fontSize: 10,
        fontFamily: "Inter, sans-serif",
      },
      grid: {
        vertLines: { color: "#e2e8f0" },
        horzLines: { color: "#e2e8f0" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#e2e8f0" },
      timeScale: { borderColor: "#e2e8f0", timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: true,
      handleScale: true,
      height: 260,
    });

    const p90 = chart.addSeries(LineSeries, {
      color: "#22c55e",
      lineWidth: 1,
      lineStyle: 2,
      title: "Bull (P90)",
    });
    const p50 = chart.addSeries(LineSeries, {
      color: "#f3a712",
      lineWidth: 2,
      title: "Base (P50)",
    });
    const p10 = chart.addSeries(LineSeries, {
      color: "#ef4444",
      lineWidth: 1,
      lineStyle: 2,
      title: "Bear (P10)",
    });

    chartRef.current = chart;
    p90Ref.current = p90;
    p50Ref.current = p50;
    p10Ref.current = p10;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  // ccy intentionally omitted — formatter captured once is fine
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!p10Ref.current || !data.length) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const toTime = (y: number): any => `${base + y}-01-01`;
    p90Ref.current?.setData(data.map((d) => ({ time: toTime(d.year), value: d.p90 })));
    p50Ref.current?.setData(data.map((d) => ({ time: toTime(d.year), value: d.p50 })));
    p10Ref.current?.setData(data.map((d) => ({ time: toTime(d.year), value: d.p10 })));
    chartRef.current?.timeScale().fitContent();
  }, [data, base]);

  return <div ref={containerRef} style={{ height: 260 }} />;
}
