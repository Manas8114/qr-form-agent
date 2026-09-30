let currentJobs = [];
let selectedJobId = null;

async function loadJobs() {
  try {
    const res = await fetch('/api/jobs');
    const data = await res.json();
    currentJobs = data.jobs || [];
    renderJobsList();
    if (selectedJobId) {
      selectJob(selectedJobId);
    } else if (currentJobs.length > 0) {
      selectJob(currentJobs[0].id);
    }
  } catch (err) {
    console.error('Failed to load jobs:', err);
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

    // Button states
    const approveBtn = document.getElementById('approve-btn');
    const rejectBtn = document.getElementById('reject-btn');
    const canApprove = (job.status === 'AWAITING_APPROVAL' || job.status === 'NEEDS_HUMAN');
    approveBtn.disabled = !canApprove;
    rejectBtn.disabled = !canApprove;
    if (canApprove) {
      approveBtn.classList.remove('btn-disabled');
      rejectBtn.classList.remove('btn-disabled');
    } else {
      approveBtn.classList.add('btn-disabled');
      rejectBtn.classList.add('btn-disabled');
    }

  } catch (err) {
    console.error('Failed to load job details:', err);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
}

document.addEventListener('DOMContentLoaded', () => {
  const approveBtn = document.getElementById('approve-btn');
  if (approveBtn) {
    approveBtn.onclick = async () => {
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
          alert('Job approved and cryptographic snapshot locked!');
        } else {
          const err = await res.json();
          alert('Approval error: ' + (err.detail || 'Failed'));
        }
      } catch (err) {
        alert('Network error approving job');
      }
    };
  }

  const rejectBtn = document.getElementById('reject-btn');
  if (rejectBtn) {
    rejectBtn.onclick = async () => {
      if (!selectedJobId) return;
      const reason = prompt('Reason for rejection:', 'Rejected by human reviewer');
      if (reason === null) return;

      try {
        const res = await fetch(`/api/jobs/${selectedJobId}/reject?reason=${encodeURIComponent(reason)}`, {
          method: 'POST'
        });
        if (res.ok) {
          await loadJobs();
        }
      } catch (err) {
        alert('Error rejecting job');
      }
    };
  }

  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) {
    refreshBtn.onclick = loadJobs;
  }

  loadJobs();
  setInterval(loadJobs, 8000);
});
