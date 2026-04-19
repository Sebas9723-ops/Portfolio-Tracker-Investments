"use client";
import { useRef, useEffect } from "react";
import { createChart, AreaSeries, ColorType } from "lightweight-charts";

interface Props {
  data: { date: string; value: number }[];
}

export function PortfolioLWChart({ data }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);

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
      height: 200,
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: "#f3a712",
      topColor: "rgba(243,167,18,0.2)",
      bottomColor: "rgba(243,167,18,0)",
      lineWidth: 2,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: "#f3a712",
    });

    chartRef.current = chart;
    seriesRef.current = series;

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
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !data.length) return;
    // Sort and deduplicate by date before feeding to lightweight-charts.
    // The library requires strictly ascending timestamps; duplicate or
    // out-of-order entries throw an assertion error and crash the chart.
    const seen = new Set<string>();
    const clean = data
      .slice()
      .sort((a, b) => a.date.localeCompare(b.date))
      .filter((d) => {
        if (seen.has(d.date)) return false;
        seen.add(d.date);
        return true;
      });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    seriesRef.current.setData(clean.map((d) => ({ time: d.date as any, value: d.value })));
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  return <div ref={containerRef} style={{ height: 200 }} />;
}
