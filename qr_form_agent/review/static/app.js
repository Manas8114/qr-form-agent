// Frontend Control Center Application Logic

let currentJobs = [];
let selectedJobId = null;
let currentKillSwitchActive = false;
let selectedQrFile = null;

// -------------------------------------------------------------
// Initialization & Navigation Tabs
// -------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  setupNavigationTabs();
  setupKillSwitch();
  setupReviewControls();
  setupQrLaunchpad();
  setupProfileManager();
  setupAuditStream();

  // Initial data fetches
  refreshAll();
  setInterval(refreshAll, 6000);
});

function refreshAll() {
  loadStats();
  loadJobs();
}

function setupNavigationTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      const targetTabId = tab.getAttribute('data-tab');
      document.querySelectorAll('.view-section').forEach(sec => {
        sec.classList.remove('active');
      });
      const targetSec = document.getElementById(targetTabId);
      if (targetSec) targetSec.classList.add('active');

      // Trigger view-specific loads
      if (targetTabId === 'tab-profile') {
        loadProfileData();
      } else if (targetTabId === 'tab-audit') {
        loadAuditLogs();
      }
    });
  });
}

// -------------------------------------------------------------
// System Stats & Kill Switch
// -------------------------------------------------------------

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById('stat-total').innerText = data.total_jobs || 0;
    const counts = data.counts || {};
    document.getElementById('stat-awaiting').innerText = counts['AWAITING_APPROVAL'] || 0;
    document.getElementById('stat-needs-human').innerText = counts['NEEDS_HUMAN'] || 0;
    document.getElementById('stat-approved').innerText = counts['APPROVED'] || 0;
    document.getElementById('stat-submitted').innerText = counts['SUBMITTED'] || 0;

    currentKillSwitchActive = !!data.kill_switch_active;
    updateKillSwitchUI(currentKillSwitchActive);
  } catch (err) {
    console.debug('Failed to load stats:', err);
  }
}

function setupKillSwitch() {
  const btn = document.getElementById('kill-switch-toggle');
  btn.onclick = async () => {
    const nextState = !currentKillSwitchActive;
    const confirmMsg = nextState
      ? 'ACTIVATE GLOBAL KILL SWITCH? This will instantly freeze all background form automations.'
      : 'Deactivate global kill switch and resume normal operations?';
    if (!confirm(confirmMsg)) return;

    try {
      const formData = new FormData();
      formData.append('activate', nextState ? 'true' : 'false');
      formData.append('reason', 'Operator button toggle on Control Center');

      const res = await fetch('/api/kill-switch/toggle', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      currentKillSwitchActive = !!data.kill_switch_active;
      updateKillSwitchUI(currentKillSwitchActive);
      alert(currentKillSwitchActive ? '🛑 Global Kill Switch ACTIVATED.' : '✅ Kill Switch DEACTIVATED.');
    } catch (err) {
      alert('Error communicating with kill switch endpoint.');
    }
  };
}

function updateKillSwitchUI(isActive) {
  const btn = document.getElementById('kill-switch-toggle');
  if (isActive) {
    btn.classList.add('active');
    btn.innerHTML = '<span>🛑 KILL SWITCH: ACTIVE</span>';
  } else {
    btn.classList.remove('active');
    btn.innerHTML = '<span>🛑 Kill Switch: OFF</span>';
  }
}

// -------------------------------------------------------------
// View 1: Form Review Dashboard
// -------------------------------------------------------------

async function loadJobs() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return;
    const data = await res.json();
    currentJobs = data.jobs || [];
    renderJobsList();
    if (selectedJobId) {
      selectJob(selectedJobId);
    } else if (currentJobs.length > 0) {
      selectJob(currentJobs[0].id);
    }
  } catch (err) {
    console.debug('Failed to load jobs:', err);
  }
}

function renderJobsList() {
  const list = document.getElementById('jobs-list');
  list.innerHTML = '';
  if (currentJobs.length === 0) {
    list.innerHTML = '<li class="empty-jobs-notice">No jobs registered.</li>';
    return;
  }

  currentJobs.forEach(job => {
    const li = document.createElement('li');
    li.className = `job-item ${job.id === selectedJobId ? 'active' : ''}`;
    li.onclick = () => selectJob(job.id);

    li.innerHTML = `
      <div class="job-item-domain">${escapeHtml(job.domain)}</div>
      <div class="job-item-meta">
        <span>${new Date(job.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
        <span class="status-pill status-${job.status}">${job.status}</span>
      </div>
    `;
    list.appendChild(li);
  });
}

async function selectJob(jobId) {
  selectedJobId = jobId;
  renderJobsList();

  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (!res.ok) return;
    const data = await res.json();
    const job = data.job;

    document.getElementById('no-job-selected').style.display = 'none';
    const detailsEl = document.getElementById('job-details');
    detailsEl.style.display = 'flex';

    document.getElementById('job-domain').innerText = job.domain;
    const urlLink = document.getElementById('job-url');
    urlLink.innerText = job.url;
    urlLink.href = job.url;

    const pill = document.getElementById('job-status-pill');
    pill.className = `status-pill status-${job.status}`;
    pill.innerText = job.status;

    const hashEl = document.getElementById('job-hash');
    if (job.approved_snapshot_hash) {
      hashEl.innerText = job.approved_snapshot_hash.slice(0, 16) + '...';
      hashEl.title = job.approved_snapshot_hash;
    } else {
      hashEl.innerText = 'Pending approval';
    }

    // Render Fields
    const fields = (job.stage_data && job.stage_data.mapped_fields) || [];
    document.getElementById('field-count').innerText = `${fields.length} fields`;
    const tbody = document.getElementById('fields-tbody');
    tbody.innerHTML = '';

    fields.forEach(f => {
      const tr = document.createElement('tr');
      const confClass = f.confidence >= 0.9 ? 'conf-high' : (f.confidence >= 0.75 ? 'conf-med' : 'conf-low');
      const confPercent = Math.round((f.confidence || 0) * 100);

      tr.innerHTML = `
        <td>
          <div class="field-name-label">${escapeHtml(f.field_id)}</div>
          <div class="field-id-sub">${escapeHtml(f.reason || '')}</div>
        </td>
        <td>
          <input type="text" class="field-input" data-field-id="${escapeHtml(f.field_id)}" value="${escapeHtml(f.value || '')}" />
        </td>
        <td>
          <span class="field-profile-key">${escapeHtml(f.profile_key || 'unmapped')}</span>
        </td>
        <td>
          <span class="confidence-pill ${confClass}">${confPercent}%</span>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Screenshot
    const img = document.getElementById('form-screenshot');
    if (job.form_screenshot_path) {
      const filename = job.form_screenshot_path.split(/[\\\\/]/).pop();
      img.src = `/screenshots/${filename}`;
      img.style.display = 'block';
    } else {
      img.style.display = 'none';
    }

    // Button States
    const approveBtn = document.getElementById('approve-btn');
    const rejectBtn = document.getElementById('reject-btn');
    const submitBtn = document.getElementById('submit-btn');
    const takeoverBtn = document.getElementById('takeover-btn');
    const notice = document.getElementById('action-notice');

    const canApprove = (job.status === 'AWAITING_APPROVAL' || job.status === 'NEEDS_HUMAN');
    approveBtn.disabled = !canApprove;
    rejectBtn.disabled = !canApprove;
    approveBtn.classList.toggle('btn-disabled', !canApprove);
    rejectBtn.classList.toggle('btn-disabled', !canApprove);

    const isApproved = (job.status === 'APPROVED');
    submitBtn.style.display = isApproved ? 'inline-flex' : 'none';

    const isNeedsHuman = (job.status === 'NEEDS_HUMAN');
    takeoverBtn.style.display = isNeedsHuman ? 'inline-flex' : 'none';

    if (isApproved) {
      notice.innerText = '✅ Form has been cryptographically approved. Ready for verified submission.';
    } else if (isNeedsHuman) {
      notice.innerText = '⚠️ Needs Human Intervention (CAPTCHA, Login, or sensitive fields detected).';
    } else if (job.status === 'SUBMITTED') {
      notice.innerText = '🎉 Form was successfully verified and submitted.';
    } else {
      notice.innerText = '⚠️ Approving will lock the current field values and compute a cryptographic SHA-256 fingerprint.';
    }

  } catch (err) {
    console.error('Failed to load job details:', err);
  }
}

function setupReviewControls() {
  document.getElementById('approve-btn').onclick = async () => {
    if (!selectedJobId) return;
    const inputs = document.querySelectorAll('#fields-tbody input.field-input');
    const edited = {};
    inputs.forEach(input => {
      edited[input.getAttribute('data-field-id')] = input.value;
    });

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edited_fields: edited })
      });
      if (res.ok) {
        await loadJobs();
        loadStats();
        alert('Job approved and cryptographic snapshot locked!');
      } else {
        const err = await res.json();
        alert('Approval error: ' + (err.detail || 'Failed'));
      }
    } catch (err) {
      alert('Network error approving job');
    }
  };

  document.getElementById('reject-btn').onclick = async () => {
    if (!selectedJobId) return;
    const reason = prompt('Reason for rejection:', 'Rejected by human reviewer');
    if (reason === null) return;

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/reject?reason=${encodeURIComponent(reason)}`, {
        method: 'POST'
      });
      if (res.ok) {
        await loadJobs();
        loadStats();
      }
    } catch (err) {
      alert('Error rejecting job');
    }
  };

  document.getElementById('submit-btn').onclick = async () => {
    if (!selectedJobId) return;
    const confirmSubmit = confirm('Execute verified submission? Current live DOM field hash will be validated.');
    if (!confirmSubmit) return;

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: false })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        alert('Form successfully submitted! Receipt: ' + (data.receipt_text || 'OK'));
        await loadJobs();
        loadStats();
      } else {
        alert('Submission failed: ' + (data.detail || data.error_message || 'Verification failure'));
      }
    } catch (err) {
      alert('Error during submission request: ' + err);
    }
  };

  document.getElementById('takeover-btn').onclick = async () => {
    if (!selectedJobId) return;
    alert('Launching interactive headful browser on your display. Solve the CAPTCHA or Login, then close the window.');
    try {
      await fetch(`/api/jobs/${selectedJobId}/takeover`, { method: 'POST' });
      await loadJobs();
    } catch (err) {
      alert('Error triggering headful takeover.');
    }
  };

  document.getElementById('refresh-btn').onclick = () => {
    loadJobs();
    loadStats();
  };
}

// -------------------------------------------------------------
// View 2: QR Launchpad
// -------------------------------------------------------------

function setupQrLaunchpad() {
  const dropzone = document.getElementById('qr-dropzone');
  const fileInput = document.getElementById('qr-file-input');
  const previewBox = document.getElementById('scan-preview-box');
  const filenameEl = document.getElementById('scan-filename');
  const startBtn = document.getElementById('start-scan-btn');
  const logBox = document.getElementById('scan-results-log');

  dropzone.onclick = () => fileInput.click();

  dropzone.ondragover = (e) => {
    e.preventDefault();
    dropzone.classList.add('dragover');
  };

  dropzone.ondragleave = () => {
    dropzone.classList.remove('dragover');
  };

  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleQrFile(e.dataTransfer.files[0]);
    }
  };

  fileInput.onchange = () => {
    if (fileInput.files && fileInput.files[0]) {
      handleQrFile(fileInput.files[0]);
    }
  };

  function handleQrFile(file) {
    selectedQrFile = file;
    filenameEl.innerText = `Selected: ${file.name} (${Math.round(file.size / 1024)} KB)`;
    previewBox.style.display = 'flex';
  }

  startBtn.onclick = async () => {
    if (!selectedQrFile) return;
    startBtn.disabled = true;
    startBtn.innerText = '⏳ Processing QR Codes...';
    logBox.style.display = 'block';
    logBox.innerText = 'Scanning image with zxing-cpp & running URL safety checks...\n';

    const formData = new FormData();
    formData.append('file', selectedQrFile);
    formData.append('auto_confirm', document.getElementById('auto-confirm-cb').checked ? 'true' : 'false');

    try {
      const res = await fetch('/api/pipeline/scan-image', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok && data.success) {
        logBox.innerText += `✓ Detection completed! Created ${data.count} form job(s):\n`;
        (data.jobs_created || []).forEach(id => {
          logBox.innerText += `  • Job ID: ${id}\n`;
        });
        logBox.innerText += `\nSwitch to the "Form Review" tab to inspect and approve.`;
        refreshAll();
      } else {
        logBox.innerText += `❌ Pipeline failed: ${data.detail || 'Unknown error'}\n`;
      }
    } catch (err) {
      logBox.innerText += `❌ Request error: ${err}\n`;
    } finally {
      startBtn.disabled = false;
      startBtn.innerText = '▶ Process QR Codes & Pre-Fill';
    }
  };
}

// -------------------------------------------------------------
// View 3: Candidate Profile Manager
// -------------------------------------------------------------

async function loadProfileData() {
  try {
    const res = await fetch('/api/profile');
    if (!res.ok) return;
    const data = await res.json();
    if (data.exists && data.profile) {
      const p = data.profile;
      document.getElementById('prof-full-name').value = p.full_name || '';
      document.getElementById('prof-email').value = p.email || '';
      document.getElementById('prof-phone').value = p.phone || '';
      document.getElementById('prof-address').value = p.address || '';
      document.getElementById('prof-city').value = p.city || '';
      document.getElementById('prof-state').value = p.state || '';
      document.getElementById('prof-postal').value = p.postal_code || '';
      document.getElementById('prof-country').value = p.country || '';
      document.getElementById('prof-linkedin').value = p.linkedin_url || '';
      document.getElementById('prof-github').value = p.github_url || '';
      document.getElementById('prof-portfolio').value = p.portfolio_url || '';
      document.getElementById('prof-skills').value = (p.skills || []).join(', ');
      document.getElementById('prof-summary').value = p.summary || '';
    }
  } catch (err) {
    console.error('Failed to load profile data:', err);
  }
}

function setupProfileManager() {
  const uploadBtn = document.getElementById('upload-resume-btn');
  const fileInput = document.getElementById('resume-file-input');
  const saveBtn = document.getElementById('save-profile-btn');

  uploadBtn.onclick = () => fileInput.click();

  fileInput.onchange = async () => {
    if (!fileInput.files || !fileInput.files[0]) return;
    const file = fileInput.files[0];
    uploadBtn.innerText = '⏳ Parsing Resume PDF...';
    uploadBtn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/profile/upload-resume', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok && data.success) {
        alert('Resume parsed and verified profile populated!');
        loadProfileData();
      } else {
        alert('Error parsing resume: ' + (data.detail || 'Failed'));
      }
    } catch (err) {
      alert('Network error uploading resume: ' + err);
    } finally {
      uploadBtn.innerText = '📄 Upload New Resume (PDF)';
      uploadBtn.disabled = false;
    }
  };

  saveBtn.onclick = async () => {
    const skillsRaw = document.getElementById('prof-skills').value;
    const skillsList = skillsRaw.split(',').map(s => s.trim()).filter(Boolean);

    const payload = {
      full_name: document.getElementById('prof-full-name').value || null,
      email: document.getElementById('prof-email').value || null,
      phone: document.getElementById('prof-phone').value || null,
      address: document.getElementById('prof-address').value || null,
      city: document.getElementById('prof-city').value || null,
      state: document.getElementById('prof-state').value || null,
      postal_code: document.getElementById('prof-postal').value || null,
      country: document.getElementById('prof-country').value || null,
      linkedin_url: document.getElementById('prof-linkedin').value || null,
      github_url: document.getElementById('prof-github').value || null,
      portfolio_url: document.getElementById('prof-portfolio').value || null,
      skills: skillsList,
      summary: document.getElementById('prof-summary').value || null,
    };

    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        alert('Verified candidate profile successfully saved!');
      } else {
        const err = await res.json();
        alert('Save error: ' + (err.detail || 'Failed'));
      }
    } catch (err) {
      alert('Error saving profile: ' + err);
    }
  };
}

// -------------------------------------------------------------
// View 4: Audit Stream
// -------------------------------------------------------------

async function loadAuditLogs() {
  try {
    const res = await fetch('/api/audit-logs?limit=50');
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('audit-tbody');
    tbody.innerHTML = '';

    const logs = data.logs || [];
    if (logs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 2rem;">No audit events recorded yet.</td></tr>';
      return;
    }

    logs.forEach(l => {
      const tr = document.createElement('tr');
      const timeStr = new Date(l.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const payloadStr = JSON.stringify(l.payload || {});

      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-size: 0.8rem; color: var(--text-muted);">${escapeHtml(timeStr)}</td>
        <td style="font-family: var(--font-mono); font-size: 0.78rem;">${escapeHtml(l.job_id.slice(0, 8))}...</td>
        <td><span class="actor-badge actor-${escapeHtml(l.actor)}">${escapeHtml(l.actor)}</span></td>
        <td><span class="action-badge">${escapeHtml(l.action)}</span></td>
        <td><div class="payload-preview" title="${escapeHtml(payloadStr)}">${escapeHtml(payloadStr)}</div></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to load audit logs:', err);
  }
}

function setupAuditStream() {
  const btn = document.getElementById('refresh-audit-btn');
  if (btn) btn.onclick = loadAuditLogs;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
}
