(() => {
  const $ = (id) => document.getElementById(id);

  const ui = {
    D: $("DInput"), beta0: $("beta0Input"), beta1: $("beta1Input"), b0: $("b0Input"), d0: $("d0Input"), optimum: $("optimumInput"),
    optimumOut: $("optimumOut"), maxChainLength: $("maxChainLengthInput"), maxChainLengthOut: $("maxChainLengthOut"), duration: $("durationInput"), seed: $("seedInput"),
    defaultsBtn: $("defaultsBtn"), runBtn: $("runBtn"), newBtn: $("newBtn"), status: $("status"),
    layer: $("layerSelect"), speed: $("speedSelect"), play: $("playBtn"), timeline: $("timeline"), timelineLabel: $("timelineLabel"),
    mapCanvas: $("mapCanvas"), mapWrap: $("mapWrap"), tooltip: $("mapTooltip"), chartCanvas: $("chartCanvas"),
    legendLabel: $("legendLabel"), legendMin: $("legendMin"), legendMax: $("legendMax"),
    timeStat: $("timeStat"), seedStat: $("seedStat"), expectedStat: $("expectedStat"), activeStat: $("activeStat"), reachedStat: $("reachedStat"), clusterStat: $("clusterStat"),
    rateDiag: $("rateDiag"), superDiag: $("superDiag"), largestDiag: $("largestDiag"), warningBox: $("warningBox")
  };

  const state = {
    meta: null,
    sim: null,
    frame: 0,
    frameFloat: 0,
    playing: false,
    lastTs: null,
    layerBitmap: null,
    layerRequestId: 0,
    mapMetrics: null,
    dirty: false,
  };

  function paramsFromForm() {
    return {
      D: Number(ui.D.value),
      beta0: Number(ui.beta0.value),
      beta1: Number(ui.beta1.value),
      b0: Number(ui.b0.value),
      d0: Number(ui.d0.value),
      max_chain_length: Math.trunc(Number(ui.maxChainLength.value)),
      optimum: Number(ui.optimum.value),
      duration: Number(ui.duration.value),
      frames: 181,
      seed: Math.trunc(Number(ui.seed.value)),
    };
  }

  function setStatus(text, kind = "") {
    ui.status.textContent = text;
    ui.status.className = `status ${kind}`.trim();
  }

  function formatNumber(x, digits = 3) {
    if (!Number.isFinite(x)) return "-";
    const ax = Math.abs(x);
    if (ax === 0) return "0";
    if (ax >= 1e5 || ax < 1e-3) return x.toExponential(2).replace("e+", "e");
    if (ax >= 1000) return Math.round(x).toLocaleString("en-US");
    if (ax >= 10) return x.toFixed(1);
    return x.toPrecision(digits);
  }

  function apiErrorMessage(payload, fallback) {
    if (!payload || payload.detail == null) return fallback;
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => {
        if (typeof item === "string") return item;
        if (!item || typeof item !== "object") return String(item);
        const loc = Array.isArray(item.loc) ? item.loc.filter((part) => !["body", "query", "path"].includes(String(part))) : [];
        const field = loc.length ? String(loc[loc.length - 1]) : "parameter";
        return `${field}: ${item.msg || "invalid value"}`;
      });
      return messages.filter(Boolean).join("; ") || fallback;
    }
    if (typeof detail === "object") return detail.msg || JSON.stringify(detail);
    return String(detail);
  }

  function applyDefaults() {
    if (!state.meta) return;
    const d = state.meta.defaults;
    ui.D.value = d.D;
    ui.beta0.value = d.beta0;
    ui.beta1.value = d.beta1;
    ui.b0.value = d.b0;
    ui.d0.value = d.d0;
    ui.maxChainLength.value = d.max_chain_length;
    ui.maxChainLengthOut.value = String(d.max_chain_length);
    ui.optimum.value = d.optimum;
    ui.optimumOut.value = Number(d.optimum).toFixed(2);
    ui.duration.value = d.duration;
    ui.seed.value = d.seed;
    markDirty();
  }

  function markDirty() {
    state.dirty = true;
    ui.optimumOut.value = Number(ui.optimum.value).toFixed(2);
    ui.maxChainLengthOut.value = String(Math.trunc(Number(ui.maxChainLength.value)));
    if (state.sim) setStatus("Parameters changed - run the simulation to apply them.");
    debounceLayerReload();
  }

  let layerTimer = null;
  function debounceLayerReload() {
    clearTimeout(layerTimer);
    layerTimer = setTimeout(() => loadLayer(), 180);
  }

  function layerUrl() {
    const p = paramsFromForm();
    const q = new URLSearchParams({ D: String(p.D), beta0: String(p.beta0), beta1: String(p.beta1) });
    return `/api/layer/${encodeURIComponent(ui.layer.value)}.png?${q}`;
  }

  async function loadLayer() {
    const requestId = ++state.layerRequestId;
    try {
      const response = await fetch(layerUrl(), { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load map layer.");
      const min = Number(response.headers.get("X-Scale-Min"));
      const max = Number(response.headers.get("X-Scale-Max"));
      const mode = response.headers.get("X-Scale-Mode") || "linear";
      const label = response.headers.get("X-Layer-Label") || ui.layer.options[ui.layer.selectedIndex].text;
      const blob = await response.blob();
      let bitmap;
      if ("createImageBitmap" in window) {
        bitmap = await createImageBitmap(blob);
      } else {
        bitmap = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = URL.createObjectURL(blob);
        });
      }
      if (requestId !== state.layerRequestId) return;
      if (state.layerBitmap && state.layerBitmap.close) state.layerBitmap.close();
      state.layerBitmap = bitmap;
      ui.legendLabel.textContent = label;
      ui.legendMin.textContent = formatNumber(min);
      ui.legendMax.textContent = formatNumber(max);
      ui.legendLabel.title = mode === "log" ? "Logarithmic color mapping" : "Linear color mapping";
      drawMap();
    } catch (err) {
      console.error(err);
      ui.legendLabel.textContent = "Layer unavailable";
    }
  }

  async function runSimulation() {
    const p = paramsFromForm();
    ui.runBtn.disabled = true;
    ui.newBtn.disabled = true;
    setStatus("Simulating spillover infections and birth-death transmission chains...", "busy");
    try {
      const response = await fetch("/api/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(p),
      });
      if (!response.ok) {
        const fallback = `Simulation failed (${response.status}).`;
        let message = fallback;
        try { message = apiErrorMessage(await response.json(), fallback); } catch (_) {}
        throw new Error(message);
      }
      state.sim = await response.json();
      state.frame = 0;
      state.frameFloat = 0;
      state.playing = true;
      state.lastTs = null;
      state.dirty = false;
      ui.timeline.max = String(state.sim.frame_times.length - 1);
      ui.timeline.value = "0";
      ui.play.textContent = "Pause";
      setStatus(`Simulation ready: ${state.sim.poisson.realized_spillovers} spillover seed${state.sim.poisson.realized_spillovers === 1 ? "" : "s"}.`);
      updateDiagnostics();
      updateFrameUI();
      drawChart();
      await loadLayer();
    } catch (err) {
      state.playing = false;
      setStatus(err.message || String(err), "error");
    } finally {
      ui.runBtn.disabled = false;
      ui.newBtn.disabled = false;
    }
  }

  function updateDiagnostics() {
    const sim = state.sim;
    if (!sim) return;
    ui.rateDiag.textContent = formatNumber(sim.poisson.total_rate);
    const superCount = sim.clusters.filter(c => c.supercritical).length;
    ui.superDiag.textContent = `${superCount} / ${sim.clusters.length}`;
    let largest = 0;
    for (const c of sim.clusters) largest = Math.max(largest, c.reached[c.reached.length - 1] || 0);
    ui.largestDiag.textContent = largest.toLocaleString("en-US");
    if (sim.warnings && sim.warnings.length) {
      ui.warningBox.hidden = false;
      ui.warningBox.textContent = sim.warnings.join(" ");
    } else {
      ui.warningBox.hidden = true;
      ui.warningBox.textContent = "";
    }
  }

  function updateFrameUI() {
    const sim = state.sim;
    if (!sim) {
      drawMap();
      drawChart();
      return;
    }
    const i = Math.max(0, Math.min(state.frame, sim.frame_times.length - 1));
    const t = sim.frame_times[i];
    const arrived = sim.clusters.reduce((n, c) => n + (c.arrival <= t ? 1 : 0), 0);
    ui.timeStat.textContent = t.toFixed(1);
    ui.seedStat.textContent = `${arrived} / ${sim.clusters.length}`;
    ui.expectedStat.textContent = `E = ${sim.poisson.expected_spillovers.toFixed(1)} total`;
    ui.activeStat.textContent = sim.totals.active[i].toLocaleString("en-US");
    ui.reachedStat.textContent = sim.totals.reached[i].toLocaleString("en-US");
    ui.clusterStat.textContent = sim.totals.active_clusters[i].toLocaleString("en-US");
    ui.timeline.value = String(i);
    ui.timelineLabel.textContent = `t = ${t.toFixed(1)}`;
    drawMap();
    drawChart();
  }

  function sizeCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width: rect.width, height: rect.height, dpr };
  }

  function mapGeometry(width, height) {
    const left = width < 540 ? 44 : 54;
    const right = 18;
    const top = 20;
    const bottom = 42;
    return { left, right, top, bottom, w: width - left - right, h: height - top - bottom };
  }

  function project(lon, lat, geom) {
    const m = state.meta.map;
    return {
      x: geom.left + (lon - m.lon_min) / (m.lon_max - m.lon_min) * geom.w,
      y: geom.top + (m.lat_max - lat) / (m.lat_max - m.lat_min) * geom.h,
    };
  }

  function drawMap() {
    if (!state.meta) return;
    const { ctx, width, height } = sizeCanvas(ui.mapCanvas);
    const g = mapGeometry(width, height);
    state.mapMetrics = g;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(0, 0, width, height);

    const xTicks = [86, 88, 90, 92, 94, 96];
    const yTicks = [20, 22, 24, 26, 28];
    ctx.save();
    ctx.strokeStyle = "#e5eaf0";
    ctx.lineWidth = 1;
    for (const lon of xTicks) {
      const p = project(lon, state.meta.map.lat_min, g);
      ctx.beginPath(); ctx.moveTo(p.x, g.top); ctx.lineTo(p.x, g.top + g.h); ctx.stroke();
    }
    for (const lat of yTicks) {
      const p = project(state.meta.map.lon_min, lat, g);
      ctx.beginPath(); ctx.moveTo(g.left, p.y); ctx.lineTo(g.left + g.w, p.y); ctx.stroke();
    }
    ctx.restore();

    ctx.save();
    ctx.beginPath();
    ctx.rect(g.left, g.top, g.w, g.h);
    ctx.clip();
    if (state.layerBitmap) {
      ctx.globalAlpha = 0.97;
      ctx.drawImage(state.layerBitmap, g.left, g.top, g.w, g.h);
      ctx.globalAlpha = 1;
    }

    if (state.sim) {
      const i = state.frame;
      const t = state.sim.frame_times[i];
      for (const c of state.sim.clusters) {
        const reached = c.reached[i];
        if (!reached) continue;
        const active = c.active[i];
        const p = project(c.lon, c.lat, g);
        const r = Math.min(42, 2.5 + 1.9 * Math.sqrt(reached));
        const warm = c.supercritical;
        const rgb = warm ? [231, 104, 69] : [44, 121, 199];
        const fillAlpha = active > 0 ? 0.10 : 0.035;
        const strokeAlpha = active > 0 ? 0.72 : 0.30;
        ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${fillAlpha})`;
        ctx.strokeStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${strokeAlpha})`;
        ctx.lineWidth = active > 0 ? 1.6 : 1.0;
        ctx.setLineDash(active > 0 ? [] : [3, 3]);
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = active > 0 ? `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` : "#667085";
        ctx.beginPath(); ctx.arc(p.x, p.y, 2.6, 0, Math.PI * 2); ctx.fill();

        const age = t - c.arrival;
        if (age >= 0 && age <= 0.75) {
          const pulseR = 5 + age * 18;
          ctx.strokeStyle = `rgba(255,255,255,${0.9 * (1 - age / 0.75)})`;
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(p.x, p.y, pulseR, 0, Math.PI * 2); ctx.stroke();
        }
      }
    }
    ctx.restore();

    ctx.strokeStyle = "#344054";
    ctx.lineWidth = 1.1;
    ctx.strokeRect(g.left, g.top, g.w, g.h);

    ctx.fillStyle = "#475467";
    ctx.font = "11px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const lon of xTicks) {
      const p = project(lon, state.meta.map.lat_min, g);
      ctx.fillText(String(lon), p.x, g.top + g.h + 8);
    }
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const lat of yTicks) {
      const p = project(state.meta.map.lon_min, lat, g);
      ctx.fillText(String(lat), g.left - 8, p.y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("longitude", g.left + g.w / 2, height - 4);
    ctx.save();
    ctx.translate(13, g.top + g.h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("latitude", 0, 0);
    ctx.restore();
  }

  function drawChart() {
    const { ctx, width, height } = sizeCanvas(ui.chartCanvas);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    if (!state.sim) return;

    const sim = state.sim;
    const left = 45, right = 14, top = 12, bottom = 30;
    const pw = width - left - right, ph = height - top - bottom;
    const maxY = Math.max(1, ...sim.totals.reached);
    const n = sim.frame_times.length;
    const xp = (i) => left + i / (n - 1) * pw;
    const yp = (v) => top + ph - v / maxY * ph;

    ctx.strokeStyle = "#e4e9ef";
    ctx.fillStyle = "#667085";
    ctx.font = "10px Inter, system-ui, sans-serif";
    ctx.lineWidth = 1;
    for (let k = 0; k <= 4; k++) {
      const v = maxY * k / 4;
      const y = yp(v);
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + pw, y); ctx.stroke();
      ctx.textAlign = "right"; ctx.textBaseline = "middle";
      ctx.fillText(formatNumber(v), left - 6, y);
    }

    function line(values, color, widthPx) {
      ctx.strokeStyle = color;
      ctx.lineWidth = widthPx;
      ctx.beginPath();
      values.forEach((v, i) => {
        const x = xp(i), y = yp(v);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    }
    line(sim.totals.reached, "#e76845", 2.1);
    line(sim.totals.active, "#2c79c7", 2.0);

    const xcur = xp(state.frame);
    ctx.strokeStyle = "#101828";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(xcur, top); ctx.lineTo(xcur, top + ph); ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = "#98a2b3";
    ctx.beginPath(); ctx.moveTo(left, top + ph); ctx.lineTo(left + pw, top + ph); ctx.stroke();
    ctx.fillStyle = "#667085";
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText("0", left, top + ph + 7);
    ctx.textAlign = "right";
    ctx.fillText(formatNumber(sim.frame_times[n - 1]), left + pw, top + ph + 7);
    ctx.textAlign = "center";
    ctx.fillText("model time", left + pw / 2, top + ph + 7);
  }

  function animate(ts) {
    if (state.sim && state.playing) {
      if (state.lastTs == null) state.lastTs = ts;
      const dt = Math.min(0.1, (ts - state.lastTs) / 1000);
      state.lastTs = ts;
      const speed = Number(ui.speed.value) || 1;
      const n = state.sim.frame_times.length;
      const completionSeconds = 12 / speed;
      state.frameFloat += dt * (n - 1) / completionSeconds;
      if (state.frameFloat >= n - 1) {
        state.frameFloat = n - 1;
        state.playing = false;
        ui.play.textContent = "Replay";
      }
      const newFrame = Math.floor(state.frameFloat);
      if (newFrame !== state.frame) {
        state.frame = newFrame;
        updateFrameUI();
      }
    } else {
      state.lastTs = null;
    }
    requestAnimationFrame(animate);
  }

  function togglePlay() {
    if (!state.sim) return;
    const n = state.sim.frame_times.length;
    if (!state.playing && state.frame >= n - 1) {
      state.frame = 0;
      state.frameFloat = 0;
    }
    state.playing = !state.playing;
    state.lastTs = null;
    ui.play.textContent = state.playing ? "Pause" : (state.frame >= n - 1 ? "Replay" : "Play");
    updateFrameUI();
  }

  function handleTimeline() {
    if (!state.sim) return;
    state.frame = Number(ui.timeline.value);
    state.frameFloat = state.frame;
    state.playing = false;
    state.lastTs = null;
    ui.play.textContent = state.frame >= state.sim.frame_times.length - 1 ? "Replay" : "Play";
    updateFrameUI();
  }

  function handleMapMove(evt) {
    if (!state.sim || !state.mapMetrics) { ui.tooltip.hidden = true; return; }
    const rect = ui.mapCanvas.getBoundingClientRect();
    const mx = evt.clientX - rect.left;
    const my = evt.clientY - rect.top;
    const g = state.mapMetrics;
    const i = state.frame;
    let best = null;
    let bestD2 = Infinity;
    for (const c of state.sim.clusters) {
      const reached = c.reached[i];
      if (!reached) continue;
      const p = project(c.lon, c.lat, g);
      const d2 = (p.x - mx) ** 2 + (p.y - my) ** 2;
      const radius = Math.max(8, Math.min(42, 2.5 + 1.9 * Math.sqrt(reached)));
      if (d2 <= radius ** 2 && d2 < bestD2) { best = c; bestD2 = d2; }
    }
    if (!best) { ui.tooltip.hidden = true; return; }
    const active = best.active[i], reached = best.reached[i];
    ui.tooltip.innerHTML = `<strong>Seed #${best.id}</strong>
      θ = ${best.theta.toFixed(2)} · arrival t = ${best.arrival.toFixed(2)}<br>
      actively infected = ${active.toLocaleString("en-US")} · ever infected = ${reached.toLocaleString("en-US")}<br>
      b - d = ${best.net_growth.toFixed(3)} ${best.supercritical ? "(supercritical)" : "(subcritical)"}`;
    ui.tooltip.hidden = false;
    const wrapRect = ui.mapWrap.getBoundingClientRect();
    let left = evt.clientX - wrapRect.left + 12;
    let top = evt.clientY - wrapRect.top + 12;
    if (left + 210 > wrapRect.width) left -= 220;
    if (top + 92 > wrapRect.height) top -= 100;
    ui.tooltip.style.left = `${Math.max(6, left)}px`;
    ui.tooltip.style.top = `${Math.max(6, top)}px`;
  }

  async function init() {
    try {
      const response = await fetch("/api/model", { cache: "no-store" });
      if (!response.ok) throw new Error("Could not load model metadata.");
      state.meta = await response.json();
      applyDefaults();
      await loadLayer();
      await runSimulation();
    } catch (err) {
      console.error(err);
      setStatus(err.message || String(err), "error");
    }
  }

  ui.optimum.addEventListener("input", markDirty);
  ui.maxChainLength.addEventListener("input", markDirty);
  for (const el of [ui.D, ui.beta0, ui.beta1, ui.b0, ui.d0, ui.duration, ui.seed]) el.addEventListener("input", markDirty);
  ui.defaultsBtn.addEventListener("click", applyDefaults);
  ui.runBtn.addEventListener("click", runSimulation);
  ui.newBtn.addEventListener("click", () => { ui.seed.value = String((Number(ui.seed.value) || 0) + 1); runSimulation(); });
  ui.layer.addEventListener("change", loadLayer);
  ui.play.addEventListener("click", togglePlay);
  ui.timeline.addEventListener("input", handleTimeline);
  ui.mapCanvas.addEventListener("mousemove", handleMapMove);
  ui.mapCanvas.addEventListener("mouseleave", () => { ui.tooltip.hidden = true; });
  window.addEventListener("resize", () => { drawMap(); drawChart(); });

  requestAnimationFrame(animate);
  init();
})();
