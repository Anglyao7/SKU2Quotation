import { BarChart, HeatmapChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";

echarts.use([
  AriaComponent,
  BarChart,
  GridComponent,
  HeatmapChart,
  LineChart,
  SVGRenderer,
  TooltipComponent,
  VisualMapComponent,
]);

export interface EChartPalette {
  accent: string;
  accentSoft: string;
  ink: string;
  muted: string;
  line: string;
  surface: string;
  fontFamily: string;
}

function cssValue(styles: CSSStyleDeclaration, name: string, fallback: string) {
  return styles.getPropertyValue(name).trim() || fallback;
}

function chartPalette(): EChartPalette {
  const styles = getComputedStyle(document.documentElement);
  return {
    accent: cssValue(styles, "--accent-9", "#23866f"),
    accentSoft: cssValue(styles, "--accent-a4", "rgba(35, 134, 111, .18)"),
    ink: cssValue(styles, "--gray-12", "#202624"),
    muted: cssValue(styles, "--gray-10", "#7c8581"),
    line: cssValue(styles, "--gray-a5", "rgba(70, 82, 77, .16)"),
    surface: cssValue(styles, "--color-panel-solid", "#ffffff"),
    fontFamily: cssValue(styles, "--font-ui", "sans-serif"),
  };
}

export function EChart({
  option,
  label,
  className = "",
}: {
  option: (palette: EChartPalette) => EChartsOption;
  label: string;
  className?: string;
}) {
  const elementRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return undefined;
    const chart = echarts.init(element, undefined, { renderer: "svg" });
    const render = () => {
      const palette = chartPalette();
      chart.setOption(
        {
          animationDuration: 420,
          animationDurationUpdate: 260,
          animationEasing: "cubicOut",
          backgroundColor: "transparent",
          textStyle: {
            color: palette.ink,
            fontFamily: palette.fontFamily,
          },
          ...option(palette),
        },
        { notMerge: true },
      );
    };
    render();

    const resizeObserver = new ResizeObserver(() => chart.resize());
    resizeObserver.observe(element);
    const themeObserver = new MutationObserver(render);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "data-theme", "data-is-root-theme", "style"],
    });
    return () => {
      resizeObserver.disconnect();
      themeObserver.disconnect();
      chart.dispose();
    };
  }, [option]);

  return (
    <div
      ref={elementRef}
      className={`core-echart ${className}`.trim()}
      role="img"
      aria-label={label}
    />
  );
}
