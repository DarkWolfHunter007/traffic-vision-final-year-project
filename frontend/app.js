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

  // Aggregate counts by bin_start_s
  const binMap = new Map();
  for (const b of bins) {
    const t = b.bin_start_s || 0;
    binMap.set(t, (binMap.get(t) || 0) + (b.count || 0));
  }

  const sortedBins = Array.from(binMap.entries()).sort((a, b) => a[0] - b[0]);
  const maxCount = Math.max(...sortedBins.map(([, c]) => c), 1);

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

  // Bars
  sortedBins.forEach(([startTime, count], idx) => {
    const barH = (count / maxCount) * chartH;
    const x = padLeft + idx * step + (step - barWidth) / 2;
    const y = padTop + chartH - barH;
    const timeLabel = `${Math.round(startTime / 60)}m`;

    elements.push(`
      <rect x="${x}" y="${y}" width="${barWidth}" height="${barH}" fill="#38bdf8" rx="2">
        <title>Start: ${startTime}s (${timeLabel}) — Count: ${count}</title>
      </rect>
      <text x="${x + barWidth / 2}" y="${padTop + chartH + 16}" fill="#94a3b8" font-size="9" text-anchor="middle">${timeLabel}</text>
      <text x="${x + barWidth / 2}" y="${y - 4}" fill="#cbd5e1" font-size="9" text-anchor="middle">${count}</text>
    `);
  });

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
    document.getElementById("vm-resolution").textContent = (vm.width && vm.height) ? `${vm.width} × ${vm.height}` : "Unavailable";
    document.getElementById("vm-fps").textContent = vm.fps_nominal !== undefined ? `${vm.fps_nominal} fps` : "Unavailable";
    document.getElementById("vm-duration").textContent = vm.duration_s !== undefined ? `${vm.duration_s} s` : "Unavailable";
    document.getElementById("vm-frames").textContent = vm.frame_count !== undefined ? vm.frame_count : "Unavailable";
    document.getElementById("vm-vfr").textContent = vm.variable_frame_rate ? "Yes (Variable Frame Rate)" : "No (Constant Frame Rate)";
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
    document.getElementById("tq-total-tracks").textContent = tq.total_tracks !== undefined ? tq.total_tracks : "Unavailable";
    document.getElementById("tq-observations").textContent = tq.total_observations !== undefined ? tq.total_observations : "Unavailable";
    document.getElementById("tq-calibrated-pts").textContent = tq.calibrated_points_count !== undefined ? tq.calibrated_points_count : "Unavailable";
    const dist = tq.trajectory_status_counts || {};
    document.getElementById("tq-complete").textContent = dist.complete !== undefined ? dist.complete : "Unavailable";
    document.getElementById("tq-active").textContent = dist.active !== undefined ? dist.active : "Unavailable";
    document.getElementById("tq-fragmented").textContent = dist.fragmented !== undefined ? dist.fragmented : "Unavailable";
    document.getElementById("tq-invalid").textContent = dist.invalid !== undefined ? dist.invalid : "Unavailable";

    // Update Volume Bins & Chart
    const bins = binsData.bins || [];
    const pill = document.getElementById("bins-summary-pill");
    const totalCount = bins.reduce((acc, b) => acc + (b.count || 0), 0);
    if (pill) {
      pill.textContent = `${bins.length} bins recorded (${totalCount} vehicles)`;
    }

    renderVolumeChart(bins);

    const tbody = document.getElementById("bins-table-body");
    if (tbody) {
      if (bins.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">No volume bins recorded for this run.</td></tr>`;
      } else {
        tbody.innerHTML = bins.map(b => `
          <tr>
            <td>${b.bin_start_s !== undefined ? b.bin_start_s + " s" : "Unavailable"}</td>
            <td>${b.observed_duration_s !== null && b.observed_duration_s !== undefined ? b.observed_duration_s + " s" : "Unavailable"}</td>
            <td>${b.approach || "Unavailable"}</td>
            <td>${b.movement || "Unavailable"}</td>
            <td>${b.vehicle_class || "Unavailable"}</td>
            <td><strong>${b.count !== undefined ? b.count : "Unavailable"}</strong></td>
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
    document.getElementById("rev-total").textContent = rev.total_reviews !== undefined ? rev.total_reviews : "0";
    document.getElementById("rev-approved").textContent = rev.approved_count !== undefined ? rev.approved_count : "0";
    document.getElementById("rev-pending").textContent = rev.pending_count !== undefined ? rev.pending_count : "0";
    document.getElementById("rev-rejected").textContent = rev.rejected_count !== undefined ? rev.rejected_count : "0";
    document.getElementById("rev-class-corr").textContent = rev.class_corrected_count !== undefined ? rev.class_corrected_count : "0";
    document.getElementById("rev-bbox-corr").textContent = rev.bbox_corrected_count !== undefined ? rev.bbox_corrected_count : "0";
    document.getElementById("rev-snippets").textContent = rev.snippet_count !== undefined ? rev.snippet_count : "0";

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
              <td>${r.counted_count}</td>
              <td>${r.observed_count}</td>
              <td>${r.absolute_error}</td>
              <td>${r.percentage_error !== null ? r.percentage_error.toFixed(1) + "%" : "N/A"}</td>
              <td>${gtData.report.error_tolerance_pct}%</td>
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
