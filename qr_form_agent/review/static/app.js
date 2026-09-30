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
  setupTrackerAndReminders();
  setupAnswersBank();

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
      } else if (targetTabId === 'tab-tracker') {
        loadTrackerData();
      } else if (targetTabId === 'tab-answers') {
        loadAnswersBank();
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
      alert('Error updating kill switch: ' + err);
    }
  };
}

function updateKillSwitchUI(isActive) {
  const btn = document.getElementById('kill-switch-toggle');
  if (isActive) {
    btn.classList.add('active');
    btn.innerHTML = '<span>🛑 Kill Switch: ACTIVE</span>';
  } else {
    btn.classList.remove('active');
    btn.innerHTML = '<span>🛑 Kill Switch: OFF</span>';
  }
}

// -------------------------------------------------------------
// Discovered Jobs & Form Review
// -------------------------------------------------------------

async function loadJobs() {
  try {
    const res = await fetch('/api/jobs');
    if (!res.ok) return;
    const data = await res.json();
    currentJobs = data.jobs || [];
    renderJobsList();

    if (selectedJobId) {
      const exists = currentJobs.some(j => j.id === selectedJobId);
      if (!exists && currentJobs.length > 0) {
        selectJob(currentJobs[0].id);
      }
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
    list.innerHTML = '<li class="empty-list-notice">No jobs discovered yet.</li>';
    return;
  }

  currentJobs.forEach(job => {
    const li = document.createElement('li');
    li.className = `job-item ${job.id === selectedJobId ? 'active' : ''}`;
    li.onclick = () => selectJob(job.id);

    const titleText = (job.company || job.domain) + (job.role ? ` (${job.role})` : '');

    li.innerHTML = `
      <div class="job-item-domain">${escapeHtml(titleText)}</div>
      <div class="job-item-meta">
        <span>${escapeHtml((job.platform || 'generic').toUpperCase())}</span>
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
    document.getElementById('job-platform-badge').innerText = (job.platform || 'generic').toUpperCase();

    const compRole = (job.company || '') + (job.role ? ' — ' + job.role : '');
    document.getElementById('job-company-role').innerText = compRole || 'Job Posting';

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

    // Render Fields: Sort low-confidence fields first!
    const fields = (job.stage_data && job.stage_data.mapped_fields) || [];
    document.getElementById('field-count').innerText = `${fields.length} fields`;
    const tbody = document.getElementById('fields-tbody');
    tbody.innerHTML = '';

    const sortedFields = [...fields].sort((a, b) => {
      const aFlag = a.flagged_for_review ? 1 : 0;
      const bFlag = b.flagged_for_review ? 1 : 0;
      if (bFlag !== aFlag) return bFlag - aFlag;
      return (a.confidence || 0) - (b.confidence || 0);
    });

    sortedFields.forEach(f => {
      const tr = document.createElement('tr');
      if (f.flagged_for_review) tr.classList.add('flagged-row');

      const confPercent = Math.round((f.confidence || 0) * 100);
      const confClass = confPercent >= 85 ? 'conf-high' : (confPercent >= 70 ? 'conf-med' : 'conf-low');

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
    const handoffBtn = document.getElementById('handoff-btn');
    const notice = document.getElementById('action-notice');

    const canApprove = (job.status === 'AWAITING_APPROVAL' || job.status === 'NEEDS_HUMAN');
    approveBtn.disabled = !canApprove;
    rejectBtn.disabled = !canApprove;
    approveBtn.classList.toggle('btn-disabled', !canApprove);
    rejectBtn.classList.toggle('btn-disabled', !canApprove);

    const isApproved = (job.status === 'APPROVED');
    submitBtn.style.display = isApproved ? 'inline-flex' : 'none';

    const isNeedsHuman = (job.status === 'NEEDS_HUMAN');
    handoffBtn.style.display = isNeedsHuman ? 'inline-flex' : 'none';

    if (isApproved) {
      notice.innerText = '✅ Form has been cryptographically approved. Ready for verified submission.';
    } else if (isNeedsHuman) {
      notice.innerText = '⚠️ Needs Human Intervention (Login wall, CAPTCHA, or sensitive fields detected). Click Continue Here.';
    } else if (job.status === 'SUBMITTED') {
      notice.innerText = '🎉 Form was successfully verified and submitted.';
    } else {
      notice.innerText = '⚠️ Approving will lock the current field values and compute a cryptographic SHA-256 fingerprint.';
    }

  } catch (err) {
    console.error('Error selecting job:', err);
  }
}

function setupReviewControls() {
  document.getElementById('refresh-btn').onclick = () => refreshAll();

  // Bulk Approve Button
  const bulkBtn = document.getElementById('bulk-approve-btn');
  if (bulkBtn) {
    bulkBtn.onclick = async () => {
      if (!confirm('Bulk approve all jobs with >= 85% confidence and no security alerts?')) return;
      try {
        const res = await fetch('/api/jobs/bulk-approve', { method: 'POST' });
        const data = await res.json();
        alert(`⚡ Bulk approved ${data.count} jobs successfully!`);
        refreshAll();
      } catch (err) {
        alert('Bulk approve failed: ' + err);
      }
    };
  }

  // Approve Button
  document.getElementById('approve-btn').onclick = async () => {
    if (!selectedJobId) return;

    const editedFields = {};
    document.querySelectorAll('.field-input').forEach(input => {
      const fId = input.getAttribute('data-field-id');
      editedFields[fId] = input.value;
    });

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ edited_fields: editedFields }),
      });
      const data = await res.json();
      if (data.success) {
        alert(`✅ Job ${selectedJobId.slice(0, 8)} approved!\nSHA-256: ${data.approved_snapshot_hash.slice(0, 16)}...`);
        refreshAll();
        selectJob(selectedJobId);
      } else {
        alert('Approval failed: ' + (data.detail || 'Unknown error'));
      }
    } catch (err) {
      alert('Error during approval: ' + err);
    }
  };

  // Reject Button
  document.getElementById('reject-btn').onclick = async () => {
    if (!selectedJobId) return;
    const reason = prompt('Reason for rejection:', 'Rejected by operator');
    if (reason === null) return;

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/reject?reason=${encodeURIComponent(reason)}`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        refreshAll();
        selectJob(selectedJobId);
      }
    } catch (err) {
      alert('Error rejecting job: ' + err);
    }
  };

  // Submit Button
  document.getElementById('submit-btn').onclick = async () => {
    if (!selectedJobId) return;
    if (!confirm('SUBMIT FORM? This will perform verified submission to the target career portal.')) return;

    try {
      const res = await fetch(`/api/jobs/${selectedJobId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dry_run: false }),
      });
      const data = await res.json();
      if (data.success) {
        alert(`🎉 SUBMISSION SUCCESSFUL!\nReceipt: ${data.receipt_text || 'Completed'}`);
        refreshAll();
        selectJob(selectedJobId);
      } else {
        alert('❌ Submission aborted: ' + (data.error_message || 'Verification failure'));
      }
    } catch (err) {
      alert('Submission error: ' + err);
    }
  };

  // Handoff Button
  const handoffBtn = document.getElementById('handoff-btn');
  if (handoffBtn) {
    handoffBtn.onclick = async () => {
      if (!selectedJobId) return;
      alert("Launching interactive headful takeover. Complete login / CAPTCHA in the browser window.");
      try {
        const res = await fetch(`/api/jobs/${selectedJobId}/handoff`, { method: 'POST' });
        const data = await res.json();
        alert(data.message || "Handoff complete.");
        refreshAll();
        selectJob(selectedJobId);
      } catch (err) {
        alert("Handoff error: " + err);
      }
    };
  }
}

// -------------------------------------------------------------
// QR Launchpad (Mobile & Camera Ready)
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
    dropzone.classList.add('drag-over');
  };
  dropzone.ondragleave = () => dropzone.classList.remove('drag-over');
  dropzone.ondrop = (e) => {
    e.preventDefault();
    dropzone.classList.remove('drag-over');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  };

  fileInput.onchange = () => {
    if (fileInput.files && fileInput.files[0]) {
      handleFileSelected(fileInput.files[0]);
    }
  };

  function handleFileSelected(file) {
    selectedQrFile = file;
    filenameEl.innerText = file.name;
    previewBox.style.display = 'flex';
  }

  startBtn.onclick = async () => {
    if (!selectedQrFile) return;

    startBtn.disabled = true;
    startBtn.innerText = '⏳ Processing QR Codes & Triaging...';
    logBox.style.display = 'block';
    logBox.innerText = `[PIPELINE START] Scanning ${selectedQrFile.name} for QR codes...\n`;

    const autoConfirm = document.getElementById('auto-confirm-cb').checked;
    const formData = new FormData();
    formData.append('file', selectedQrFile);
    formData.append('auto_confirm', autoConfirm ? 'true' : 'false');

    try {
      const res = await fetch('/api/pipeline/scan-image', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (data.success) {
        logBox.innerText += `[SUCCESS] Decoded barcodes & created ${data.count} jobs.\n`;
        logBox.innerText += `Jobs Created: ${data.jobs_created.join(', ')}\n`;
        refreshAll();
        setTimeout(() => {
          document.getElementById('tab-btn-review').click();
        }, 1500);
      } else {
        logBox.innerText += `[ERROR] Pipeline error: ${data.detail || 'Unknown failure'}\n`;
      }
    } catch (err) {
      logBox.innerText += `[FAILED] Network error: ${err}\n`;
    } finally {
      startBtn.disabled = false;
      startBtn.innerText = '▶ Process QR Codes & Pre-Fill';
    }
  };
}

// -------------------------------------------------------------
// Tracker & Deadlines View
// -------------------------------------------------------------

function setupTrackerAndReminders() {
  // Tracker loaded when tab clicked
}

async function loadTrackerData() {
  try {
    // 1. Load reminders
    const remRes = await fetch('/api/reminders');
    if (remRes.ok) {
      const remData = await remRes.json();
      const listEl = document.getElementById('reminder-list');
      listEl.innerHTML = '';
      const reminders = remData.reminders || [];
      if (reminders.length === 0) {
        listEl.innerHTML = '<div class="text-muted-desc">No active deadline or opening reminders.</div>';
      } else {
        reminders.forEach(r => {
          const div = document.createElement('div');
          div.className = 'reminder-item';
          const type = r.opening_date ? 'OPENING' : 'DEADLINE';
          div.innerHTML = `
            <div>
              <span class="reminder-company">${escapeHtml(r.company || 'Job')}</span>
              <span style="color: #94a3b8;">(${escapeHtml(r.role || 'Role')})</span>
              <div class="reminder-notice">${escapeHtml(r.notes || (type + ': ' + (r.opening_date || r.deadline)))}</div>
            </div>
            <span class="status-pill status-${r.status}">${r.status}</span>
          `;
          listEl.appendChild(div);
        });
      }
    }

    // 2. Load tracker table
    const jobsRes = await fetch('/api/jobs');
    if (jobsRes.ok) {
      const jobsData = await jobsRes.json();
      const tbody = document.getElementById('tracker-tbody');
      tbody.innerHTML = '';
      const jobs = jobsData.jobs || [];
      jobs.forEach(j => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td style="font-weight: 600; color: #fff;">${escapeHtml(j.company || 'Unknown')}</td>
          <td>${escapeHtml(j.role || 'Unknown')}</td>
          <td><span class="platform-badge">${escapeHtml((j.platform || 'generic').toUpperCase())}</span></td>
          <td><span class="status-pill status-${j.status}">${j.status}</span></td>
          <td>${escapeHtml(j.deadline || j.opening_date || '-')}</td>
          <td>${escapeHtml(j.applied_date ? new Date(j.applied_date).toLocaleDateString() : '-')}</td>
          <td><a href="${escapeHtml(j.url)}" target="_blank" class="job-url-link">${escapeHtml(j.domain)}</a></td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.debug('Failed loading tracker:', err);
  }
}

// -------------------------------------------------------------
// Saved Answers Bank View
// -------------------------------------------------------------

function setupAnswersBank() {
  // Handlers for answers bank
}

async function loadAnswersBank() {
  try {
    const res = await fetch('/api/answers-bank');
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('answers-tbody');
    tbody.innerHTML = '';

    const answers = data.answers || [];
    answers.forEach(item => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td style="font-family: var(--font-mono); color: #38bdf8;">${escapeHtml(item.key)}</td>
        <td><span class="status-pill status-QUEUED">${escapeHtml(item.category)}</span></td>
        <td>${escapeHtml(item.question_text)}</td>
        <td>
          <input type="text" class="form-control ans-val-input" data-key="${escapeHtml(item.key)}" value="${escapeHtml(item.value)}" />
        </td>
        <td>
          <button class="btn btn-refresh btn-sm save-ans-btn" data-key="${escapeHtml(item.key)}">💾 Save</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    // Save buttons
    tbody.querySelectorAll('.save-ans-btn').forEach(btn => {
      btn.onclick = async () => {
        const k = btn.getAttribute('data-key');
        const input = tbody.querySelector(`.ans-val-input[data-key="${k}"]`);
        if (!input) return;
        try {
          const updateRes = await fetch('/api/answers-bank', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: k, value: input.value }),
          });
          const updateData = await updateRes.json();
          if (updateData.success) {
            btn.innerText = '✔ Saved';
            setTimeout(() => { btn.innerText = '💾 Save'; }, 1500);
          }
        } catch (e) {
          alert('Failed saving answer: ' + e);
        }
      };
    });

  } catch (err) {
    console.debug('Failed loading answers bank:', err);
  }
}

// -------------------------------------------------------------
// Candidate Profile Management
// -------------------------------------------------------------

function setupProfileManager() {
  const resumeInput = document.getElementById('resume-file-input');
  const uploadBtn = document.getElementById('upload-resume-btn');
  const saveBtn = document.getElementById('save-profile-btn');

  uploadBtn.onclick = () => resumeInput.click();

  resumeInput.onchange = async () => {
    if (!resumeInput.files || !resumeInput.files[0]) return;
    const file = resumeInput.files[0];
    uploadBtn.innerText = '⏳ Extracting Resume...';
    uploadBtn.disabled = true;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/profile/upload-resume', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (data.success) {
        alert('✅ Resume parsed and profile updated!');
        populateProfileForm(data.profile);
      } else {
        alert('Resume extraction failed: ' + (data.detail || 'Unknown error'));
      }
    } catch (err) {
      alert('Error uploading resume: ' + err);
    } finally {
      uploadBtn.innerText = '📄 Upload New Resume (PDF)';
      uploadBtn.disabled = false;
    }
  };

  saveBtn.onclick = async () => {
    const profileData = getProfileFormData();
    try {
      const res = await fetch('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileData),
      });
      const data = await res.json();
      if (data.success) {
        alert('💾 Verified profile successfully saved!');
      }
    } catch (err) {
      alert('Error saving profile: ' + err);
    }
  };
}

async function loadProfileData() {
  try {
    const res = await fetch('/api/profile');
    if (!res.ok) return;
    const data = await res.json();
    if (data.profile) {
      populateProfileForm(data.profile);
    }
  } catch (err) {
    console.debug('Failed to load profile:', err);
  }
}

function populateProfileForm(p) {
  document.getElementById('prof-full-name').value = p.full_name || '';
  document.getElementById('prof-email').value = p.email || '';
  document.getElementById('prof-phone').value = p.phone || '';
  document.getElementById('prof-address').value = p.address || '';
  document.getElementById('prof-city').value = p.city || '';
  document.getElementById('prof-state').value = p.state || '';
  document.getElementById('prof-postal').value = p.postal_code || '';
  document.getElementById('prof-country').value = p.country || '';
  document.getElementById('prof-linkedin').value = p.linkedin || '';
  document.getElementById('prof-github').value = p.github || '';
  document.getElementById('prof-portfolio').value = p.portfolio || '';
  document.getElementById('prof-skills').value = (p.skills || []).join(', ');
  document.getElementById('prof-summary').value = p.summary || '';
}

function getProfileFormData() {
  const skillsStr = document.getElementById('prof-skills').value || '';
  const skillsList = skillsStr.split(',').map(s => s.strip ? s.strip() : s.trim()).filter(Boolean);

  return {
    full_name: document.getElementById('prof-full-name').value || null,
    email: document.getElementById('prof-email').value || null,
    phone: document.getElementById('prof-phone').value || null,
    address: document.getElementById('prof-address').value || null,
    city: document.getElementById('prof-city').value || null,
    state: document.getElementById('prof-state').value || null,
    postal_code: document.getElementById('prof-postal').value || null,
    country: document.getElementById('prof-country').value || null,
    linkedin: document.getElementById('prof-linkedin').value || null,
    github: document.getElementById('prof-github').value || null,
    portfolio: document.getElementById('prof-portfolio').value || null,
    skills: skillsList,
    summary: document.getElementById('prof-summary').value || null,
  };
}

// -------------------------------------------------------------
// Audit Log Stream
// -------------------------------------------------------------

function setupAuditStream() {
  document.getElementById('refresh-audit-btn').onclick = () => loadAuditLogs();
}

async function loadAuditLogs() {
  try {
    const res = await fetch('/api/audit-logs?limit=50');
    if (!res.ok) return;
    const data = await res.json();
    const tbody = document.getElementById('audit-tbody');
    tbody.innerHTML = '';

    (data.logs || []).forEach(log => {
      const tr = document.createElement('tr');
      const timeStr = new Date(log.timestamp).toLocaleTimeString();
      const payloadStr = JSON.stringify(log.payload);

      tr.innerHTML = `
        <td style="font-family: var(--font-mono); font-size: 0.8rem; color: #94a3b8;">${timeStr}</td>
        <td style="font-family: var(--font-mono); color: #818cf8;">${log.job_id.slice(0, 8)}</td>
        <td><span class="actor-badge actor-${log.actor}">${log.actor}</span></td>
        <td><span class="action-badge">${log.action}</span></td>
        <td class="payload-preview" title="${escapeHtml(payloadStr)}">${escapeHtml(payloadStr)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.debug('Failed to load audit logs:', err);
  }
}

// Helper
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
