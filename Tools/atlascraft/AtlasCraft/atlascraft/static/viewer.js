/* AtlasCraft offline viewer. No network requests or external dependencies. */
"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const data = JSON.parse($("atlas-data").textContent);
  const regions = new Map(data.regions.map(r => [r.id, r]));
  const [nz, ny, nx] = data.shape;
  const state = {selected: null, x: Math.floor(nx / 2), y: Math.floor(ny / 2), z: Math.floor(nz / 2), evidence: false};
  const anchors = new Set((data.metadata.anchor_indices || []).map(Number));
  const evidenceNames = data.metadata.evidence_codes || {};
  const evidencePalette = ["#f6f4ec", "#398375", "#cfac65", "#527fa0", "#a97888", "#857eab", "#cf8865", "#869e6b"];
  let labels, evidence, meshes, scene;
  const fmt = v => Number(v) !== 0 && Math.abs(Number(v)) < 0.0001 ? Number(v).toExponential(2) : Number(v).toLocaleString(undefined, {maximumFractionDigits: 4});
  const index = (z, y, x) => (z * ny + y) * nx + x;
  const hex = color => [1, 3, 5].map(i => parseInt(color.slice(i, i + 2), 16));
  const evidenceName = code => {
    const value = evidenceNames[String(code)];
    return typeof value === "string" ? value : value && typeof value === "object" ? (value.description || value.name || JSON.stringify(value)) : `Evidence code ${code}`;
  };
  function evidenceColor(code) {
    return evidencePalette[code % evidencePalette.length];
  }
  async function inflate(encoded, Type) {
    if (!globalThis.DecompressionStream) throw new Error("This offline file needs a current browser with local gzip decompression. Open it in a current version of Chrome, Edge, Firefox or Safari.");
    const binary = atob(encoded), bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    const array = new Type(await new Response(stream).arrayBuffer());
    return array;
  }
  function notice(message) { $("error").textContent = message; $("error").hidden = false; }
  function multiply(a, b) {
    const out = new Float32Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k];
    return out;
  }
  const identity = () => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  class SurfaceScene {
    constructor(canvas, models) {
      this.canvas = canvas; this.models = models;
      const gl = canvas.getContext("webgl", {antialias: true, alpha: true, preserveDrawingBuffer: false});
      if (!gl || !gl.getExtension("OES_element_index_uint")) throw new Error("3D rendering is unavailable in this browser or graphics configuration. Native slices and surface downloads remain available.");
      this.gl = gl;
      const vertexSource = `attribute vec3 a_position; attribute vec3 a_normal; uniform mat4 u_mvp; uniform mat4 u_rotation; uniform vec3 u_center; varying vec3 v_normal; void main(){vec3 p=a_position-u_center; vec3 n=a_normal; vec3 mapped=vec3(p.x,p.z,-p.y); v_normal=(u_rotation*vec4(n.x,n.z,-n.y,0.0)).xyz; gl_Position=u_mvp*vec4(mapped,1.0);}`;
      const fragmentSource = `precision mediump float; varying vec3 v_normal; uniform vec3 u_color; uniform float u_dim; void main(){vec3 n=normalize(v_normal); float light=0.42+0.48*abs(dot(n,normalize(vec3(-0.5,0.8,1.0))))+0.10*abs(dot(n,vec3(1.0,0.0,0.0))); vec3 c=mix(vec3(0.82,0.86,0.81),u_color,u_dim); gl_FragColor=vec4(c*light,1.0);}`;
      const shader = (type, source) => { const s = gl.createShader(type); gl.shaderSource(s, source); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
      this.program = gl.createProgram(); gl.attachShader(this.program, shader(gl.VERTEX_SHADER, vertexSource)); gl.attachShader(this.program, shader(gl.FRAGMENT_SHADER, fragmentSource)); gl.linkProgram(this.program);
      if (!gl.getProgramParameter(this.program, gl.LINK_STATUS)) throw new Error("Unable to initialize the local 3D shaders.");
      gl.useProgram(this.program); this.attributes = {};
      for (const name of ["a_position", "a_normal"]) this.attributes[name] = gl.getAttribLocation(this.program, name);
      this.uniforms = {};
      for (const name of ["u_mvp", "u_rotation", "u_center", "u_color", "u_dim"]) this.uniforms[name] = gl.getUniformLocation(this.program, name);
      for (const mesh of models) {
        mesh.buffers = {};
        for (const name of ["vertices", "normals", "faces"]) {
          const target = name === "faces" ? gl.ELEMENT_ARRAY_BUFFER : gl.ARRAY_BUFFER;
          const b = gl.createBuffer(); gl.bindBuffer(target, b); gl.bufferData(target, mesh[name], gl.STATIC_DRAW); mesh.buffers[name] = b;
        }
      }
      const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
      for (const mesh of models) for (let i = 0; i < mesh.vertices.length; i++) { const axis = i % 3; low[axis] = Math.min(low[axis], mesh.vertices[i]); high[axis] = Math.max(high[axis], mesh.vertices[i]); }
      if (!models.length) for (let axis = 0; axis < 3; axis++) { low[axis] = data.edges[axis][0]; high[axis] = data.edges[axis].at(-1); }
      this.center = low.map((v, i) => (v + high[i]) / 2);
      this.radius = Math.hypot(...high.map((v, i) => v - low[i])) / 2 || 1;
      this.reset(); this.bind();
      new ResizeObserver(() => this.draw()).observe(canvas);
    }
    reset() { this.yaw = 0.62; this.pitch = -0.22; this.zoom = 1; this.pan = [0, 0]; this.draw(); }
    bind() {
      let previous = null;
      this.canvas.addEventListener("pointerdown", e => { previous = [e.clientX, e.clientY]; this.canvas.setPointerCapture(e.pointerId); this.canvas.style.cursor = "grabbing"; });
      this.canvas.addEventListener("pointermove", e => {
        if (!previous) return;
        const dx = e.clientX - previous[0], dy = e.clientY - previous[1]; previous = [e.clientX, e.clientY];
        if (e.shiftKey || e.buttons === 2) { const scale = 2.4 * this.radius / (this.canvas.clientHeight * this.zoom); this.pan[0] += dx * scale; this.pan[1] -= dy * scale; }
        else { this.yaw += dx * 0.009; this.pitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, this.pitch + dy * 0.009)); }
        this.draw();
      });
      const end = () => { previous = null; this.canvas.style.cursor = "grab"; };
      this.canvas.addEventListener("pointerup", end); this.canvas.addEventListener("pointercancel", end);
      this.canvas.addEventListener("contextmenu", e => e.preventDefault());
      this.canvas.addEventListener("wheel", e => { e.preventDefault(); this.zoom = Math.max(0.2, Math.min(12, this.zoom * Math.exp(-e.deltaY * 0.001))); this.draw(); }, {passive: false});
    }
    draw() {
      const gl = this.gl;
      if (!gl) return;
      const dpr = Math.min(2, devicePixelRatio || 1), width = Math.max(1, Math.round(this.canvas.clientWidth * dpr)), height = Math.max(1, Math.round(this.canvas.clientHeight * dpr));
      if (this.canvas.width !== width || this.canvas.height !== height) { this.canvas.width = width; this.canvas.height = height; }
      gl.viewport(0, 0, width, height); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE); gl.useProgram(this.program);
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), cx = Math.cos(this.pitch), sx = Math.sin(this.pitch);
      const ry = new Float32Array([cy, 0, -sy, 0, 0, 1, 0, 0, sy, 0, cy, 0, 0, 0, 0, 1]);
      const rx = new Float32Array([1, 0, 0, 0, 0, cx, sx, 0, 0, -sx, cx, 0, 0, 0, 0, 1]);
      const rotation = multiply(rx, ry), translate = identity(); translate[12] = this.pan[0]; translate[13] = this.pan[1];
      const span = 1.18 * this.radius / this.zoom, aspect = width / height;
      const mmPerPixel = 2 * span / this.canvas.clientHeight, target = 75 * mmPerPixel, power = 10 ** Math.floor(Math.log10(target));
      const scaleMm = [1, 2, 5, 10].map(n => n * power).filter(v => v <= target).at(-1) || power;
      $("scale-line").style.width = Math.round(scaleMm / mmPerPixel) + "px"; $("scale-label").textContent = `${fmt(scaleMm)} mm`;
      const projection = new Float32Array([1 / (span * aspect), 0, 0, 0, 0, 1 / span, 0, 0, 0, 0, -1 / (5 * this.radius), 0, 0, 0, 0, 1]);
      gl.uniformMatrix4fv(this.uniforms.u_mvp, false, multiply(projection, multiply(translate, rotation)));
      gl.uniformMatrix4fv(this.uniforms.u_rotation, false, rotation); gl.uniform3fv(this.uniforms.u_center, this.center);
      for (const mesh of this.models) {
        if (!visible(mesh.id)) continue;
        for (const [attribute, field] of [["a_position", "vertices"], ["a_normal", "normals"]]) { gl.bindBuffer(gl.ARRAY_BUFFER, mesh.buffers[field]); gl.enableVertexAttribArray(this.attributes[attribute]); gl.vertexAttribPointer(this.attributes[attribute], 3, gl.FLOAT, false, 0, 0); }
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mesh.buffers.faces);
        gl.uniform3fv(this.uniforms.u_color, hex(regions.get(mesh.id).color).map(v => v / 255));
        gl.uniform1f(this.uniforms.u_dim, state.selected === null || state.selected === mesh.id ? 1 : 0.32);
        gl.drawElements(gl.TRIANGLES, mesh.faces.length, gl.UNSIGNED_INT, 0);
      }
    }
  }
  function visible(id) { return (id !== 65535 || $("show-unknown").checked) && (!$("isolate").checked || state.selected === null || state.selected === id); }
  function renderRegions() {
    const query = $("region-search").value.toLowerCase(), container = $("region-list"); container.replaceChildren();
    for (const region of data.regions) {
      if (!region.id || !(region.name.toLowerCase().includes(query) || String(region.id).includes(query))) continue;
      const button = document.createElement("button"); button.className = "region-option" + (state.selected === region.id ? " active" : ""); button.setAttribute("role", "option"); button.setAttribute("aria-selected", state.selected === region.id ? "true" : "false");
      const swatch = document.createElement("i"); swatch.className = "swatch"; swatch.style.background = region.color;
      const name = document.createElement("span"); name.className = "region-text"; name.textContent = region.name;
      const id = document.createElement("span"); id.textContent = region.id;
      button.append(swatch, name, id); button.onclick = () => select(region.id); container.append(button);
    }
  }
  function select(id) {
    state.selected = id === 0 ? null : id;
    const region = regions.get(state.selected);
    $("selected-name").textContent = region ? region.name : "All regions";
    $("selected-detail").textContent = region ? `Label ${region.id} · ${region.voxels.toLocaleString()} native voxels${region.has_surface ? "" : " · present in native slices; too small for this surface preview"}` : "Select a region to inspect it.";
    $("selected-swatch").style.background = region ? region.color : "#b8c9bd";
    renderRegions(); drawSlices(); if (scene) scene.draw();
  }
  function colorFor(offset) {
    const id = labels[offset];
    if (id === 0 || !visible(id)) return [246, 244, 236];
    let rgb = state.evidence ? hex(evidenceColor(evidence[offset])) : hex(regions.get(id)?.color || "#a8afb0");
    if (state.selected !== null && state.selected !== id && !$("isolate").checked) rgb = rgb.map(c => Math.round(c * .35 + 238 * .65));
    return rgb;
  }
  const sliceGeometry = {};
  function drawSlice(axis) {
    const canvas = $("slice-" + axis), context = canvas.getContext("2d");
    const width = axis === "x" ? ny : nx, rows = axis === "z" ? ny : nz;
    const raw = document.createElement("canvas"); raw.width = width; raw.height = rows;
    const rawContext = raw.getContext("2d"), pixels = rawContext.createImageData(width, rows);
    for (let row = 0; row < rows; row++) for (let col = 0; col < width; col++) {
      const offset = axis === "z" ? index(state.z, row, col) : axis === "y" ? index(row, state.y, col) : index(row, col, state.x);
      const rgb = colorFor(offset), i = (row * width + col) * 4; pixels.data[i] = rgb[0]; pixels.data[i + 1] = rgb[1]; pixels.data[i + 2] = rgb[2]; pixels.data[i + 3] = 255;
    }
    rawContext.putImageData(pixels, 0, 0);
    const horizontal = data.edges[axis === "x" ? 1 : 0], vertical = data.edges[axis === "z" ? 1 : 2];
    const physicalWidth = horizontal[horizontal.length - 1] - horizontal[0], physicalHeight = vertical[vertical.length - 1] - vertical[0];
    const stage = canvas.parentElement;
    const scale = Math.min((stage.clientWidth - 16) / physicalWidth, (stage.clientHeight - 16) / physicalHeight);
    canvas.style.width = Math.max(1, physicalWidth * scale) + "px"; canvas.style.height = Math.max(1, physicalHeight * scale) + "px";
    canvas.width = width; canvas.height = axis === "z" ? rows : Math.min(4096, Math.max(rows, Math.ceil(physicalHeight / Math.min(...vertical.slice(1).map((v, i) => v - vertical[i])))));
    context.imageSmoothingEnabled = false;
    if (axis === "z") context.drawImage(raw, 0, 0);
    else for (let row = 0; row < rows; row++) {
      const top = Math.round((vertical[row] - vertical[0]) / physicalHeight * canvas.height), bottom = Math.round((vertical[row + 1] - vertical[0]) / physicalHeight * canvas.height);
      if (bottom > top) context.drawImage(raw, 0, row, width, 1, 0, top, width, bottom - top);
    }
    sliceGeometry[axis] = {horizontal, vertical};
  }
  function drawSlices() {
    if (!labels) return;
    for (const axis of ["z", "y", "x"]) drawSlice(axis);
    $("z-position").textContent = `Z ${fmt(data.z[state.z])} mm`;
    $("y-position").textContent = `Y ${fmt(data.origin_xy_mm[1] + state.y * data.spacing_xy_mm[1])} mm`;
    $("x-position").textContent = `X ${fmt(data.origin_xy_mm[0] + state.x * data.spacing_xy_mm[0])} mm`;
    $("z-anchor").textContent = `Plane ${state.z + 1} of ${nz}${anchors.has(state.z) ? " · aligned source anchor" : ""}`;
  }
  function nearestZ(position) {
    let lo = 0, hi = data.z.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (data.z[mid] < position) lo = mid + 1; else hi = mid; }
    if (!lo) return 0;
    const a = Math.abs(data.z[lo - 1] - position), b = Math.abs(data.z[lo] - position);
    return a <= b + Math.max(1, Math.abs(position)) * Number.EPSILON * 8 ? lo - 1 : lo;
  }
  function lookup(axis, event, pick) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const u = Math.max(0, Math.min(.999999, (event.clientX - bounds.left) / bounds.width)), v = Math.max(0, Math.min(.999999, (event.clientY - bounds.top) / bounds.height));
    const physicalZ = data.edges[2][0] + v * (data.edges[2][nz] - data.edges[2][0]);
    const x = axis === "x" ? state.x : Math.floor(u * nx), y = axis === "z" ? Math.floor(v * ny) : axis === "x" ? Math.floor(u * ny) : state.y, z = axis === "z" ? state.z : nearestZ(physicalZ);
    const off = index(z, y, x), id = labels[off], e = evidence[off], region = regions.get(id);
    const text = `${region?.name || "Label " + id} · ID ${id} · ${evidenceName(e)} (${e}) · X ${fmt(data.origin_xy_mm[0] + x * data.spacing_xy_mm[0])}, Y ${fmt(data.origin_xy_mm[1] + y * data.spacing_xy_mm[1])}, Z ${fmt(data.z[z])} mm · native [z,y,x] [${z},${y},${x}]`;
    $("lookup").lastElementChild.textContent = text; $("lookup").firstElementChild.style.background = region?.color || "#a8afb0";
    if (pick) select(id);
  }
  function renderReport() {
    const list = (target, input, empty) => {
      const el = $(target); el.replaceChildren();
      const values = input === undefined || input === null ? [] : Array.isArray(input) ? input : typeof input === "object" ? Object.entries(input).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`) : [String(input)];
      if (!values.length) { const p = document.createElement("p"); p.textContent = empty; el.append(p); return; }
      const ul = document.createElement("ul");
      for (const value of values.slice(0, 50)) { const li = document.createElement("li"); li.textContent = value && typeof value === "object" ? (value.message || value.description || JSON.stringify(value)) : String(value); ul.append(li); }
      if (values.length > 50) { const li = document.createElement("li"); li.textContent = `${values.length - 50} more entries are retained in the output metadata.`; ul.append(li); }
      el.append(ul);
    };
    const warnings = data.metadata.warnings || [];
    const notes = Array.isArray(warnings) ? [...warnings] : [warnings];
    if (data.preview.labels_without_preview_surface.length) notes.push(`${data.preview.labels_without_preview_surface.length} small identities have no surface at the preview sampling. They remain available in native slices.`);
    list("warnings", notes, "No warnings were recorded for this output.");
    const correctionData = data.metadata.corrections || data.metadata.correction_log;
    const corrections = Array.isArray(correctionData) ? correctionData : correctionData ? [correctionData] : [];
    const correctionBox = $("corrections"); correctionBox.replaceChildren();
    if (!corrections.length) { const p = document.createElement("p"); p.textContent = "No corrections were recorded."; correctionBox.append(p); }
    else {
      const retained = corrections.filter(r => r && typeof r === "object" && r.accepted === true);
      const summary = document.createElement("p"); summary.textContent = `${corrections.length} recorded checks${retained.length ? ` · ${retained.length} computed adjustments retained` : ""}. Anatomical acceptance remains a separate human review.`; correctionBox.append(summary);
      const ul = document.createElement("ul");
      for (const r of (retained.length ? retained : corrections).slice(0, 6)) {
        const li = document.createElement("li");
        if (r && typeof r === "object") {
          const location = Array.isArray(r.pair) ? `Sections ${r.pair.map(i => Number(i) + 1).join("–")}` : r.section !== undefined ? `Section ${Number(r.section) + 1}` : r.plane !== undefined ? `Plane ${Number(r.plane) + 1}` : "Recorded change";
          const score = Number.isFinite(r.objective_before) && Number.isFinite(r.objective_after) ? ` Score ${fmt(r.objective_before)} → ${fmt(r.objective_after)}.` : "";
          li.textContent = `${location}: ${r.message || r.description || r.reason || r.action || "see full record"}${score}`;
        } else li.textContent = String(r);
        ul.append(li);
      }
      correctionBox.append(ul); const details = document.createElement("details"), summaryNode = document.createElement("summary"), pre = document.createElement("pre"); summaryNode.textContent = "Complete correction record"; pre.textContent = JSON.stringify(corrections, null, 2); details.append(summaryNode, pre); correctionBox.append(details);
    }
    const metrics = data.metadata.metrics || data.metadata.validation;
    const metricLabels = {mean_dice_before: "Mean overlap before alignment", mean_dice_rigid_after: "Mean overlap after section alignment", mean_dice_after: "Mean overlap after refinement", flagged_pairs: "Flagged section pairs", input_sections: "Reference sections", output_voxels: "Output voxels", unknown_voxels: "Unresolved voxels", correction_count: "Retained adjustments", anchors_exact: "Exact source anchors"};
    const metricBox = $("metrics"); metricBox.replaceChildren();
    if (metrics && typeof metrics === "object" && !Array.isArray(metrics)) {
      for (const [key, value] of Object.entries(metrics).filter(([k, v]) => typeof v === "number" || typeof v === "boolean").slice(0, 10)) { const row = document.createElement("div"); row.className = "metric-row"; const label = document.createElement("span"), number = document.createElement("strong"); label.textContent = metricLabels[key] || key.replaceAll("_", " "); number.textContent = typeof value === "boolean" ? (value ? "Yes" : "No") : fmt(value); row.append(label, number); metricBox.append(row); }
      const note = document.createElement("p"); note.style.marginTop = "12px"; note.textContent = "Computed geometry checks do not establish independent anatomical accuracy."; metricBox.append(note);
      const details = document.createElement("details"), summaryNode = document.createElement("summary"), pre = document.createElement("pre"); summaryNode.textContent = "Definitions and all checks"; pre.textContent = JSON.stringify(metrics, null, 2); details.append(summaryNode, pre); metricBox.append(details);
    } else list("metrics", metrics, "No additional quantitative checks were recorded in this viewer metadata.");
    const review = data.metadata.human_review;
    $("review-state").textContent = review && review.output_anatomically_accepted === false ? "Anatomical review required" : String(data.metadata.status || data.metadata.review_status || "Recorded output");
    const sources = data.metadata.sources || data.metadata.attribution || [];
    const sourceItems = Array.isArray(sources) ? sources : [sources];
    if (sourceItems.length) {
      $("sources-block").hidden = false;
      for (const source of sourceItems) {
        const p = document.createElement("p");
        if (source && typeof source === "object") {
          p.textContent = source.citation || source.title || source.name || source.description || JSON.stringify(source);
          if (source.license) p.append(document.createTextNode(` · ${source.license}`));
          const url = source.url || source.source_url;
          if (typeof url === "string" && /^https?:\/\//i.test(url)) { const a = document.createElement("a"); a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = "Source"; p.append(document.createTextNode(" · "), a); }
        } else p.textContent = String(source);
        $("sources").append(p);
      }
    }
    $("details").textContent = JSON.stringify({shape_zyx: data.shape, spacing_xy_mm: data.spacing_xy_mm, origin_xy_mm: data.origin_xy_mm, z_range_mm: [data.z[0], data.z[nz - 1]], native_z_is_nonuniform: data.z.length > 2 && data.z.slice(2).some((v, i) => Math.abs((v - data.z[i + 1]) - (data.z[1] - data.z[0])) > 1e-10), axis_note: "Native source coordinates; no anatomical orientation inferred.", preview: data.preview}, null, 2);
  }
  function downloadPly() {
    const chosen = meshes.filter(m => visible(m.id)), vertexCount = chosen.reduce((s, m) => s + m.vertices.length / 3, 0), faceCount = chosen.reduce((s, m) => s + m.faces.length / 3, 0);
    const header = `ply\nformat binary_little_endian 1.0\ncomment AtlasCraft surface preview; physical XYZ millimetres; not a native measurement mesh\nelement vertex ${vertexCount}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nproperty ushort label_id\nelement face ${faceCount}\nproperty list uchar int vertex_indices\nend_header\n`;
    const bytes = new ArrayBuffer(vertexCount * 17 + faceCount * 13), view = new DataView(bytes); let cursor = 0, base = 0;
    for (const mesh of chosen) { const color = hex(regions.get(mesh.id).color); for (let i = 0; i < mesh.vertices.length; i += 3) { for (let a = 0; a < 3; a++) view.setFloat32(cursor + a * 4, mesh.vertices[i + a], true); for (let a = 0; a < 3; a++) view.setUint8(cursor + 12 + a, color[a]); view.setUint16(cursor + 15, mesh.id, true); cursor += 17; } }
    for (const mesh of chosen) { for (let i = 0; i < mesh.faces.length; i += 3) { view.setUint8(cursor, 3); for (let a = 0; a < 3; a++) view.setInt32(cursor + 1 + a * 4, mesh.faces[i + a] + base, true); cursor += 13; } base += mesh.vertices.length / 3; }
    const url = URL.createObjectURL(new Blob([header, bytes], {type: "application/octet-stream"})), link = document.createElement("a"); link.href = url; link.download = "AtlasCraft_surface_preview.ply"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  async function main() {
    $("region-count").textContent = data.regions.filter(r => r.id).length.toLocaleString(); $("dimensions").textContent = data.shape.join(" × "); $("spacing").textContent = data.spacing_xy_mm.map(fmt).join(" × "); $("anchors").textContent = anchors.size.toLocaleString();
    renderReport(); renderRegions();
    [labels, evidence] = await Promise.all([inflate(data.labels, Uint16Array), inflate(data.evidence, Uint8Array)]);
    if (labels.length !== nz * ny * nx || evidence.length !== labels.length) throw new Error("Embedded native arrays have an unexpected length.");
    meshes = [];
    for (const item of data.meshes) { const [vertices, normals, faces] = await Promise.all([inflate(item.vertices, Float32Array), inflate(item.normals, Float32Array), inflate(item.faces, Uint32Array)]); meshes.push({id: item.id, vertices, normals, faces}); }
    try { scene = new SurfaceScene($("surface"), meshes); } catch (error) { notice(error.message); }
    $("mesh-caption").textContent = `${data.preview.triangles.toLocaleString()} triangles · ${data.preview.preview_shape_zyx.join(" × ")} preview samples`;
    for (const axis of ["z", "y", "x"]) { const slider = $("slider-" + axis); slider.max = ({z: nz, y: ny, x: nx})[axis] - 1; slider.value = state[axis]; slider.oninput = () => { state[axis] = Number(slider.value); drawSlices(); }; const canvas = $("slice-" + axis); canvas.addEventListener("pointermove", event => lookup(axis, event, false)); canvas.addEventListener("click", event => lookup(axis, event, true)); }
    $("region-search").oninput = renderRegions;
    $("reset-camera").onclick = () => scene && scene.reset();
    $("download-ply").onclick = downloadPly;
    $("clear-selection").onclick = () => { $("isolate").checked = false; select(null); };
    for (const id of ["show-unknown", "isolate"]) $(id).onchange = () => { drawSlices(); if (scene) scene.draw(); };
    const codes = Array.from(new Set(evidence)).sort((a, b) => a - b);
    for (const code of codes) { const item = document.createElement("span"); item.className = "legend-item"; const swatch = document.createElement("i"); swatch.className = "swatch"; swatch.style.background = evidenceColor(code); const text = document.createElement("span"); text.textContent = `${code}: ${evidenceName(code)}`; item.append(swatch, text); $("evidence-legend").append(item); }
    $("evidence-toggle").onchange = () => { state.evidence = $("evidence-toggle").checked; $("evidence-legend").hidden = !state.evidence; drawSlices(); };
    new ResizeObserver(drawSlices).observe($("slice-z").parentElement);
    drawSlices(); $("status").textContent = "Ready · all data stay on this device";
    // A small read-only test hook exposes physical lookup without modifying arrays.
    window.AtlasCraftViewer = Object.freeze({nearestZ, shape: [...data.shape], nativeLabel: (z, y, x) => labels[index(z, y, x)], nativeEvidence: (z, y, x) => evidence[index(z, y, x)], surfaceCount: meshes.length});
  }
  main().catch(error => { notice(error.message || String(error)); $("status").textContent = "Unable to open this output"; });
})();
