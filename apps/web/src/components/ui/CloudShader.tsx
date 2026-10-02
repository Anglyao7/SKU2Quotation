// Adapted from https://ui.aceternity.com/components/cloud-shader (official registry).

import React, { useEffect, useRef, useState } from "react";
import styles from "./CloudShader.module.css";

export type CloudShaderProps = {
  className?: string;
  children?: React.ReactNode;
  /** Animation speed multiplier. 1 = default drift. */
  speed?: number;
  /** Pause drift without hiding the cloud field. */
  paused?: boolean;
  /** Number of clouds (1-6). */
  count?: number;
  /** Cloud tint color (hex or rgb string). */
  cloudColor?: string;
  /** Sky color at the top (hex or rgb string). */
  skyTopColor?: string;
  /** Sky color at the bottom (hex or rgb string). */
  skyBottomColor?: string;
};

const VERT = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}
`;

// Original cloud shader for Aceternity UI.
// Each cloud is an asymmetric envelope (dome top, flat base) filled with
// domain-warped billow noise. A second density sample above the pixel
// approximates self-shadowing. Clouds drift horizontally and wrap around.
const FRAG = `
precision highp float;

varying vec2 v_uv;

uniform vec2 u_res;
uniform float u_time;
uniform float u_count;
uniform vec3 u_cloud;
uniform vec3 u_skyTop;
uniform vec3 u_skyBottom;

const mat2 R = mat2(0.80, 0.60, -0.60, 0.80);

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(41.31, 289.17))) * 26737.367);
}

float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 4; i++) {
    sum += amp * vnoise(p);
    p = R * p * 2.03 + 19.19;
    amp *= 0.5;
  }
  return sum;
}

// billow noise: sharp puffy ridges, like cauliflower cloud tops
float billow(vec2 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 5; i++) {
    sum += amp * (1.0 - abs(2.0 * vnoise(p) - 1.0));
    p = R * p * 2.11 + 13.37;
    amp *= 0.5;
  }
  return sum;
}

// raw density for one cloud at point p
float cloudDensity(vec2 p, vec2 c, vec2 r, float seed, float t) {
  vec2 q = p - c;

  // envelope: dome above the center, flat base below
  float ry = q.y > 0.0 ? r.y : r.y * 0.42;
  float env = 1.0 - length(vec2(q.x / r.x, q.y / ry));
  if (env < -0.35) return 0.0;

  // domain-warped billow detail, moves with the cloud, evolves slowly
  vec2 dp = q * (2.4 / r.x) + seed;
  dp += 0.6 * vec2(
    fbm(dp * 1.4 + t * 0.04),
    fbm(dp * 1.4 + 7.7 - t * 0.03)
  );
  float detail = billow(dp * 1.6);

  return env + (detail - 0.62) * 0.62;
}

// shades one cloud and blends it over the current color
vec3 shadeCloud(vec3 color, vec3 sky, vec2 p, vec2 c, vec2 r, float seed, float t, float dist) {
  float d = cloudDensity(p, c, r, seed, t);
  if (d < 0.02) return color;

  // sample density toward the sun (straight up) for self-shadowing
  float dUp = cloudDensity(p + vec2(0.0, r.y * 0.55), c, r, seed, t);
  float occl = clamp((dUp - d) * 1.1 + d * 0.55, 0.0, 1.0);

  vec3 lit = u_cloud * 1.04;
  vec3 shadow = mix(u_cloud * 0.60, sky, 0.38);
  vec3 cloudCol = mix(lit, shadow, occl * 0.85);

  float alpha = smoothstep(0.02, 0.38, d);

  // silver lining on thin edges
  float rim = smoothstep(0.02, 0.14, d) * (1.0 - smoothstep(0.14, 0.40, d));
  cloudCol += rim * 0.10;

  // atmospheric perspective: far clouds fade into the sky
  cloudCol = mix(cloudCol, sky, dist * 0.35);
  alpha *= mix(1.0, 0.8, dist);

  return mix(color, cloudCol, alpha);
}

// one drifting cloud: horizontal wrap + gentle vertical bob
vec3 cloudPass(vec3 color, vec3 sky, vec2 p, float aspect, float t,
               float spd, float phase, float y, vec2 r, float seed, float dist) {
  float cx = mix(-r.x - 0.25, aspect + r.x + 0.25, fract(t * spd + phase));
  float cy = y + sin(t * 0.05 + phase * 6.2831) * 0.012;
  return shadeCloud(color, sky, p, vec2(cx, cy), r, seed, t, dist);
}

void main() {
  float aspect = u_res.x / u_res.y;
  vec2 p = vec2(v_uv.x * aspect, v_uv.y);
  float t = u_time;

  vec3 sky = mix(u_skyBottom, u_skyTop, v_uv.y);
  vec3 color = sky;

  // faint haze band near the horizon
  color = mix(color, u_skyBottom * 1.06, smoothstep(0.35, 0.0, v_uv.y) * 0.5);

  // soft sun glow, upper area
  vec2 sunPos = vec2(aspect * 0.78, 0.92);
  float sunDist = length(p - sunPos);
  color += vec3(1.0, 0.95, 0.82) * exp(-sunDist * sunDist * 5.0) * 0.28;

  // thin cirrus streaks, stretched horizontally, high in the sky
  float cirrusBand = smoothstep(0.55, 0.8, v_uv.y) * (1.0 - smoothstep(0.9, 1.0, v_uv.y));
  if (cirrusBand > 0.01) {
    float streak = fbm(vec2(p.x * 1.6 - t * 0.006, p.y * 12.0));
    float wisp = smoothstep(0.52, 0.78, streak) * cirrusBand;
    color = mix(color, u_cloud * 0.98, wisp * 0.35);
  }

  // far layer: small, high, slow
  if (u_count > 5.5) {
    color = cloudPass(color, sky, p, aspect, t, 0.006, 0.10, 0.84, vec2(0.20, 0.10), 43.7, 1.0);
  }
  if (u_count > 4.5) {
    color = cloudPass(color, sky, p, aspect, t, 0.008, 0.62, 0.73, vec2(0.24, 0.12), 71.3, 0.85);
  }

  // middle layer
  if (u_count > 3.5) {
    color = cloudPass(color, sky, p, aspect, t, 0.011, 0.33, 0.60, vec2(0.34, 0.16), 17.3, 0.55);
  }
  if (u_count > 2.5) {
    color = cloudPass(color, sky, p, aspect, t, 0.013, 0.80, 0.47, vec2(0.30, 0.15), 29.9, 0.45);
  }

  // near layer: big, low, fast
  if (u_count > 1.5) {
    color = cloudPass(color, sky, p, aspect, t, 0.016, 0.05, 0.35, vec2(0.46, 0.20), 91.1, 0.15);
  }
  color = cloudPass(color, sky, p, aspect, t, 0.020, 0.48, 0.20, vec2(0.56, 0.24), 57.2, 0.0);

  gl_FragColor = vec4(color, 1.0);
}
`;

function parseHex(color: string): [number, number, number] {
  const value = color.trim();
  if (value.startsWith("#")) {
    const hex = value.slice(1);
    if (hex.length === 3) {
      return [
        parseInt(hex[0] + hex[0], 16) / 255,
        parseInt(hex[1] + hex[1], 16) / 255,
        parseInt(hex[2] + hex[2], 16) / 255,
      ];
    }
    return [
      parseInt(hex.slice(0, 2), 16) / 255,
      parseInt(hex.slice(2, 4), 16) / 255,
      parseInt(hex.slice(4, 6), 16) / 255,
    ];
  }
  const rgb = value.match(/[\d.]+/g);
  if (rgb && rgb.length >= 3) {
    return [Number(rgb[0]) / 255, Number(rgb[1]) / 255, Number(rgb[2]) / 255];
  }
  return [0.95, 0.95, 0.95];
}

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export function CloudShader({
  className,
  children,
  speed = 1,
  paused = false,
  count = 6,
  cloudColor = "#fbf8f2",
  skyTopColor = "#3876ba",
  skyBottomColor = "#8cbfe8",
}: CloudShaderProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef<(() => void) | null>(null);
  const paramsRef = useRef({
    speed,
    paused,
    count,
    cloudColor,
    skyTopColor,
    skyBottomColor,
  });
  const [contextVersion, setContextVersion] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.dataset.status = "fallback";
    const restore = () => setContextVersion((value) => value + 1);
    canvas.addEventListener("webglcontextrestored", restore);
    let gl: WebGLRenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl", {
        alpha: false,
        antialias: false,
        premultipliedAlpha: false,
      });
    } catch {
      // The underlying CSS background keeps the page usable without WebGL.
    }
    if (!gl)
      return () => canvas.removeEventListener("webglcontextrestored", restore);
    const context = gl;
    const vert = compile(context, context.VERTEX_SHADER, VERT);
    const frag = compile(context, context.FRAGMENT_SHADER, FRAG);
    const program = context.createProgram();
    const buffer = context.createBuffer();
    const release = () => {
      context.deleteBuffer(buffer);
      context.deleteProgram(program);
      context.deleteShader(vert);
      context.deleteShader(frag);
      canvas.removeEventListener("webglcontextrestored", restore);
    };
    if (!vert || !frag || !program || !buffer) {
      release();
      return;
    }
    context.attachShader(program, vert);
    context.attachShader(program, frag);
    context.bindAttribLocation(program, 0, "a_pos");
    context.linkProgram(program);
    if (!context.getProgramParameter(program, context.LINK_STATUS)) {
      release();
      return;
    }
    context.useProgram(program);
    context.bindBuffer(context.ARRAY_BUFFER, buffer);
    context.bufferData(
      context.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      context.STATIC_DRAW,
    );
    context.enableVertexAttribArray(0);
    context.vertexAttribPointer(0, 2, context.FLOAT, false, 0, 0);
    const loc = {
      res: context.getUniformLocation(program, "u_res"),
      time: context.getUniformLocation(program, "u_time"),
      count: context.getUniformLocation(program, "u_count"),
      cloud: context.getUniformLocation(program, "u_cloud"),
      skyTop: context.getUniformLocation(program, "u_skyTop"),
      skyBottom: context.getUniformLocation(program, "u_skyBottom"),
    };
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let disposed = false;
    let lost = false;
    let inView = true;
    let elapsed = 0;
    let previous = 0;
    let lastPaint = 0;

    const animated = () =>
      !paramsRef.current.paused &&
      !motion.matches &&
      paramsRef.current.speed > 0;
    const active = () => !disposed && !lost && inView && !document.hidden;
    const paint = () => {
      const p = paramsRef.current;
      context.uniform1f(loc.time, elapsed);
      context.uniform1f(loc.count, Math.min(6, Math.max(1, p.count)));
      context.uniform3fv(loc.cloud, parseHex(p.cloudColor));
      context.uniform3fv(loc.skyTop, parseHex(p.skyTopColor));
      context.uniform3fv(loc.skyBottom, parseHex(p.skyBottomColor));
      context.drawArrays(context.TRIANGLES, 0, 3);
      canvas.dataset.status = "ready";
    };
    const tick = (now: number) => {
      frame = 0;
      if (!active()) return;
      canvas.dataset.motion = animated() ? "running" : "static";
      if (animated()) {
        if (previous)
          elapsed +=
            (Math.min(now - previous, 100) / 1000) * paramsRef.current.speed;
        previous = now;
      } else previous = 0;
      // Cap paints at 30fps; render one frame for paused/reduced-motion mode.
      if (!animated() || now - lastPaint >= 1000 / 30) {
        paint();
        lastPaint = now;
      }
      if (animated()) frame = requestAnimationFrame(tick);
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = 0;
      previous = 0;
      lastPaint = 0;
      canvas.dataset.motion = active()
        ? animated()
          ? "running"
          : "static"
        : "suspended";
      if (active()) frame = requestAnimationFrame(tick);
    };
    drawRef.current = schedule;
    const resize = () => {
      // Limit GPU work on high-DPI and large displays to a 960px backing width.
      const width = Math.max(1, canvas.clientWidth);
      const height = Math.max(1, canvas.clientHeight);
      const scale = Math.min(window.devicePixelRatio || 1, 1, 960 / width);
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      context.viewport(0, 0, canvas.width, canvas.height);
      context.uniform2f(loc.res, canvas.width, canvas.height);
      schedule();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    const intersectionObserver = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      schedule();
    });
    intersectionObserver.observe(canvas);
    const loseContext = (event: Event) => {
      event.preventDefault();
      lost = true;
      canvas.dataset.status = "fallback";
      schedule();
    };
    canvas.addEventListener("webglcontextlost", loseContext);
    document.addEventListener("visibilitychange", schedule);
    motion.addEventListener("change", schedule);
    resize();
    return () => {
      disposed = true;
      drawRef.current = null;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener("visibilitychange", schedule);
      motion.removeEventListener("change", schedule);
      canvas.removeEventListener("webglcontextlost", loseContext);
      release();
    };
  }, [contextVersion]);

  useEffect(() => {
    paramsRef.current = {
      speed,
      paused,
      count,
      cloudColor,
      skyTopColor,
      skyBottomColor,
    };
    drawRef.current?.();
  }, [speed, paused, count, cloudColor, skyTopColor, skyBottomColor]);

  return (
    <div className={[styles.clouds, className].filter(Boolean).join(" ")}>
      <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      {children ? <div className={styles.content}>{children}</div> : null}
    </div>
  );
}
