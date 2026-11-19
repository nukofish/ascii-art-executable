"use strict";
const byId = id => document.getElementById(id);
const labels = {token: "Token integrity", geometry: "Shape geometry", compile: "C11 compilation", behavior: "Sample behavior"};
const explanations = {NO_FIXTURE: "Custom input · no behavior fixture", OUTPUT_TOO_LARGE: "Canvas exceeds behavior-test limit", TOKEN_NOT_PASS: "Waiting for a passing token check", COMPILE_NOT_PASS: "Compilation did not pass", GEOMETRY_NOT_PASS: "Geometry did not pass", CANCELLED: "Generation cancelled", PIPELINE_TIMEOUT: "Generation timed out", PIPELINE_STOPPED: "Generation stopped before this check"};
let samples = [];
let active = null;
let busy = false;
let cancelRequested = false;
let generatedSource = null;

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "The request failed");
    error.status = response.status;
    if (data.prepass) {
      byId("candidates").textContent = JSON.stringify(data.prepass, null, 2);
      byId("candidates").hidden = false;
    }
    throw error;
  }
  return data;
}
function status(message, error = false) {
  byId("status").textContent = message;
  byId("status").className = error ? "error" : "";
}
function showChecks(checks = {}) {
  byId("checks").replaceChildren();
  for (const [name, label] of Object.entries(labels)) {
    const check = checks[name] || {status: "NOT_RUN", reason: null};
    const card = document.createElement("div");
    card.className = "check";
    const top = document.createElement("div");
    top.className = "check-top";
    const heading = document.createElement("h3");
    heading.textContent = label;
    const badge = document.createElement("span");
    badge.className = "badge " + (check.status === "PASS" ? "pass" : check.status === "FAIL" ? "fail" : "");
    badge.textContent = check.status.replace("_", " ");
    top.append(heading, badge);
    const reason = document.createElement("p");
    reason.textContent = check.reason ? (explanations[check.reason] || check.reason) : (check.status === "PASS" ? "Check passed" : check.status === "FAIL" ? "See diagnostics below" : "Not run");
    card.append(top, reason);
    byId("checks").append(card);
  }
}
function resetResult() {
  sessionStorage.removeItem("codeart-job");
  generatedSource = null;
  byId("artwork-preview").hidden = true;
  byId("output-preamble").hidden = true;
  byId("output-preamble").textContent = "";
  byId("output").textContent = "";
  byId("copy-source").hidden = true;
  byId("copy-source").textContent = "Copy code";
  byId("copy-feedback").textContent = "";
  byId("empty").hidden = false;
  byId("dimensions").textContent = "";
  byId("metrics").hidden = true;
  byId("download").hidden = true;
  byId("report").hidden = true;
  byId("diagnostics").hidden = true;
  byId("export-note").textContent = "";
  byId("attempt-rows").replaceChildren();
  byId("attempt-count").textContent = "";
  byId("summary").textContent = "Waiting for a result";
  showChecks();
}
function setBusy(value) {
  busy = value;
  if (!value) cancelRequested = false;
  byId("controls").disabled = value;
  byId("source").readOnly = value;
  byId("file").disabled = value;
  byId("file-mode").disabled = value;
  byId("program-mode").disabled = value;
  byId("function").disabled = value;
  byId("inspect-file").disabled = value;
  byId("cancel").hidden = !value;
  byId("cancel").disabled = false;
  byId("generate").textContent = value ? "Generating…" : "Generate artwork ↗";
}
function syncFileScope() {
  byId("file-scope").hidden = !byId("file-mode").checked;
  if (!byId("file-mode").checked) byId("candidates").hidden = true;
  byId("program-scope").hidden = !byId("program-mode").checked;
  byId("file-controls").hidden = byId("program-mode").checked;
  byId("input-encoding").textContent = byId("program-mode").checked ? "C11 · UTF-8" : "C11 · ASCII";
  byId("input-kind").textContent = byId("program-mode").checked ? "Complete C program"
    : byId("file-mode").checked ? "Extract one function"
      : byId("sample").value ? "Built-in sample · 8 behavior inputs" : "Custom function";
}
function showCandidates(extraction) {
  byId("function").replaceChildren(new Option("First eligible function", ""));
  for (const candidate of extraction.candidates) {
    const option = new Option(
      candidate.name + " · " + candidate.start_line + "–" + candidate.end_line + " · " + candidate.a_status,
      candidate.name
    );
    option.disabled = candidate.a_status !== "PASS";
    byId("function").append(option);
  }
  byId("function").value = extraction.selected || "";
  byId("candidates").textContent = JSON.stringify(
    extraction.candidates.map(({source_text, ...candidate}) => candidate), null, 2);
  byId("candidates").hidden = !extraction.candidates.length;
}
function showArtwork(text, widths = {}) {
  const output = byId("output");
  if (!Object.keys(widths).length) {
    output.textContent = text;
    return;
  }
  output.replaceChildren();
  let offset = 0;
  for (const match of text.matchAll(/[^\x00-\x7f]/gu)) {
    const [char] = match;
    const glyph = document.createElement("span");
    glyph.className = "artwork-glyph";
    glyph.style.width = widths[char] + "ch";
    glyph.textContent = char;
    output.append(text.slice(offset, match.index), glyph);
    offset = match.index + char.length;
  }
  output.append(text.slice(offset));
}
function render(job) {
  const result = job.result;
  byId("file-mode").checked = job.file_mode ?? Boolean(result.prepass);
  byId("program-mode").checked = job.program_mode ?? result.program_mode ?? false;
  syncFileScope();
  if (result.prepass) showCandidates(result.prepass);
  showChecks(result.checks);
  if (result.source_text !== null) {
    generatedSource = result.source_text;
    const prefix = result.preamble_text || "";
    byId("output-preamble").textContent = prefix;
    byId("output-preamble").hidden = !prefix;
    showArtwork(generatedSource.slice(prefix.length), result.artwork_character_widths);
    byId("artwork-preview").hidden = false;
    byId("empty").hidden = true;
    byId("copy-source").hidden = false;
    byId("download").href = "/api/jobs/" + job.id + "/source.c";
    byId("download").hidden = false;
  }
  byId("report").href = "/api/jobs/" + job.id + "/report.json";
  byId("report").hidden = false;
  byId("export-note").textContent = result.verified ? "LF line endings · UTF-8" : "Review diagnostics before using this output.";
  const layout = result.layout;
  if (layout) {
    byId("dimensions").textContent = layout.width + " × " + layout.height + " CELLS";
    const preview = byId("artwork-preview");
    // The bundled font's advance is 0.60 em. Round up to leave room at the edge.
    preview.style.setProperty("--art-width-em", layout.width * 0.61);
    preview.style.setProperty("--art-height-em", layout.height * 0.61 / (result.cell_aspect || 0.5));
  }
  byId("font-label").textContent = (result.font_id || "—") + " · fixed character grid";
  if (result.cell_aspect) {
    document.documentElement.style.setProperty("--cell-height", (1 / result.cell_aspect).toFixed(4) + "ch");
  }
  const metrics = byId("metrics");
  metrics.replaceChildren();
  const values = [
    ["Grid", layout ? layout.width + " × " + layout.height : "—"],
    ["Actual scale", layout ? layout.scale.toFixed(3) + "×" : "—"],
    ["Attempts", layout ? layout.attempts : result.attempt_history.length],
    ["Code fill", result.code_fill_ratio == null ? "—" : (result.code_fill_ratio * 100).toFixed(2) + "%"],
    ["Coverage", result.coverage ? (result.coverage.total * 100).toFixed(2) + "%" : "—"],
    ["Elapsed", job.elapsed_s.toFixed(2) + " s"]
  ];
  for (const [label, value] of values) {
    const item = document.createElement("div");
    item.className = "metric";
    item.textContent = label;
    const number = document.createElement("strong");
    number.textContent = value;
    item.append(number);
    metrics.append(item);
  }
  metrics.hidden = false;
  const diagnostics = byId("diagnostics");
  diagnostics.replaceChildren();
  if (result.prepass && result.prepass.error) {
    const paragraph = document.createElement("p");
    paragraph.textContent = "Function extraction · " + result.prepass.error;
    diagnostics.append(paragraph);
  }
  for (const item of result.diagnostics) {
    const paragraph = document.createElement("p");
    const position = item.line ? " at " + item.line + (item.column ? ":" + item.column : "") : "";
    paragraph.textContent = item.code + " · " + item.stage + position + " — " + item.message;
    diagnostics.append(paragraph);
    if (Object.keys(item.details).length) {
      const detail = document.createElement("pre");
      detail.textContent = JSON.stringify(item.details, null, 2);
      diagnostics.append(detail);
    }
  }
  const diff = result.verification && result.verification.first_diff;
  if (diff) {
    const detail = document.createElement("pre");
    detail.textContent = "First token difference · " + JSON.stringify(diff, null, 2);
    diagnostics.append(detail);
  }
  diagnostics.hidden = !diagnostics.childElementCount;
  byId("attempt-rows").replaceChildren();
  for (const attempt of result.attempt_history) {
    const row = document.createElement("tr");
    for (const value of [attempt.scale.toFixed(3) + "×", attempt.width + " × " + attempt.height,
      attempt.failure_token_index === null ? "—" : attempt.failure_token_index,
      attempt.reason || "Placed successfully", attempt.elapsed_s.toFixed(3)]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    byId("attempt-rows").append(row);
  }
  byId("attempt-count").textContent = "(" + result.attempt_history.length + ")";
  const message = result.verified ? (result.checks.behavior.status === "PASS" ? "All four checks passed." : "Token, geometry and compilation passed. Behavior was not run.") : "Generation finished with issues. Review the checks and diagnostics.";
  byId("summary").textContent = result.verified ? "Verified" : "Review required";
  status(message + (result.code_fill_warning ? " " + result.code_fill_warning : ""), !result.verified);
}
byId("copy-source").addEventListener("click", async () => {
  const source = generatedSource;
  if (source === null) return;
  try {
    await navigator.clipboard.writeText(source);
    if (source === generatedSource) {
      byId("copy-source").textContent = "Copied";
      byId("copy-feedback").textContent = "Complete source copied.";
    }
  } catch {
    if (source === generatedSource) status("Clipboard unavailable. Use Download .c source.", true);
  }
});
async function poll(identifier) {
  if (active !== identifier) return;
  try {
    const job = await api("/api/jobs/" + identifier);
    if (active !== identifier) return;
    if (job.state === "running") {
      window.setTimeout(() => poll(identifier), 350);
      return;
    }
    render(job);
    active = null;
    if (!(job.file_mode || job.program_mode) || job.result.status !== "OK") {
      sessionStorage.removeItem("codeart-job");
    }
    setBusy(false);
  } catch (error) {
    if (active !== identifier) return;
    status(error.message, true);
    if (error.status === 404) {
      active = null;
      sessionStorage.removeItem("codeart-job");
      setBusy(false);
    } else {
      window.setTimeout(() => poll(identifier), 3000);
    }
  }
}
byId("generator").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  resetResult();
  setBusy(true);
  status("Analyzing, arranging and verifying your source…");
  try {
    const response = await api("/api/generate", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({source: byId("source").value, shape: byId("shape").value,
        file_mode: byId("file-mode").checked,
        program_mode: byId("program-mode").checked,
        function: byId("function").value || null,
        scale: Number(byId("scale").value), sample: byId("sample").value || null})
    });
    active = response.id;
    sessionStorage.setItem("codeart-job", active);
    if (cancelRequested) await cancelGeneration();
    poll(active);
  } catch (error) {
    setBusy(false);
    status(error.message, true);
  }
});
async function cancelGeneration() {
  if (!busy) return;
  cancelRequested = true;
  byId("cancel").disabled = true;
  status("Cancellation requested. Waiting for the current work to stop…");
  if (!active) return;
  try {
    await api("/api/jobs/" + active + "/cancel", {method: "POST"});
  } catch (error) {
    status(error.message, true);
    byId("cancel").disabled = false;
  }
}
byId("cancel").addEventListener("click", cancelGeneration);
byId("sample").addEventListener("change", () => {
  const sample = samples.find(item => item.name === byId("sample").value);
  if (sample) {
    byId("source").value = sample.source;
    byId("file-mode").checked = false;
    byId("program-mode").checked = false;
    byId("function").replaceChildren(new Option("First eligible function", ""));
    byId("candidates").textContent = "";
    byId("candidates").hidden = true;
  }
  syncFileScope();
  resetResult();
});
byId("program-mode").addEventListener("change", () => {
  if (byId("program-mode").checked) {
    byId("file-mode").checked = false;
    byId("sample").value = "";
  }
  syncFileScope();
  resetResult();
});
byId("file-mode").addEventListener("change", () => {
  if (byId("file-mode").checked) byId("program-mode").checked = false;
  else byId("candidates").hidden = true;
  syncFileScope();
  resetResult();
});
byId("source").addEventListener("input", () => {
  byId("sample").value = "";
  syncFileScope();
  resetResult();
  status("Source changed. Generate to update the result.");
});
for (const id of ["shape", "scale"]) byId(id).addEventListener("change", resetResult);
byId("function").addEventListener("change", resetResult);
byId("file").addEventListener("change", async event => {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 900000) { status("Choose a source file smaller than 900 KB.", true); return; }
  byId("source").value = await file.text();
  byId("file-mode").checked = false;
  byId("program-mode").checked = true;
  syncFileScope();
  byId("source").dispatchEvent(new Event("input"));
});
showChecks();
Promise.all([api("/api/samples"), api("/api/environment")]).then(([data, environment]) => {
  samples = data;
  for (const sample of samples) {
    const option = document.createElement("option");
    option.value = sample.name;
    option.textContent = sample.name + "() · 8 inputs";
    byId("sample").append(option);
  }
  byId("environment").textContent = JSON.stringify(environment, null, 2);
  const previous = sessionStorage.getItem("codeart-job");
  if (previous) {
    active = previous;
    setBusy(true);
    api("/api/jobs/" + previous).then(job => {
      byId("source").value = job.input_source ?? job.source;
      byId("file-mode").checked = job.file_mode ?? Boolean(job.result && job.result.prepass);
      byId("program-mode").checked = job.program_mode ?? job.result?.program_mode ?? false;
      if (job.result && job.result.prepass) showCandidates(job.result.prepass);
      else if (job.file_mode && job.function) {
        byId("function").append(new Option(job.function, job.function));
        byId("function").value = job.function;
      }
      byId("shape").value = job.shape;
      byId("scale").value = String(job.scale);
      byId("sample").value = job.sample || "";
      syncFileScope();
      poll(previous);
    }).catch(error => {
      sessionStorage.removeItem("codeart-job");
      active = null;
      setBusy(false);
      status(error.message, true);
    });
  }
}).catch(error => status(error.message, true));

byId("inspect-file").addEventListener("click", async () => {
  if (busy) return;
  byId("inspect-file").disabled = true;
  try {
    const data = await api("/api/prepass", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({source: byId("source").value})});
    byId("file-mode").checked = true;
    showCandidates(data);
    syncFileScope();
    resetResult();
    status(data.error || data.validation_scope, Boolean(data.error));
  } catch (error) { status(error.message, true); }
  finally { byId("inspect-file").disabled = false; }
});
byId("source").addEventListener("input", () => {
  byId("function").replaceChildren(new Option("First eligible function", ""));
  byId("candidates").textContent = "";
  byId("candidates").hidden = true;
});
syncFileScope();
