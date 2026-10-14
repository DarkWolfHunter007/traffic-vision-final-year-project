/**
 * Traffic Vision Status-Aware Research Dashboard ES Module
 * Dependency-free, accessible, pure vanilla JavaScript client.
 */

function badgeHtml(status) {
  const s = (status || "unavailable").toLowerCase();
  const labelMap = {
    valid: "Valid",
    invalid: "Invalid",
    unavailable: "Unavailable",
    unvalidated: "Unvalidated",
  };
  const label = labelMap[s] || "Unavailable";
  return `<span class="status-badge status-${s}">${label}</span>`;
}

function formatValue(val, unit = "") {
  if (val === null || val === undefined) {
    return `<span class="status-badge status-unavailable">Unavailable</span>`;
  }
  return `${val}${unit ? " " + unit : ""}`;
}

function formatNumber(val, decimals = 1, unit = "") {
  if (val === null || val === undefined) {
    return `<span class="status-badge status-unavailable">Unavailable</span>`;
  }
  const num = typeof val === "number" ? val.toFixed(decimals) : val;
  return `${num}${unit ? " " + unit : ""}`;
}

function formatText(val, unit = "") {
  if (val === null || val === undefined) {
    return "Unavailable";
  }
  return `${val}${unit ? " " + unit : ""}`;
}

function renderVolumeChart(bins) {
  const svg = document.getElementById("volume-chart");
  if (!svg) return;

  if (!bins || bins.length === 0) {
    svg.innerHTML = `
      <text x="380" y="90" text-anchor="middle" fill="#64748b" font-size="14">
        No volume bin data recorded for this run
      </text>`;
    return;
  }

  // Aggregate counts by bin_start_s without converting missing counts to 0
  const binMap = new Map();
  for (const b of bins) {
    const t = (b.bin_start_s !== null && b.bin_start_s !== undefined) ? b.bin_start_s : null;
    const key = t !== null ? String(t) : `unknown_${Math.random()}`;
    if (!binMap.has(key)) {
      binMap.set(key, { startTime: t, count: 0, hasCount: false });
    }
    const entry = binMap.get(key);
    if (b.count !== null && b.count !== undefined) {
      entry.count += Number(b.count);
      entry.hasCount = true;
    }
  }

  const entries = Array.from(binMap.values());
  const sortedBins = entries.sort((a, b) => {
    if (a.startTime === null) return 1;
    if (b.startTime === null) return -1;
    return a.startTime - b.startTime;
  });

  const availableCounts = sortedBins.filter(e => e.hasCount).map(e => e.count);
  const maxCount = availableCounts.length > 0 ? Math.max(...availableCounts, 1) : 1;

  const width = 760;
  const height = 180;
  const padLeft = 50;
  const padRight = 20;
  const padBottom = 30;
  const padTop = 20;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;
  const barWidth = Math.max(6, Math.min(40, (chartW / sortedBins.length) * 0.7));
  const step = chartW / sortedBins.length;

  let elements = [];

  // Y-axis gridlines
  elements.push(`
    <line x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}" stroke="#334155" stroke-dasharray="3,3" />
    <line x1="${padLeft}" y1="${padTop + chartH / 2}" x2="${width - padRight}" y2="${padTop + chartH / 2}" stroke="#334155" stroke-dasharray="3,3" />
    <line x1="${padLeft}" y1="${padTop + chartH}" x2="${width - padRight}" y2="${padTop + chartH}" stroke="#475569" />
    <text x="${padLeft - 8}" y="${padTop + 4}" fill="#94a3b8" font-size="10" text-anchor="end">${maxCount}</text>
    <text x="${padLeft - 8}" y="${padTop + chartH / 2 + 4}" fill="#94a3b8" font-size="10" text-anchor="end">${Math.round(maxCount / 2)}</text>
    <text x="${padLeft - 8}" y="${padTop + chartH + 4}" fill="#94a3b8" font-size="10" text-anchor="end">0</text>
  `);

  let unavailableCount = 0;

  // Bars
  sortedBins.forEach((entry, idx) => {
    const x = padLeft + idx * step + (step - barWidth) / 2;
    const startTime = entry.startTime;
    const timeLabel = startTime !== null ? `${Math.round(startTime / 60)}m` : "Unavailable";

    if (entry.hasCount) {
      const count = entry.count;
      const barH = (count / maxCount) * chartH;
      const y = padTop + chartH - barH;

      elements.push(`
        <rect x="${x}" y="${y}" width="${barWidth}" height="${barH}" fill="#38bdf8" rx="2">
          <title>Start: ${startTime !== null ? startTime + "s" : "Unavailable"} (${timeLabel}) — Count: ${count}</title>
        </rect>
        <text x="${x + barWidth / 2}" y="${padTop + chartH + 16}" fill="#94a3b8" font-size="9" text-anchor="middle">${timeLabel}</text>
        <text x="${x + barWidth / 2}" y="${y - 4}" fill="#cbd5e1" font-size="9" text-anchor="middle">${count}</text>
      `);
    } else {
      unavailableCount++;
      elements.push(`
        <rect x="${x}" y="${padTop}" width="${barWidth}" height="${chartH}" fill="rgba(148, 163, 184, 0.08)" stroke="#64748b" stroke-dasharray="2,2" rx="2">
          <title>Start: ${startTime !== null ? startTime + "s" : "Unavailable"} (${timeLabel}) — Count: Unavailable</title>
        </rect>
        <text x="${x + barWidth / 2}" y="${padTop + chartH + 16}" fill="#94a3b8" font-size="9" text-anchor="middle">${timeLabel}</text>
        <text x="${x + barWidth / 2}" y="${padTop + 14}" fill="#94a3b8" font-size="8" text-anchor="middle">Unavailable</text>
      `);
    }
  });

  if (unavailableCount > 0) {
    elements.push(`
      <text x="${width - padRight}" y="${padTop - 6}" fill="#94a3b8" font-size="9" text-anchor="end">* ${unavailableCount} bin(s) with unavailable count</text>
    `);
  }

  svg.innerHTML = elements.join("\n");
}

async function loadRunDetails(runId) {
  if (!runId) return;

  const exportBanner = document.getElementById("export-status");
  if (exportBanner) exportBanner.textContent = "";

  try {
    // 1. Fetch summary
    const summaryRes = await fetch(`/api/runs/${encodeURIComponent(runId)}/summary`);
    if (!summaryRes.ok) throw new Error(`Summary fetch failed: ${summaryRes.status}`);
    const summary = await summaryRes.json();

    // 2. Fetch volume bins
    const binsRes = await fetch(`/api/runs/${encodeURIComponent(runId)}/volume-bins`);
    const binsData = binsRes.ok ? await binsRes.json() : { bins: [], observed_period_summary: [] };

    // Update Video Metadata
    const vm = summary.video_metadata || {};
    document.getElementById("vm-video-id").textContent = vm.video_id || "Unavailable";
    document.getElementById("vm-filename").textContent = vm.filename || "Unavailable";
    document.getElementById("vm-sha256").textContent = vm.sha256 || "Unavailable";
    document.getElementById("vm-resolution").textContent = (vm.width !== null && vm.width !== undefined && vm.height !== null && vm.height !== undefined)
      ? `${vm.width} × ${vm.height}`
      : "Unavailable";
    document.getElementById("vm-fps").textContent = formatText(vm.fps_nominal, "fps");
    document.getElementById("vm-duration").textContent = formatText(vm.duration_s, "s");
    document.getElementById("vm-frames").textContent = formatText(vm.frame_count);
    document.getElementById("vm-vfr").textContent = (vm.variable_frame_rate !== null && vm.variable_frame_rate !== undefined)
      ? (vm.variable_frame_rate ? "Yes (Variable Frame Rate)" : "No (Constant Frame Rate)")
      : "Unavailable";
    document.getElementById("vm-wall-clock").textContent = vm.wall_clock_start || "Unavailable";

    // Update Validation Status Badges
    const vs = summary.validation_status || {};
    document.getElementById("st-calibration").outerHTML = badgeHtml(vs.calibration);
    document.getElementById("st-calibration") || (document.querySelector(".status-grid").children[0].lastElementChild.id = "st-calibration");
    document.getElementById("st-tracking").outerHTML = badgeHtml(vs.tracking);
    document.getElementById("st-speed").outerHTML = badgeHtml(vs.speed);
    document.getElementById("st-queue").outerHTML = badgeHtml(vs.queue);
    document.getElementById("st-counting").outerHTML = badgeHtml(vs.counting);
    document.getElementById("st-ground-truth").outerHTML = badgeHtml(vs.ground_truth);

    // Update Tracking Quality
    const tq = summary.tracking_quality || {};
    document.getElementById("tq-total-tracks").textContent = formatText(tq.total_tracks);
    document.getElementById("tq-observations").textContent = formatText(tq.total_observations);
    document.getElementById("tq-calibrated-pts").textContent = formatText(tq.calibrated_points_count);
    const dist = tq.trajectory_status_counts || {};
    document.getElementById("tq-complete").textContent = formatText(dist.complete);
    document.getElementById("tq-active").textContent = formatText(dist.active);
    document.getElementById("tq-fragmented").textContent = formatText(dist.fragmented);
    document.getElementById("tq-invalid").textContent = formatText(dist.invalid);

    // Update Volume Bins & Chart
    const bins = binsData.bins || [];
    const pill = document.getElementById("bins-summary-pill");
    if (pill) {
      if (bins.length === 0) {
        pill.textContent = "0 bins recorded";
      } else {
        let totalCount = 0;
        let hasAvailableCount = false;
        let hasUnavailableCount = false;

        for (const b of bins) {
          if (b.count !== null && b.count !== undefined) {
            totalCount += Number(b.count);
            hasAvailableCount = true;
          } else {
            hasUnavailableCount = true;
          }
        }

        if (!hasAvailableCount) {
          pill.textContent = `${bins.length} bins recorded (vehicle count Unavailable)`;
        } else if (hasUnavailableCount) {
          pill.textContent = `${bins.length} bins recorded (${totalCount} vehicles recorded, some Unavailable)`;
        } else {
          pill.textContent = `${bins.length} bins recorded (${totalCount} vehicles)`;
        }
      }
    }

    renderVolumeChart(bins);

    const tbody = document.getElementById("bins-table-body");
    if (tbody) {
      if (bins.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">No volume bins recorded for this run.</td></tr>`;
      } else {
        tbody.innerHTML = bins.map(b => `
          <tr>
            <td>${formatText(b.bin_start_s, "s")}</td>
            <td>${formatText(b.observed_duration_s, "s")}</td>
            <td>${b.approach || "Unavailable"}</td>
            <td>${b.movement || "Unavailable"}</td>
            <td>${b.vehicle_class || "Unavailable"}</td>
            <td><strong>${formatText(b.count)}</strong></td>
            <td>${b.extrapolated_vehicles_per_hour !== null && b.extrapolated_vehicles_per_hour !== undefined ? b.extrapolated_vehicles_per_hour : badgeHtml("unavailable")}</td>
          </tr>
        `).join("");
      }
    }

    // Update Speed Summary
    const spd = summary.speed_summary || {};
    document.getElementById("spd-mean-kmh").innerHTML = formatNumber(spd.mean_speed_kmh, 1);
    document.getElementById("spd-max-kmh").innerHTML = formatNumber(spd.max_speed_kmh, 1);
    document.getElementById("spd-total").innerHTML = formatValue(spd.total_observations);
    document.getElementById("spd-valid").innerHTML = formatValue(spd.valid_count);
    document.getElementById("spd-invalid").innerHTML = formatValue(spd.invalid_count);
    document.getElementById("spd-unavailable").innerHTML = formatValue(spd.unavailable_count);
    document.getElementById("spd-mean-mps").innerHTML = formatNumber(spd.mean_speed_mps, 2, "m/s");
    document.getElementById("spd-max-mps").innerHTML = formatNumber(spd.max_speed_mps, 2, "m/s");

    // Update Queue Summary
    const q = summary.queue_summary || {};
    const qQueues = q.queues || {};
    const qStops = q.stops || {};
    document.getElementById("que-mean-m").innerHTML = formatNumber(qQueues.mean_queue_length_m, 1, "m");
    document.getElementById("que-max-m").innerHTML = formatNumber(qQueues.max_queue_length_m, 1, "m");
    document.getElementById("que-stops-total").innerHTML = formatValue(qStops.total);
    document.getElementById("que-stops-valid").innerHTML = formatValue(qStops.valid_stops);
    document.getElementById("que-stop-mean-dur").innerHTML = formatNumber(qStops.mean_duration_s, 1, "s");
    document.getElementById("que-total").innerHTML = formatValue(qQueues.total);
    document.getElementById("que-formed").innerHTML = formatValue(qQueues.formed_queues);
    document.getElementById("que-max-veh").innerHTML = formatValue(qQueues.max_queued_vehicles);

    // Update Review Status
    const rev = summary.review_status || {};
    document.getElementById("rev-total").textContent = formatText(rev.total_reviews);
    document.getElementById("rev-approved").textContent = formatText(rev.approved_count);
    document.getElementById("rev-pending").textContent = formatText(rev.pending_count);
    document.getElementById("rev-rejected").textContent = formatText(rev.rejected_count);
    document.getElementById("rev-class-corr").textContent = formatText(rev.class_corrected_count);
    document.getElementById("rev-bbox-corr").textContent = formatText(rev.bbox_corrected_count);
    document.getElementById("rev-snippets").textContent = formatText(rev.snippet_count);

    // Update Ground-Truth Comparison
    const gtRes = await fetch(`/api/runs/${encodeURIComponent(runId)}/ground-truth`);
    const gtData = gtRes.ok ? await gtRes.json() : { status: "unavailable", report: null };
    const gtBadge = document.getElementById("gt-status-badge");
    const gtMsg = document.getElementById("gt-message");
    const gtTbody = document.getElementById("gt-table-body");

    if (gtData.status === "valid" && gtData.report) {
      if (gtBadge) gtBadge.outerHTML = badgeHtml("valid");
      if (gtMsg) gtMsg.textContent = `Evaluated against reference set: ${gtData.report.ground_truth_set_name || gtData.report.ground_truth_set_id}. Error tolerance: ${gtData.report.error_tolerance_pct}%. Research audit only.`;
      const compRows = gtData.report.comparisons || [];
      if (gtTbody) {
        if (compRows.length === 0) {
          gtTbody.innerHTML = `<tr><td colspan="9" class="empty-cell">No comparison rows evaluated for this ground-truth set.</td></tr>`;
        } else {
          gtTbody.innerHTML = compRows.map(r => `
            <tr>
              <td>${r.segment_label || r.video_segment_id || "Clip"}</td>
              <td>${r.approach || "All"}</td>
              <td>${r.movement || "All"}</td>
              <td>${r.vehicle_class || "All"}</td>
              <td>${formatText(r.counted_count)}</td>
              <td>${formatText(r.observed_count)}</td>
              <td>${formatText(r.absolute_error)}</td>
              <td>${r.percentage_error !== null && r.percentage_error !== undefined ? r.percentage_error.toFixed(1) + "%" : "Unavailable"}</td>
              <td>${gtData.report.error_tolerance_pct !== null && gtData.report.error_tolerance_pct !== undefined ? gtData.report.error_tolerance_pct + "%" : "Unavailable"}</td>
            </tr>
          `).join("");
        }
      }
    } else {
      if (gtBadge) gtBadge.outerHTML = badgeHtml("unavailable");
      if (gtMsg) gtMsg.textContent = "No manual reference counts configured for this video. Ground-truth comparison unavailable.";
      if (gtTbody) {
        gtTbody.innerHTML = `<tr><td colspan="9" class="empty-cell">No manual reference counts configured for this run.</td></tr>`;
      }
    }

  } catch (err) {
    console.error("Failed to load run details:", err);
    if (exportBanner) {
      exportBanner.textContent = `Error loading run: ${err.message}`;
    }
  }
}

async function triggerExport(runId) {
  if (!runId) return;
  const btn = document.getElementById("btn-export");
  const banner = document.getElementById("export-status");
  if (btn) btn.disabled = true;
  if (banner) banner.textContent = `Exporting run '${runId}' in CSV, JSON, and SQLite formats...`;

  try {
    const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: "all", include_raw: true }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Export failed with status ${res.status}`);
    }

    const data = await res.json();
    if (banner) {
      banner.innerHTML = `<strong>Export complete:</strong> Saved to <code>${data.export_dir}</code>. Content hash: <code>${data.content_hash.substring(0, 16)}...</code> (${data.exported_files.length} files generated).`;
    }
  } catch (err) {
    if (banner) {
      banner.innerHTML = `<span style="color:#fda4af;">Export error: ${err.message}</span>`;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function initDashboard() {
  const selector = document.getElementById("run-selector");
  const exportBtn = document.getElementById("btn-export");

  try {
    const res = await fetch("/api/runs");
    if (!res.ok) throw new Error(`Runs fetch failed: ${res.status}`);
    const runs = await res.json();

    if (!runs || runs.length === 0) {
      selector.innerHTML = `<option value="" disabled selected>No processing runs found</option>`;
      return;
    }

    selector.innerHTML = runs.map(r => {
      const label = `${r.run_id} (${r.status} | ${r.notes || r.video_id})`;
      return `<option value="${r.run_id}">${label}</option>`;
    }).join("");

    selector.addEventListener("change", (e) => {
      loadRunDetails(e.target.value);
    });

    if (exportBtn) {
      exportBtn.addEventListener("click", () => {
        triggerExport(selector.value);
      });
    }

    // Load first run by default
    if (runs[0]) {
      selector.value = runs[0].run_id;
      loadRunDetails(runs[0].run_id);
    }
  } catch (err) {
    console.error("Dashboard initialization failed:", err);
    selector.innerHTML = `<option value="" disabled selected>Failed to load runs: ${err.message}</option>`;
  }
}

document.addEventListener("DOMContentLoaded", initDashboard);
