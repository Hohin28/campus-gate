/* ============================================================
   Campus Gate — frontend logic
   Works standalone (no backend needed for login + navigation +
   logging) and automatically uses the real backend OCR / database
   when the FastAPI server is running.
   ============================================================ */

const API = '';

/* ---- local fallback credentials (used when backend is unreachable) ---- */
const LOCAL_GUARDS = { guard1: 'guard123', guard2: 'guard123' };

/* ---- embedded student dataset (mirrors backend seed_data.py) ---- */
// Student lookup, keyed by normalised roll number (e.g. CBSCU4CIV24101).
// Data comes from dataset.js (generated from students.xlsx by seed_data.py).
function buildStudents() {
  const map = {};
  const rows = window.STUDENT_DATASET || [];
  rows.forEach(s => {
    const key = s.key || normRoll(s.roll_number);
    map[key] = {
      barcode_id: key,
      name: s.name,
      roll_number: s.roll_number,
      phone: s.phone,
      place: s.place,
      hostel: s.hostel,
    };
  });
  return map;
}
function normRoll(s) {
  return (s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}
const STUDENTS = buildStudents();

/* ---- state ---- */
let token = localStorage.getItem('cg_token');
let username = localStorage.getItem('cg_username');
let userRole = localStorage.getItem('cg_role') || 'guard';
let userHostel = localStorage.getItem('cg_hostel') || '';
let logFilter = '';
let wardenTab = 'PENDING';
let capturedPlate = null;
let capturedOccupants = null;
let capturedCompanion = null;   // "Parent" or the relative's name
let plateStream = null;
let scanStream = null;
let exitStream = null;
let codeReaderRunning = false;
let pollTimer = null;

/* ---- camera helpers (shared by plate / barcode / exit) ---- */
async function getCameraStream() {
  const md = navigator.mediaDevices;
  if (!md || !md.getUserMedia) throw new DOMException('getUserMedia unsupported', 'NotSupportedError');
  try {
    // Rear camera at full HD (soft constraints — phones default to 640x480
    // otherwise, which makes the plate too small to read reliably).
    return await md.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
  } catch (e) {
    // Don't re-prompt on permission / in-use errors (re-prompting can make the
    // browser auto-block). Only retry when the constraint itself was the issue.
    if (e && (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError'
              || e.name === 'SecurityError' || e.name === 'NotReadableError')) {
      throw e;
    }
    return await md.getUserMedia({ video: true, audio: false });
  }
}

function cameraHint(e) {
  const h = location.hostname;
  const secure = location.protocol === 'https:' || h === 'localhost' || h === '127.0.0.1';
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return '📷 This browser/page cannot open a camera here. Use manual entry.';
  }
  if (!secure) {
    return '📷 Camera is blocked because the page is not secure. Browsers only allow the camera on https:// or localhost. You are on ' + location.origin + '. Use manual entry, or open the app over https / localhost.';
  }
  const n = e && e.name;
  if (n === 'NotAllowedError' || n === 'PermissionDeniedError') {
    return '📷 Camera permission was denied. Click the camera icon in the address bar → Allow, then try again. (Manual entry still works.)';
  }
  if (n === 'NotFoundError' || n === 'OverconstrainedError' || n === 'DevicesNotFoundError') {
    return '📷 No usable camera was found on this device. Use manual entry.';
  }
  if (n === 'NotReadableError' || n === 'TrackStartError') {
    return '📷 The camera is in use by another app. Close it and retry, or use manual entry.';
  }
  return '📷 Could not access the camera (' + (n || 'unknown error') + '). Use manual entry.';
}

/* Rich, step-by-step camera help with a Retry button. `retryCall` is a JS
   call string like "startPlateCam()". */
function cameraHelpHtml(e, retryCall) {
  const h = location.hostname;
  const secure = location.protocol === 'https:' || h === 'localhost' || h === '127.0.0.1';
  const n = e && e.name;
  let title, steps;

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    title = 'Camera not available on this page';
    steps = ['Open the app in <b>Chrome or Edge</b> at <b>http://localhost:8000</b> (not inside a preview panel).'];
  } else if (!secure) {
    title = 'Camera blocked — page is not secure';
    steps = [
      'On <b>this</b> computer, open <b>http://localhost:8000</b> (camera is only allowed on localhost / https).',
      'On a <b>second device</b> (the LAN address), use <b>Enter plate manually</b> below.'
    ];
  } else if (n === 'NotAllowedError' || n === 'PermissionDeniedError') {
    title = 'Camera permission is blocked';
    steps = [
      'Click the <b>camera / 🔒 icon</b> in the address bar → set Camera to <b>Allow</b> → reload.',
      'Windows: <b>Settings → Privacy &amp; security → Camera</b> → turn <b>On</b> “Camera access” and “Let apps / desktop apps access your camera”.',
      'Close any app using the webcam (Zoom, Teams, Camera), then tap <b>Try Again</b>.'
    ];
  } else if (n === 'NotFoundError' || n === 'DevicesNotFoundError' || n === 'OverconstrainedError') {
    title = 'No camera found on this device';
    steps = ['Connect a webcam, or use <b>Enter plate manually</b> below.'];
  } else if (n === 'NotReadableError' || n === 'TrackStartError') {
    title = 'Camera is busy';
    steps = ['Another app is using the camera. Close it (Zoom / Teams / Camera) and tap <b>Try Again</b>.'];
  } else {
    title = 'Could not open the camera (' + (n || 'error') + ')';
    steps = ['Use <b>Enter plate manually</b> below, or tap <b>Try Again</b>.'];
  }

  return '<div class="cam-help">'
    + '<div class="cam-help-title">📷 ' + title + '</div>'
    + '<ol>' + steps.map(function (s) { return '<li>' + s + '</li>'; }).join('') + '</ol>'
    + '<button class="btn-secondary" onclick="' + retryCall + '">🔄 Try Again</button>'
    + '</div>';
}

/* ---- ZXing barcode library (for ID card scanning) ---- */
const zxScript = document.createElement('script');
zxScript.src = 'https://unpkg.com/@zxing/library@0.18.6/umd/index.min.js';
document.head.appendChild(zxScript);

/* ============================================================
   Helpers
   ============================================================ */
function normalizePlate(s) {
  return (s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function fmtTime(t) {
  if (!t) return '—';
  // Backend sends naive UTC (no zone) -> append Z. Local logs already ISO/Z.
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t + 'Z';
  const d = new Date(iso);
  return isNaN(d) ? t : d.toLocaleString();
}

function showScreen(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
  const el = document.getElementById(id);
  if (el) el.classList.add('active');
  window.scrollTo(0, 0);
  stopAllCameras();
  stopPoll();
  // Keep stats fresh on the main screen so both guards see live counts.
  if (id === 'screen-main') startPoll(loadStats, 5000);
}

function stopAllCameras() {
  if (typeof stopAutoScan === 'function') stopAutoScan();
  stopPlateCam();
  stopScan();
  stopExitCam();
}

/* ---- live refresh (so entry & exit guards stay in sync) ---- */
function startPoll(fn, ms) {
  stopPoll();
  pollTimer = setInterval(fn, ms);
}
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function showMsg(id, msg, type) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<div class="alert alert-${type}">${msg}</div>`;
  if (type !== 'info') setTimeout(() => { if (el) el.innerHTML = ''; }, 4000);
}

function comingSoon(name) {
  alert(name + ' module is coming soon.\nStudent is fully ready to use.');
}

/* ---- localStorage-backed logs (standalone fallback) ---- */
function getLocalLogs() {
  try { return JSON.parse(localStorage.getItem('cg_logs') || '[]'); }
  catch (e) { return []; }
}
function saveLocalLogs(logs) {
  localStorage.setItem('cg_logs', JSON.stringify(logs));
}

function cleanId(raw) {
  // Strip dots/spaces so CB.SC.U4CIV24101 matches CBSCU4CIV24101.
  return (raw || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function isValidId(cid) {
  // Any roll number / campus ID, e.g. CBSCU4CIV24101 or CYS24122.
  return /^[A-Z0-9]{5,25}$/.test(cid) && /[A-Z]/.test(cid) && /[0-9]/.test(cid);
}

function findStudent(cid) {
  return STUDENTS[cid] || null;   // keyed by normalised roll
}

/* ---- plate format AA 00 AA 0000 (each group may be shorter) ---- */
function isValidPlate(plate) {
  return /^[A-Z]{1,2}\d{1,2}[A-Z]{1,2}\d{1,4}$/.test(normalizePlate(plate));
}
function formatPlate(plate) {
  const m = normalizePlate(plate).match(/^([A-Z]{1,2})(\d{1,2})([A-Z]{1,2})(\d{1,4})$/);
  return m ? m.slice(1).join(' ') : plate.toUpperCase();
}

function localScan(barcode, plate, occupants, companion) {
  const cid = cleanId(barcode);
  const student = findStudent(cid);

  let sname, sroll, sphone, splace, shostel;
  if (student) {
    sname = student.name; sroll = student.roll_number; sphone = student.phone;
    splace = student.place; shostel = student.hostel;
  } else {
    // Unseen roll: accept any valid ID; leave name blank, show ID as roll.
    if (!isValidId(cid)) return { error: 'Enter a valid roll number (e.g. CB.SC.U4CIV24101)' };
    sname = ''; sroll = cid; sphone = null; splace = null; shostel = null;
  }
  const soccupants = occupants || null;

  const norm = normalizePlate(plate);
  if (!norm) return { error: 'No vehicle number captured' };
  if (!isValidPlate(norm)) return { error: 'Vehicle number must look like AA 00 AA 0000 (e.g. TN 38 H 1234)' };

  const logs = getLocalLogs();
  const active = logs.find(l => l.vehicle_number_normalized === norm && l.status === 'INSIDE');
  if (active) {
    return { error: 'This vehicle is already inside — clear it at the Exit gate before re-entering.' };
  }
  const log = {
    id: 'L' + Date.now(),
    student_name: sname,
    roll_number: sroll,
    phone: sphone,
    place: splace,
    hostel: shostel,
    occupants: soccupants,
    companion: companion || null,
    person_type: 'student',
    vehicle_number: formatPlate(plate),
    vehicle_number_normalized: norm,
    entry_time: new Date().toISOString(),
    exit_time: null,
    status: 'INSIDE',
  };
  logs.unshift(log);
  saveLocalLogs(logs);
  return { action: 'ENTRY', ...log };
}

function localExit(plate) {
  const norm = normalizePlate(plate);
  if (!norm) return { error: 'No vehicle number entered' };
  if (!isValidPlate(norm)) return { error: 'Vehicle number must look like AA 00 AA 0000 (e.g. TN 38 H 1234)' };
  const logs = getLocalLogs();
  const active = logs.find(l => l.vehicle_number_normalized === norm && l.status === 'INSIDE');
  if (!active) return { error: 'This vehicle is not inside — no matching entry found.' };
  active.exit_time = new Date().toISOString();
  active.status = 'EXITED';
  saveLocalLogs(logs);
  return { action: 'EXIT', ...active };
}

function computeLocalStats() {
  const logs = getLocalLogs();
  const start = new Date(); start.setHours(0, 0, 0, 0);
  let total = 0, inside = 0, exited = 0;
  logs.forEach(l => {
    if (new Date(l.entry_time) >= start) total++;
    if (l.status === 'INSIDE') inside++;
    if (l.status === 'EXITED' && l.exit_time && new Date(l.exit_time) >= start) exited++;
  });
  return { total_today: total, inside_now: inside, exited_today: exited };
}

function filterLocalLogs(status, search) {
  let out = getLocalLogs();
  if (status) out = out.filter(l => l.status === status);
  if (search) {
    const s = search.toUpperCase();
    const sn = normalizePlate(search);
    out = out.filter(l =>
      (sn && l.vehicle_number_normalized.includes(sn)) ||
      l.student_name.toUpperCase().includes(s) ||
      l.roll_number.toUpperCase().includes(s));
  }
  out.sort((a, b) => new Date(b.entry_time) - new Date(a.entry_time));
  return out.slice(0, 50);
}

/* ============================================================
   Auth  (backend first, local fallback) — gates access
   ============================================================ */
async function doLogin() {
  const u = document.getElementById('login-user').value.trim();
  const p = document.getElementById('login-pass').value.trim();
  if (!u || !p) return showMsg('login-msg', 'Enter username and password', 'error');

  // 1) Try the real backend.
  try {
    const res = await fetch(`${API}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    });
    const data = await res.json();
    if (res.ok) return enterApp(data.token, data.username, data.role, data.hostel);
    // Backend reachable but rejected the credentials -> stay on login.
    return showMsg('login-msg', data.detail || 'Invalid credentials', 'error');
  } catch (e) {
    // 2) Backend unreachable -> validate against local guards.
    if (LOCAL_GUARDS[u] && LOCAL_GUARDS[u] === p) {
      return enterApp('local-session', u, 'guard', '');
    }
    return showMsg('login-msg', 'Invalid credentials', 'error');
  }
}

function enterApp(tok, user, role, hostel) {
  token = tok;
  username = user;
  userRole = role || 'guard';
  userHostel = hostel || '';
  localStorage.setItem('cg_token', token);
  localStorage.setItem('cg_username', username);
  localStorage.setItem('cg_role', userRole);
  localStorage.setItem('cg_hostel', userHostel);
  document.getElementById('login-msg').innerHTML = '';
  document.getElementById('login-pass').value = '';

  if (userRole === 'warden') return showWarden();

  document.getElementById('guard-name-display').textContent = `Guard: ${username}`;
  showScreen('screen-main');
  loadStats();
}

function doLogout() {
  localStorage.removeItem('cg_token');
  localStorage.removeItem('cg_username');
  localStorage.removeItem('cg_role');
  localStorage.removeItem('cg_hostel');
  token = null;
  userRole = 'guard';
  stopScan();
  stopPlateCam();
  stopPoll();
  showScreen('screen-login');
}

/* ============================================================
   Warden screen (per-hostel approvals)
   ============================================================ */
function showWarden() {
  document.getElementById('warden-hostel-display').textContent = (userHostel || '') + ' hostel · ' + username;
  showScreen('screen-warden');     // stops any existing poll
  switchWardenTab('PENDING');
  startPoll(loadWardenList, 3000); // live — new gate entries appear on their own
}

function switchWardenTab(status) {
  wardenTab = status;
  document.getElementById('wtab-pending').classList.toggle('active', status === 'PENDING');
  document.getElementById('wtab-approved').classList.toggle('active', status === 'APPROVED');
  document.getElementById('warden-hint').style.display = status === 'PENDING' ? 'block' : 'none';
  loadWardenList();
}

async function loadWardenList() {
  try {
    const res = await fetch(`${API}/api/warden/list?token=${encodeURIComponent(token)}&status=${wardenTab}`);
    if (!res.ok) return;
    const data = await res.json();
    renderWardenList(data.items);
    if (wardenTab === 'PENDING') document.getElementById('wpending-count').textContent = data.items.length;
  } catch (e) { /* keep last view on transient errors */ }
}

function renderWardenList(items) {
  const c = document.getElementById('warden-list');
  if (!items.length) {
    c.innerHTML = '<div class="card" style="text-align:center;color:#93a4bd">'
      + (wardenTab === 'PENDING' ? 'No students waiting for approval' : 'No approvals yet') + '</div>';
    return;
  }
  c.innerHTML = items.map(i => {
    const name = i.student_name || i.roll_number;
    const right = (i.warden_status === 'PENDING')
      ? `<button class="btn-success wc-approve" onclick="approveStudent('${i.id}', this)">✔ Approve</button>`
      : `<div class="wc-approved">✅ Approved<br><span>${fmtTime(i.warden_approved_at)}</span></div>`;
    return `<div class="warden-card">
      <div class="wc-main">
        <div class="wc-name">${name}</div>
        <div class="wc-sub">${i.roll_number}</div>
        <div class="wc-meta">🚗 ${i.vehicle_number} &nbsp;·&nbsp; 👤 ${i.companion || '—'} &nbsp;·&nbsp; 👥 ${i.occupants != null ? i.occupants : '—'} &nbsp;·&nbsp; ⏱ ${fmtTime(i.entry_time)}</div>
      </div>
      ${right}
    </div>`;
  }).join('');
}

async function approveStudent(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const res = await fetch(`${API}/api/warden/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ log_id: id, token: token })
    });
    const data = await res.json();
    if (!res.ok) { alert(data.detail || 'Approve failed'); loadWardenList(); return; }
    loadWardenList();   // approved row leaves Pending, shows under Approved
  } catch (e) {
    alert('Cannot reach server');
    loadWardenList();
  }
}

async function loadStats() {
  let data;
  try {
    const res = await fetch(`${API}/api/stats`);
    if (!res.ok) throw new Error();
    data = await res.json();
  } catch (e) {
    data = computeLocalStats();
  }
  document.getElementById('stat-today').textContent = data.total_today;
  document.getElementById('stat-inside').textContent = data.inside_now;
  document.getElementById('stat-exited').textContent = data.exited_today;
}

/* ============================================================
   Student flow
   ============================================================ */
function startStudentFlow() {
  capturedPlate = null;
  capturedOccupants = null;
  capturedCompanion = null;
  document.getElementById('relative-box').style.display = 'none';
  document.getElementById('relative-name').value = '';
  document.getElementById('companion-msg').innerHTML = '';
  showScreen('screen-companion');
}

/* ---- companion: Parent or Relative/Other ---- */
function chooseCompanion(c) {
  capturedCompanion = c;
  updateStudentSteps();
  showScreen('screen-student');
}

function showRelativeInput() {
  const box = document.getElementById('relative-box');
  box.style.display = 'block';
  setTimeout(() => document.getElementById('relative-name').focus(), 50);
}

function chooseRelative() {
  const name = document.getElementById('relative-name').value.trim();
  if (name.length < 2) return showMsg('companion-msg', 'Enter the relative’s name', 'error');
  chooseCompanion(name);
}

function updateStudentSteps() {
  document.getElementById('companion-display').textContent = capturedCompanion || '—';
  const hasPlate = !!capturedPlate;
  document.getElementById('vehicle-status').textContent = hasPlate ? '✓ ' + capturedPlate : 'scan plate';
  document.getElementById('split-vehicle').classList.toggle('split-done', hasPlate);
  document.getElementById('step-vehicle').classList.toggle('step-done', hasPlate);
  document.getElementById('split-id').classList.toggle('split-locked', !hasPlate);
  document.getElementById('id-status').textContent = hasPlate ? 'scan ID' : 'locked';
  document.getElementById('step-id').classList.toggle('step-active', hasPlate);
}

function openVehicle() {
  document.getElementById('plate-result').style.display = 'none';
  document.getElementById('plate-start-btn').style.display = 'block';
  document.getElementById('plate-capture-btn').style.display = 'none';
  document.getElementById('plate-msg').innerHTML = '';
  document.getElementById('plate-occupants').value = '1';
  showScreen('screen-vehicle');
}

function openIdCard() {
  if (!capturedPlate) return alert('Please capture the vehicle number plate first.');
  document.getElementById('captured-plate-display').textContent = capturedPlate;
  document.getElementById('captured-companion-display').textContent = capturedCompanion || '—';
  switchIdTab('manual');
  showScreen('screen-id');
  setTimeout(() => { const el = document.getElementById('manual-barcode'); if (el) el.focus(); }, 50);
}

/* ---- plate camera + recognition ---- */
async function startPlateCam() {
  stopPlateCam();
  const video = document.getElementById('plate-video');
  try {
    plateStream = await getCameraStream();
    video.srcObject = plateStream;
    await video.play();
    document.getElementById('plate-start-btn').style.display = 'none';
    document.getElementById('plate-capture-btn').style.display = 'block';
    showMsg('plate-msg', '📡 Auto-detecting — hold the plate inside the box…', 'info');
    startAutoScan('plate');
  } catch (e) {
    document.getElementById('plate-msg').innerHTML = cameraHelpHtml(e, 'startPlateCam()');
  }
}

function stopPlateCam() {
  if (plateStream) {
    plateStream.getTracks().forEach(t => t.stop());
    plateStream = null;
  }
}

function showPlateResult(value) {
  stopAutoScan();
  stopPlateCam();
  document.getElementById('plate-result').style.display = 'block';
  document.getElementById('plate-number-input').value = value || '';
  document.getElementById('plate-start-btn').style.display = 'none';
  document.getElementById('plate-capture-btn').style.display = 'none';
  document.getElementById('plate-number-input').focus();
}

function enterPlateManually() {
  showPlateResult('');
}

// Crop the camera frame to the plate-guide region (with a small margin).
// A tight crop is far faster to OCR and removes background text/noise.
function capturePlateRegion(video, canvas) {
  const W = video.videoWidth, H = video.videoHeight;
  const sx = W * 0.05, sw = W * 0.90;   // guide is 10%..90% horizontally
  const sy = H * 0.26, sh = H * 0.48;   // guide is 34%..66% vertically
  canvas.width = sw;
  canvas.height = sh;
  canvas.getContext('2d').drawImage(video, sx, sy, sw, sh, 0, 0, sw, sh);
  return canvas.toDataURL('image/jpeg', 0.85);
}

// Burst: 3 frames ~160ms apart. One blurry / mid-focus frame (common on
// phones) no longer ruins the read — the server votes across frames.
async function captureBurst(video, canvas) {
  const frames = [];
  for (let i = 0; i < 3; i++) {
    frames.push(capturePlateRegion(video, canvas));
    if (i < 2) await new Promise(r => setTimeout(r, 160));
  }
  return frames;
}

/* ---- live auto-detect (ANPR): no capture tap needed ----
   While the camera is on, a frame is sent every ~0.5s (fast mode, one request
   in flight at a time). When the SAME valid plate is read twice — or once
   with high confidence — it locks, fills the field, and the guard just
   confirms/edits. */
const SCAN_CFG = {
  plate: {
    video: 'plate-video', canvas: 'plate-canvas', msg: 'plate-msg',
    onLock(val) {
      showPlateResult(val);   // stops the camera, shows editable field + Save
      showMsg('plate-msg', '✅ Plate detected automatically — check it and Save.', 'info');
    }
  },
  exit: {
    video: 'exit-video', canvas: 'exit-canvas', msg: 'exit-scan-msg',
    onLock(val) {
      stopExitCam();
      document.getElementById('exit-plate-input').value = val;
      switchExitTab('manual');
      showMsg('exit-msg', '✅ Plate detected automatically — check it and Record Exit.', 'info');
    }
  }
};

let autoScan = { running: false, kind: null, tally: {}, busy: false, timer: null };

function startAutoScan(kind) {
  stopAutoScan();
  autoScan = { running: true, kind, tally: {}, busy: false, timer: null };
  tickAutoScan();
}

function stopAutoScan() {
  autoScan.running = false;
  if (autoScan.timer) { clearTimeout(autoScan.timer); autoScan.timer = null; }
}

async function tickAutoScan() {
  if (!autoScan.running) return;
  const cfg = SCAN_CFG[autoScan.kind];
  const video = document.getElementById(cfg.video);
  const canvas = document.getElementById(cfg.canvas);

  if (video && video.videoWidth && !autoScan.busy) {
    autoScan.busy = true;
    try {
      const frame = capturePlateRegion(video, canvas);
      const res = await fetch(`${API}/api/recognize-plate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images: [frame], fast: true })
      });
      if (res.ok && autoScan.running) {
        const data = await res.json();
        if (data.plate && isValidPlate(data.plate)) {
          const p = normalizePlate(data.plate);
          autoScan.tally[p] = (autoScan.tally[p] || 0) + 1;
          const top = data.candidates && data.candidates[0];
          const conf = top ? top.confidence : 0;
          if (autoScan.tally[p] >= 2 || conf >= 0.6) {
            stopAutoScan();
            cfg.onLock(formatPlate(p));
            return;
          }
          showMsg(cfg.msg, '🔎 Reading ' + formatPlate(p) + ' — hold steady…', 'info');
        }
      }
    } catch (e) { /* transient error — keep scanning */ }
    autoScan.busy = false;
  }
  if (autoScan.running) autoScan.timer = setTimeout(tickAutoScan, 450);
}

async function capturePlate() {
  const video = document.getElementById('plate-video');
  const canvas = document.getElementById('plate-canvas');
  if (!video.videoWidth) return showMsg('plate-msg', 'Camera not ready yet', 'error');

  stopAutoScan();   // manual capture takes over from auto-detect
  showMsg('plate-msg', '🔍 Hold steady — reading plate…', 'info');
  const frames = await captureBurst(video, canvas);
  try {
    const res = await fetch(`${API}/api/recognize-plate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images: frames })
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    document.getElementById('plate-msg').innerHTML = '';
    const reading = data.plate ? (isValidPlate(data.plate) ? formatPlate(data.plate) : data.plate) : '';
    showPlateResult(reading);
    if (!data.detected || !isValidPlate(data.plate || '')) {
      showMsg('plate-msg', 'Check the reading — it must look like AA 00 AA 0000 (e.g. TN 38 H 1234).', 'error');
    }
  } catch (e) {
    // No OCR backend — let the guard type it from the still frame.
    document.getElementById('plate-msg').innerHTML = '';
    showPlateResult('');
    showMsg('plate-msg', 'Auto-read needs the server. Type the plate from the photo.', 'info');
  }
}

function retakePlate() {
  document.getElementById('plate-result').style.display = 'none';
  document.getElementById('plate-msg').innerHTML = '';
  startPlateCam();
}

function savePlate() {
  const val = document.getElementById('plate-number-input').value.trim();
  if (!val) return showMsg('plate-msg', 'Enter or capture a vehicle number first.', 'error');
  if (!isValidPlate(val)) {
    return showMsg('plate-msg', 'Vehicle number must look like AA 00 AA 0000 (e.g. TN 38 H 1234).', 'error');
  }
  const occ = parseInt(document.getElementById('plate-occupants').value, 10);
  if (!occ || occ < 1) {
    return showMsg('plate-msg', 'Enter how many people are in the vehicle (at least 1).', 'error');
  }
  capturedPlate = formatPlate(val);
  capturedOccupants = occ;
  stopPlateCam();
  updateStudentSteps();
  openIdCard();   // auto-direct to ID card
}

/* ---- ID barcode scan ---- */
function switchIdTab(tab) {
  ['manual', 'live', 'scan'].forEach(t => {
    document.getElementById('tab-content-' + t).style.display = tab === t ? 'block' : 'none';
    document.getElementById('tab-' + t).classList.toggle('active', tab === t);
  });
  if (tab !== 'scan') stopScan();
  if (tab === 'live') {
    loadArrivals();
    startPoll(loadArrivals, 3000);   // face scans pop in live
  } else {
    stopPoll();
  }
}

/* ---- Live Entry: students who just face-scanned at the gate ---- */
async function loadArrivals() {
  try {
    const res = await fetch(`${API}/api/arrivals?minutes=10`);
    if (!res.ok) throw new Error();
    renderArrivals((await res.json()).items);
  } catch (e) {
    renderArrivals(null);   // backend unreachable
  }
}

function timeAgo(t) {
  const s = Math.max(0, (Date.now() - new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t + 'Z')) / 1000);
  if (s < 60) return Math.round(s) + 's ago';
  return Math.round(s / 60) + ' min ago';
}

function renderArrivals(items) {
  const c = document.getElementById('arrivals-list');
  if (items === null) {
    c.innerHTML = '<div class="hint">Live Entry needs the server — use the Roll No tab.</div>';
    return;
  }
  if (!items.length) {
    c.innerHTML = '<div class="hint" style="margin-top:6px">No face scans in the last 10 minutes. Ask the student to face-scan, or use the Roll No tab.</div>';
    return;
  }
  c.innerHTML = items.map(a => `
    <button class="warden-card" style="width:100%;cursor:pointer" onclick="pickArrival('${a.barcode_id}')">
      <div class="wc-main" style="text-align:left">
        <div class="wc-name">${a.name}</div>
        <div class="wc-sub">${a.roll_number}</div>
        <div class="wc-meta">🏠 ${a.hostel || '—'} &nbsp;·&nbsp; ⏱ ${timeAgo(a.scanned_at)}</div>
      </div>
      <div class="wc-approved">Select ➜</div>
    </button>`).join('');
}

function pickArrival(barcodeId) {
  stopPoll();
  submitScan(barcodeId);
}

async function startScan() {
  stopScan();
  const video = document.getElementById('id-video');
  try {
    scanStream = await getCameraStream();
    video.srcObject = scanStream;
    await video.play();
    const ZXing = window.ZXing;
    if (!ZXing) { showMsg('id-msg', 'Scanner still loading — use the Enter ID tab.', 'error'); return; }
    const codeReader = new ZXing.BrowserMultiFormatReader();
    codeReaderRunning = true;
    codeReader.decodeFromVideoElement(video, (result) => {
      if (result && codeReaderRunning) {
        codeReaderRunning = false;
        stopScan();
        submitScan(result.getText());
      }
    });
  } catch (e) {
    document.getElementById('id-msg').innerHTML = cameraHelpHtml(e, 'startScan()');
  }
}

function stopScan() {
  codeReaderRunning = false;
  if (scanStream) {
    scanStream.getTracks().forEach(t => t.stop());
    scanStream = null;
  }
}

// Live preview of the name as the guard types a roll number.
function previewRoll() {
  const el = document.getElementById('roll-preview');
  const raw = document.getElementById('manual-barcode').value.trim();
  if (!raw) { el.innerHTML = ''; return; }
  const s = findStudent(cleanId(raw));
  if (s) {
    el.innerHTML = '<span class="rp-ok">✓ ' + s.name + '</span>'
      + '<span class="rp-meta">' + [s.place, s.hostel].filter(Boolean).join(' · ') + '</span>';
  } else {
    el.innerHTML = '<span class="rp-no">Not in dataset — will be logged by ID</span>';
  }
}

async function submitScan(barcode) {
  if (!barcode) return;
  barcode = barcode.trim().toUpperCase();
  if (!capturedPlate) return alert('Vehicle number missing. Go back and capture the plate.');

  // Try backend first; fall back to fully-local toggle.
  let data;
  try {
    const res = await fetch(`${API}/api/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ barcode_id: barcode, vehicle_number: capturedPlate, occupants: capturedOccupants, companion: capturedCompanion, guard_token: token })
    });
    data = await res.json();
    if (!res.ok) {
      const m = data.detail || 'Scan failed';
      showMsg('id-msg', m, 'error');
      showMsg('id-msg-manual', m, 'error');
      return;
    }
  } catch (e) {
    data = localScan(barcode, capturedPlate, capturedOccupants, capturedCompanion);
    if (data.error) {
      showMsg('id-msg', data.error, 'error');
      showMsg('id-msg-manual', data.error, 'error');
      return;
    }
  }
  showResult(data);
}

function showResult(data) {
  const isEntry = data.action === 'ENTRY';
  document.getElementById('result-icon').textContent = isEntry ? '✅' : '👋';
  document.getElementById('result-card').className = 'result-card ' + (isEntry ? 'res-entry' : 'res-exit');
  document.getElementById('result-action').textContent = isEntry ? 'ENTRY RECORDED' : 'EXIT RECORDED';
  // For an unseen student the name is blank — show the roll/ID as the heading.
  const heading = data.student_name || data.roll_number || '—';
  document.getElementById('result-name').textContent = heading;

  // Show a detail row only when it has a value.
  function row(id, valId, value) {
    const el = document.getElementById(id);
    if (value === null || value === undefined || value === '') { el.style.display = 'none'; }
    else { el.style.display = 'flex'; document.getElementById(valId).textContent = value; }
  }
  row('row-roll', 'result-roll', (data.roll_number && data.roll_number !== heading) ? data.roll_number : '');
  row('row-phone', 'result-phone', data.phone || '');
  row('row-place', 'result-place', data.place || '');
  row('row-hostel', 'result-hostel', data.hostel || '');
  row('row-occupants', 'result-occupants', (data.occupants !== null && data.occupants !== undefined) ? data.occupants : '');
  row('row-companion', 'result-companion', data.companion || '');

  document.getElementById('result-vehicle').textContent = data.vehicle_number;
  document.getElementById('result-time').textContent = fmtTime(isEntry ? data.entry_time : data.exit_time);

  // reset entry inputs for the next vehicle
  capturedPlate = null;
  capturedOccupants = null;
  capturedCompanion = null;
  const mb = document.getElementById('manual-barcode'); if (mb) mb.value = '';
  const rp = document.getElementById('roll-preview'); if (rp) rp.innerHTML = '';
  showScreen('screen-result');
}

/* ============================================================
   Exit gate flow  (second guard — plate only, no ID)
   ============================================================ */
function openExit() {
  document.getElementById('exit-plate-input').value = '';
  document.getElementById('exit-msg').innerHTML = '';
  document.getElementById('exit-scan-msg').innerHTML = '';
  document.getElementById('exit-start-btn').style.display = 'block';
  document.getElementById('exit-capture-btn').style.display = 'none';
  switchExitTab('manual');
  showScreen('screen-exit');
  setTimeout(() => { const el = document.getElementById('exit-plate-input'); if (el) el.focus(); }, 50);
}

function switchExitTab(tab) {
  document.getElementById('exit-manual').style.display = tab === 'manual' ? 'block' : 'none';
  document.getElementById('exit-scan').style.display = tab === 'scan' ? 'block' : 'none';
  document.getElementById('extab-manual').classList.toggle('active', tab === 'manual');
  document.getElementById('extab-scan').classList.toggle('active', tab === 'scan');
  if (tab !== 'scan') stopExitCam();
}

async function startExitCam() {
  stopExitCam();
  const video = document.getElementById('exit-video');
  try {
    exitStream = await getCameraStream();
    video.srcObject = exitStream;
    await video.play();
    document.getElementById('exit-start-btn').style.display = 'none';
    document.getElementById('exit-capture-btn').style.display = 'block';
    showMsg('exit-scan-msg', '📡 Auto-detecting — hold the plate inside the box…', 'info');
    startAutoScan('exit');
  } catch (e) {
    document.getElementById('exit-scan-msg').innerHTML = cameraHelpHtml(e, 'startExitCam()');
  }
}

function stopExitCam() {
  if (exitStream) {
    exitStream.getTracks().forEach(t => t.stop());
    exitStream = null;
  }
}

async function captureExitPlate() {
  const video = document.getElementById('exit-video');
  const canvas = document.getElementById('exit-canvas');
  if (!video.videoWidth) return showMsg('exit-scan-msg', 'Camera not ready yet', 'error');

  stopAutoScan();   // manual capture takes over from auto-detect
  showMsg('exit-scan-msg', '🔍 Hold steady — reading plate…', 'info');
  const frames = await captureBurst(video, canvas);
  try {
    const res = await fetch(`${API}/api/recognize-plate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ images: frames })
    });
    if (!res.ok) throw new Error();
    const data = await res.json();
    stopExitCam();
    document.getElementById('exit-plate-input').value = data.plate || '';
    switchExitTab('manual');
    showMsg('exit-msg', data.detected ? 'Review the plate and tap Record Exit.' : 'Could not read clearly — type / correct the plate.', data.detected ? 'info' : 'error');
  } catch (e) {
    stopExitCam();
    switchExitTab('manual');
    showMsg('exit-msg', 'Auto-read needs the server. Type the plate from the photo.', 'info');
  }
}

async function recordExit(plate) {
  plate = (plate || '').trim().toUpperCase();
  if (!plate) return showMsg('exit-msg', 'Enter the vehicle number', 'error');

  let data;
  try {
    const res = await fetch(`${API}/api/exit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vehicle_number: plate, guard_token: token })
    });
    data = await res.json();
    if (!res.ok) return showMsg('exit-msg', data.detail || 'Exit failed', 'error');
  } catch (e) {
    data = localExit(plate);
    if (data.error) return showMsg('exit-msg', data.error, 'error');
  }
  showResult(data);   // reuse the result card with action = EXIT
}

/* ============================================================
   Logs
   ============================================================ */
function openLogs() {
  showScreen('screen-logs');
  loadLogs();
  // Poll so an entry/exit made by the other guard appears within a few seconds.
  startPoll(() => { loadLogs(); loadStats(); }, 3000);
}

function setFilter(f, el) {
  logFilter = f;
  document.querySelectorAll('#screen-logs .nav-tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  loadLogs();
}

async function loadLogs() {
  const search = document.getElementById('log-search').value.trim();
  let logs;
  try {
    let url = `${API}/api/logs?limit=50`;
    if (logFilter) url += `&status=${logFilter}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error();
    logs = await res.json();
  } catch (e) {
    logs = filterLocalLogs(logFilter, search);
  }
  renderLogs(logs);
}

function renderLogs(logs) {
  const container = document.getElementById('logs-list');
  if (!logs.length) {
    container.innerHTML = '<div class="card" style="text-align:center;color:#93a4bd">No records found</div>';
    return;
  }
  const rows = logs.map((l, i) => {
    const exited = l.status === 'EXITED';
    // ✔ = entered AND exited (complete). ✘ = entered but still inside (pending exit).
    const mark = exited
      ? '<span class="t-mark t-yes" title="Entered and exited">✔</span>'
      : '<span class="t-mark t-no" title="Still inside — not exited yet">✘</span>';
    const status = exited
      ? '<span class="st-exited">Exited</span>'
      : '<span class="st-inside">Inside</span>';
    const occ = (l.occupants !== null && l.occupants !== undefined) ? l.occupants : '—';
    return `<tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-name">${l.student_name || '—'}</td>
      <td>${l.roll_number || '—'}</td>
      <td>${l.phone || '—'}</td>
      <td>${l.place || '—'}</td>
      <td>${l.hostel || '—'}</td>
      <td>${l.companion || '—'}</td>
      <td class="td-center">${occ}</td>
      <td class="td-vehicle">${l.vehicle_number}</td>
      <td>${status}</td>
      <td>${fmtTime(l.entry_time)}</td>
      <td>${l.exit_time ? fmtTime(l.exit_time) : '<span class="muted-cell">—</span>'}</td>
      <td class="td-center">${mark}</td>
    </tr>`;
  }).join('');
  container.innerHTML = `<div class="table-wrap"><table class="log-table">
    <thead><tr>
      <th>#</th><th>Name</th><th>Roll No</th><th>Phone</th><th>Place</th><th>Hostel</th><th>Came with</th><th>With</th>
      <th>Vehicle</th><th>Status</th><th>Entry Time</th><th>Exit Time</th><th>✔ / ✘</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

/* ============================================================
   Boot
   ============================================================ */
window.onload = () => {
  // Enter key submits login
  ['login-user', 'login-pass'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });
  });
  // Enter key submits manual barcode
  const mb = document.getElementById('manual-barcode');
  if (mb) mb.addEventListener('keydown', e => { if (e.key === 'Enter') submitScan(mb.value); });

  if (token && userRole === 'warden') {
    showWarden();
  } else if (token) {
    document.getElementById('guard-name-display').textContent = `Guard: ${username}`;
    showScreen('screen-main');
    loadStats();
  } else {
    showScreen('screen-login');
  }
};
