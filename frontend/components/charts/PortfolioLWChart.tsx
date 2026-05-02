"use client";
import { useRef, useEffect } from "react";
import { createChart, AreaSeries, LineSeries, ColorType } from "lightweight-charts";
import { useThemeStore } from "@/lib/store/themeStore";

interface Props {
  data: { date: string; value: number }[];
  benchmark?: { date: string; value: number }[];
  benchmarkLabel?: string;
}

export function PortfolioLWChart({ data, benchmark, benchmarkLabel = "Benchmark" }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const chartRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const bmSeriesRef = useRef<any>(null);
  const dark = useThemeStore((s) => s.dark);

  useEffect(() => {
    if (!containerRef.current) return;

    const bg    = dark ? "#0f141e" : "#ffffff";
    const grid  = dark ? "#1e2a3c" : "#e2e8f0";
    const text  = dark ? "#64748b" : "#64748b";

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: bg },
        textColor: text,
        fontSize: 10,
        fontFamily: "Inter, sans-serif",
      },
      grid: {
        vertLines: { color: grid },
        horzLines: { color: grid },
      },
      crosshair: { mode: 1 },
      localization: { locale: "en-US" },
      rightPriceScale: { borderColor: grid },
      timeScale: { borderColor: grid, timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
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

    if (benchmark) {
      const bmSeries = chart.addSeries(LineSeries, {
        color: dark ? "#6b7a99" : "#94a3b8",
        lineWidth: 1,
        lineStyle: 2, // dashed
        title: benchmarkLabel,
      });
      bmSeriesRef.current = bmSeries;
    }

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      bmSeriesRef.current = null;
    };
  // Re-create chart when theme or benchmark presence changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, !!benchmark]);

  useEffect(() => {
    if (!seriesRef.current || !data.length) return;
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

  useEffect(() => {
    if (!bmSeriesRef.current || !benchmark?.length) return;
    const seen = new Set<string>();
    const clean = benchmark
      .slice()
      .sort((a, b) => a.date.localeCompare(b.date))
      .filter((d) => {
        if (seen.has(d.date)) return false;
        seen.add(d.date);
        return true;
      });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    bmSeriesRef.current.setData(clean.map((d) => ({ time: d.date as any, value: d.value })));
  }, [benchmark]);

  return <div ref={containerRef} style={{ height: 200 }} />;
}
