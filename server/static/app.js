'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────

const video    = document.getElementById('webcam');
const canvas   = document.getElementById('capture');
const ctx      = canvas.getContext('2d');

const startScreen  = document.getElementById('start-screen');
const cardLive     = document.getElementById('card-live');
const cardUpload   = document.getElementById('card-upload');

const uploadView     = document.getElementById('upload-view');
const backBtn        = document.getElementById('back-btn');
const dropZone       = document.getElementById('drop-zone');
const fileInput      = document.getElementById('file-input');
const dropContent    = document.getElementById('drop-content');
const dropSelected   = document.getElementById('drop-selected');
const selectedName   = document.getElementById('selected-name');
const selectedSize   = document.getElementById('selected-size');
const previewSection = document.getElementById('preview-section');
const previewVideo   = document.getElementById('preview-video');
const frameBadge     = document.getElementById('frame-badge');
const frameBadgeNum  = document.getElementById('frame-badge-num');
const analyzeBtn     = document.getElementById('analyze-btn');
const livePanel      = document.getElementById('live-panel');
const liveProgressFill = document.getElementById('live-progress-fill');
const liveFrame      = document.getElementById('live-frame');
const liveTotal      = document.getElementById('live-total');
const liveScore      = document.getElementById('live-score');
const liveBlinks     = document.getElementById('live-blinks');
const liveEye        = document.getElementById('live-eye');
const liveLevel      = document.getElementById('live-level');
const errorBox       = document.getElementById('error-box');
const errorText      = document.getElementById('error-text');
const resultsSection = document.getElementById('results-section');
const resetBtn       = document.getElementById('reset-btn');

// ── State ─────────────────────────────────────────────────────────────────

let ws            = null;
let sending       = false;
let captureInterval = null;
let currentFile   = null;
let previewObjUrl = null;
let streamFrames  = [];
let streamFps     = 30;
let streamTotal   = 0;

// ── Mode selection ────────────────────────────────────────────────────────

cardLive.addEventListener('click', startLiveMode);
cardLive.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') startLiveMode(); });

cardUpload.addEventListener('click', startUploadMode);
cardUpload.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') startUploadMode(); });

backBtn.addEventListener('click', goToStartScreen);

function startLiveMode() {
    navigator.mediaDevices.getUserMedia({ video: true })
        .then(stream => {
            video.srcObject = stream;
            return video.play();
        })
        .then(() => {
            startScreen.classList.add('hidden');
            requestNotificationPermission();
            connectWebSocket();
        })
        .catch(err => alert('Camera access denied: ' + err.message));
}

function startUploadMode() {
    startScreen.classList.add('hidden');
    uploadView.classList.remove('hidden');
}

function goToStartScreen() {
    uploadView.classList.add('hidden');
    startScreen.classList.remove('hidden');
    resetUploadState();
}

// ── WebSocket (live mode) ─────────────────────────────────────────────────

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${protocol}://${location.host}/ws`);
    ws.binaryType = 'arraybuffer';

    ws.onopen = () => {
        setConnectionStatus(true);
        captureInterval = setInterval(captureAndSend, 100);
    };

    ws.onmessage = event => {
        const state = JSON.parse(event.data);
        updateHUD(state);
        handleAlerts(state);
    };

    ws.onclose = () => {
        setConnectionStatus(false);
        clearInterval(captureInterval);
        captureInterval = null;
        setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = () => ws.close();
}

function captureAndSend() {
    if (!ws || ws.readyState !== WebSocket.OPEN || sending) return;
    if (!video.videoWidth) return;

    sending = true;
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(blob => {
        if (!blob) { sending = false; return; }
        blob.arrayBuffer().then(buf => {
            if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
            sending = false;
        });
    }, 'image/jpeg', 0.7);
}

// ── Live HUD ──────────────────────────────────────────────────────────────

function updateHUD(state) {
    document.getElementById('score').textContent       = Math.round(state.score);
    document.getElementById('alert-level').textContent = state.alert_level;
    document.getElementById('blink-count').textContent = state.blink_count;
    document.getElementById('blink-pts').textContent   = state.blink_rate_pts;
    document.getElementById('heavy-pts').textContent   = state.heavy_eyes_pts;
    document.getElementById('staring-pts').textContent = state.staring_pts;
    document.getElementById('countdown').textContent   = Math.ceil(state.seconds_until_update) + 's';

    const eyeEl = document.getElementById('eye-state');
    if (!state.face_detected) {
        eyeEl.textContent = 'No face';
        eyeEl.className   = 'hud-value dim';
    } else {
        eyeEl.textContent = state.is_closed ? 'Closed' : 'Open';
        eyeEl.className   = state.is_closed ? 'hud-value closed' : 'hud-value open';
    }
}

// ── Live alerts ───────────────────────────────────────────────────────────

const ALERT_MESSAGES = {
    1: 'Mild fatigue detected. Take a short rest.',
    2: 'Moderate fatigue. Please take a break now.',
    3: 'SEVERE FATIGUE — Auto-resetting in:',
};

function handleAlerts(state) {
    const overlay = document.getElementById('alert-overlay');
    const msgEl   = document.getElementById('alert-message');
    const cdEl    = document.getElementById('alert-countdown');

    if (state.alert_level === 0) {
        overlay.classList.add('hidden');
        overlay.dataset.level = '0';
        return;
    }

    overlay.classList.remove('hidden');
    overlay.dataset.level = String(state.alert_level);
    msgEl.textContent = ALERT_MESSAGES[state.alert_level] || '';
    cdEl.textContent  = state.lock_countdown != null
        ? Math.ceil(state.lock_countdown) + 's'
        : '';

    if (state.new_alert) sendNotification(state.alert_level);
}

function sendNotification(level) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const titles = { 1: 'Mild Fatigue', 2: 'Moderate Fatigue', 3: 'Severe Fatigue' };
    new Notification(titles[level] || 'Fatigue Alert', { body: ALERT_MESSAGES[level] });
}

function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function setConnectionStatus(connected) {
    const dot = document.getElementById('connection-status');
    dot.className = 'status-dot ' + (connected ? 'connected' : 'disconnected');
}

// ── File selection ────────────────────────────────────────────────────────

dropZone.addEventListener('dragover', e => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) setFile(file);
});
dropZone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') fileInput.click();
});
fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
});

function setFile(file) {
    currentFile = file;

    // Update drop zone to "selected" state
    dropContent.classList.add('hidden');
    dropSelected.classList.remove('hidden');
    selectedName.textContent = file.name;
    selectedSize.textContent = formatBytes(file.size);
    dropZone.classList.add('has-file');

    // Show video preview
    if (previewObjUrl) URL.revokeObjectURL(previewObjUrl);
    previewObjUrl = URL.createObjectURL(file);
    previewVideo.src = previewObjUrl;
    previewSection.classList.remove('hidden');

    analyzeBtn.disabled = false;
    errorBox.classList.add('hidden');
    resultsSection.classList.add('hidden');
    livePanel.classList.add('hidden');
    frameBadge.classList.add('hidden');
}

function formatBytes(bytes) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Analyze (streaming) ───────────────────────────────────────────────────

analyzeBtn.addEventListener('click', async () => {
    if (!currentFile) return;

    analyzeBtn.disabled = true;
    errorBox.classList.add('hidden');
    resultsSection.classList.add('hidden');
    streamFrames = [];

    // Reset live panel
    liveProgressFill.style.width = '0%';
    liveFrame.textContent  = '0';
    liveTotal.textContent  = '—';
    liveScore.textContent  = '0';
    liveBlinks.textContent = '0';
    liveEye.textContent    = '—';
    liveLevel.textContent  = '0';
    livePanel.classList.remove('hidden');
    frameBadge.classList.remove('hidden');

    try {
        await streamAnalysis(currentFile);
    } catch (err) {
        livePanel.classList.add('hidden');
        frameBadge.classList.add('hidden');
        showError(err.message);
        analyzeBtn.disabled = false;
    }
});

async function streamAnalysis(file) {
    const form = new FormData();
    form.append('file', file);

    const resp = await fetch('/analyze-stream', { method: 'POST', body: form });
    if (!resp.ok) throw new Error(`Server error ${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer    = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep any incomplete trailing line
        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            try {
                handleStreamData(JSON.parse(trimmed));
            } catch (e) {
                console.warn('Stream parse error:', e, line);
            }
        }
    }

    // Flush any remainder
    if (buffer.trim()) {
        try { handleStreamData(JSON.parse(buffer.trim())); } catch (_) {}
    }
}

function handleStreamData(data) {
    if (data.type === 'meta') {
        streamTotal = data.total_frames;
        streamFps   = data.fps || 30;
        liveTotal.textContent = streamTotal.toLocaleString();
        return;
    }

    if (data.type === 'frame') {
        streamFrames.push(data);
        updateLivePanel(data);
        seekPreview(data.frame_index);
        return;
    }

    if (data.type === 'summary') {
        // Snap progress to 100%
        liveProgressFill.style.width = '100%';
        liveFrame.textContent = streamTotal.toLocaleString();

        // Short delay so user sees the 100% bar, then show results
        setTimeout(() => {
            livePanel.classList.add('hidden');
            frameBadge.classList.add('hidden');
            renderResults(data);
            analyzeBtn.disabled = false;
        }, 400);
        return;
    }

    if (data.type === 'error') {
        throw new Error(data.message);
    }
}

function updateLivePanel(frame) {
    if (streamTotal > 0) {
        liveProgressFill.style.width = ((frame.frame_index / streamTotal) * 100).toFixed(1) + '%';
    }
    liveFrame.textContent  = frame.frame_index.toLocaleString();
    liveScore.textContent  = Math.round(frame.score);
    liveBlinks.textContent = frame.blink_count;
    liveLevel.textContent  = frame.alert_level;
    frameBadgeNum.textContent = frame.frame_index.toLocaleString();

    if (!frame.face_detected) {
        liveEye.textContent = 'No face';
        liveEye.className   = 'live-val dim';
    } else {
        liveEye.textContent = frame.is_closed ? 'Closed' : 'Open';
        liveEye.className   = frame.is_closed ? 'live-val closed' : 'live-val open';
    }
}

function seekPreview(frameIndex) {
    if (previewVideo.readyState >= 1 && streamFps > 0) {
        previewVideo.currentTime = frameIndex / streamFps;
    }
}

// ── Results ───────────────────────────────────────────────────────────────

const LEVEL_LABELS = { 0: 'None', 1: 'Mild', 2: 'Moderate', 3: 'Severe' };

function renderResults(data) {
    const level = data.final_alert_level || 0;

    document.getElementById('res-score').textContent  = Math.round(data.final_score || 0);
    document.getElementById('res-blinks').textContent = data.total_blinks || 0;
    document.getElementById('res-frames').textContent = (data.frames_processed || 0).toLocaleString();
    document.getElementById('res-level').textContent  = LEVEL_LABELS[level] || level;

    const levelBox = document.getElementById('res-level-box');
    levelBox.className = level > 0 ? `stat-box level-${level}` : 'stat-box';

    if (streamFrames.length >= 2) {
        drawScoreChart(streamFrames);
    } else {
        document.getElementById('score-chart').innerHTML =
            '<text fill="#444" x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" font-size="12" font-family="monospace">Not enough frames to chart</text>';
    }

    renderAlertTimeline(streamFrames);
    resultsSection.classList.remove('hidden');
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderAlertTimeline(frames) {
    const timeline  = document.getElementById('alert-timeline');
    const eventList = document.getElementById('alert-event-list');
    eventList.innerHTML = '';

    const events = [];
    frames.forEach(f => {
        if (f.new_alert && f.alert_level > 0) {
            events.push({ level: f.alert_level, frameIndex: f.frame_index });
        }
    });

    if (events.length === 0) { timeline.classList.add('hidden'); return; }

    const names = { 1: 'MILD', 2: 'MODERATE', 3: 'SEVERE' };
    events.forEach(ev => {
        const el = document.createElement('div');
        el.className = 'alert-event';
        el.innerHTML = `
            <span class="alert-badge badge-${ev.level}">${names[ev.level] || 'LEVEL ' + ev.level}</span>
            <span class="alert-event-time">Frame ${ev.frameIndex.toLocaleString()}</span>
            <span class="alert-event-msg">${ALERT_MESSAGES[ev.level] || ''}</span>
        `;
        eventList.appendChild(el);
    });

    timeline.classList.remove('hidden');
}

function showError(msg) {
    errorText.textContent = 'Error: ' + msg;
    errorBox.classList.remove('hidden');
}

// ── Reset ─────────────────────────────────────────────────────────────────

resetBtn.addEventListener('click', resetUploadState);

function resetUploadState() {
    currentFile = null;
    fileInput.value = '';

    dropContent.classList.remove('hidden');
    dropSelected.classList.add('hidden');
    selectedName.textContent = '';
    selectedSize.textContent = '';
    dropZone.classList.remove('has-file', 'drag-over');

    previewSection.classList.add('hidden');
    if (previewObjUrl) { URL.revokeObjectURL(previewObjUrl); previewObjUrl = null; }
    previewVideo.src = '';
    frameBadge.classList.add('hidden');

    analyzeBtn.disabled = true;
    livePanel.classList.add('hidden');
    errorBox.classList.add('hidden');
    resultsSection.classList.add('hidden');
    liveProgressFill.style.width = '0%';
    streamFrames = [];
}

// ── SVG score chart ───────────────────────────────────────────────────────

function drawScoreChart(frames) {
    const svg = document.getElementById('score-chart');
    const W = 760, H = 180;
    const PAD = { top: 14, right: 16, bottom: 14, left: 38 };
    const cW = W - PAD.left - PAD.right;
    const cH = H - PAD.top - PAD.bottom;

    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);

    // Downsample to max 400 points
    const step = Math.max(1, Math.floor(frames.length / 400));
    const pts  = frames.filter((_, i) => i % step === 0);
    if (pts.length < 2) return;

    const maxScore = Math.max(110, ...pts.map(f => f.score));
    const x = i => PAD.left + (i / (pts.length - 1)) * cW;
    const y = v => PAD.top + cH - (v / maxScore) * cH;

    const parts = [];

    parts.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#0a0a0a"/>`);

    // Alert zone fills
    parts.push(`<rect x="${PAD.left}" y="${y(50)}"       width="${cW}" height="${y(0)  - y(50)}"       fill="rgba(255,152,0,0.04)"/>`);
    parts.push(`<rect x="${PAD.left}" y="${y(80)}"       width="${cW}" height="${y(50) - y(80)}"       fill="rgba(230,74,25,0.05)"/>`);
    parts.push(`<rect x="${PAD.left}" y="${y(maxScore)}" width="${cW}" height="${y(80) - y(maxScore)}" fill="rgba(183,28,28,0.05)"/>`);

    // Zero baseline
    parts.push(`<line x1="${PAD.left}" y1="${y(0)}" x2="${W - PAD.right}" y2="${y(0)}" stroke="rgba(255,255,255,0.06)" stroke-width="1"/>`);
    parts.push(`<text x="${PAD.left - 5}" y="${y(0) + 4}" fill="#333" font-size="9" text-anchor="end" font-family="monospace">0</text>`);

    // Threshold lines
    const thresholds = [
        { v: 50,  c: '#ff9800', l: '50'  },
        { v: 80,  c: '#e64a19', l: '80'  },
        { v: 100, c: '#ef5350', l: '100' },
    ];
    for (const t of thresholds) {
        if (t.v > maxScore) continue;
        const ty = y(t.v);
        parts.push(`<line x1="${PAD.left}" y1="${ty}" x2="${W - PAD.right}" y2="${ty}" stroke="${t.c}" stroke-width="1" stroke-dasharray="3 5" opacity="0.45"/>`);
        parts.push(`<text x="${PAD.left - 5}" y="${ty + 4}" fill="${t.c}" font-size="9" text-anchor="end" font-family="monospace" opacity="0.75">${t.l}</text>`);
    }

    // Score line
    const d = pts.map((f, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(f.score).toFixed(1)}`).join(' ');
    parts.push(`<path d="${d}" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>`);

    // End dot
    const last = pts[pts.length - 1];
    parts.push(`<circle cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last.score).toFixed(1)}" r="3" fill="#fff"/>`);

    svg.innerHTML = parts.join('');
}
