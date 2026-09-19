/* Planner — Outlook sync panel (talks to the main process over IPC). */
'use strict';

const syncBackdrop = el('syncBackdrop');
const syncAPI = window.plannerAPI && window.plannerAPI.sync;

function renderSyncStatus(s) {
  el('syncDot').classList.toggle('hidden', !(s && s.connected));
  if (!s) return;
  el('syncSetup').classList.toggle('hidden', s.connected);
  el('syncConnected').classList.toggle('hidden', !s.connected);
  el('fClientId').value = s.clientId || '';
  el('syncUser').textContent = s.username || '';
  el('btnSyncNow').disabled = !!s.busy;
  el('btnSyncNow').textContent = s.busy ? 'Syncing…' : 'Sync now';
  const last = s.lastSync;
  el('syncLastLine').textContent = last
    ? `Last sync ${new Date(last.at).toLocaleString()} — ${last.created} added, ${last.updated} updated, ${last.deleted} removed.`
    : 'Not synced yet.';
  el('syncError').classList.toggle('hidden', !s.lastError);
  el('syncError').textContent = s.lastError ? `Sync error: ${s.lastError}` : '';
  if (s.connected) el('deviceCodeBox').classList.add('hidden');
}

el('btnSyncOpen').addEventListener('click', async () => {
  syncBackdrop.classList.remove('hidden');
  if (!syncAPI) {
    el('syncUnavailable').style.display = '';
    el('syncSetup').classList.add('hidden');
    el('syncConnected').classList.add('hidden');
    return;
  }
  renderSyncStatus(await syncAPI.getStatus());
});

el('btnSyncClose').addEventListener('click', () => syncBackdrop.classList.add('hidden'));
syncBackdrop.addEventListener('pointerdown', (e) => {
  if (e.target === syncBackdrop) syncBackdrop.classList.add('hidden');
});

if (syncAPI) {
  syncAPI.onStatus(renderSyncStatus);

  syncAPI.onDeviceCode((info) => {
    el('deviceCodeBox').classList.remove('hidden');
    el('dcCode').textContent = info.userCode;
    const a = el('dcLink');
    a.textContent = info.verificationUri;
    a.href = info.verificationUri;
  });

  el('btnConnect').addEventListener('click', async () => {
    el('syncError').classList.add('hidden');
    try {
      await syncAPI.setClientId(el('fClientId').value);
      renderSyncStatus(await syncAPI.connect());
    } catch (err) {
      el('syncError').classList.remove('hidden');
      el('syncError').textContent = `Connect failed: ${err.message.replace(/^.*Error invoking remote method '[^']+': (Error: )?/, '')}`;
    }
  });

  el('btnDisconnect').addEventListener('click', async () => {
    await syncAPI.disconnect();
    renderSyncStatus(await syncAPI.getStatus());
  });

  el('btnSyncNow').addEventListener('click', () => syncAPI.now());

  syncAPI.getStatus().then(renderSyncStatus);
}
