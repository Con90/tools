/* Outlook sync (main process): mirrors Planner tasks into a "Planner"
 * calendar on connected Microsoft accounts via Microsoft Graph.
 * One-way: Planner -> Outlook. */
'use strict';

const path = require('path');
const fs = require('fs');
const msal = require('@azure/msal-node');
const { safeStorage } = require('electron');

const SCOPES = ['Calendars.ReadWrite', 'User.Read'];
const CAL_NAME = 'Planner';
const GRAPH = 'https://graph.microsoft.com/v1.0';
const DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

class SyncManager {
  constructor(userDataDir, notify) {
    this.stateFile = path.join(userDataDir, 'sync-state.json');
    this.cacheFile = path.join(userDataDir, 'msal-cache.bin');
    this.notify = notify || (() => {});
    this.state = this.loadState();
    this.pca = null;
    this.busy = false;
    this.lastError = null;
    this.autoTimer = null;
  }

  loadState() {
    try {
      return JSON.parse(fs.readFileSync(this.stateFile, 'utf8'));
    } catch {
      return { clientId: '', account: null, calendarId: null, map: {}, hashes: {}, lastSync: null };
    }
  }

  saveState() {
    fs.writeFileSync(this.stateFile, JSON.stringify(this.state, null, 2));
  }

  cachePlugin() {
    const file = this.cacheFile;
    const enc = safeStorage.isEncryptionAvailable();
    return {
      beforeCacheAccess: async (ctx) => {
        try {
          const raw = fs.readFileSync(file);
          ctx.tokenCache.deserialize(enc ? safeStorage.decryptString(raw) : raw.toString('utf8'));
        } catch { /* first run */ }
      },
      afterCacheAccess: async (ctx) => {
        if (!ctx.cacheHasChanged) return;
        const data = ctx.tokenCache.serialize();
        fs.writeFileSync(file, enc ? safeStorage.encryptString(data) : data);
      }
    };
  }

  getPca() {
    if (!this.state.clientId) throw new Error('No client ID set. Paste your Azure app registration client ID first.');
    if (!this.pca) {
      this.pca = new msal.PublicClientApplication({
        auth: { clientId: this.state.clientId, authority: 'https://login.microsoftonline.com/common' },
        cache: { cachePlugin: this.cachePlugin() }
      });
    }
    return this.pca;
  }

  status() {
    return {
      clientId: this.state.clientId,
      connected: !!this.state.account,
      username: this.state.account ? this.state.account.username : null,
      busy: this.busy,
      lastSync: this.state.lastSync,
      lastError: this.lastError
    };
  }

  setClientId(id) {
    this.state.clientId = (id || '').trim();
    this.pca = null;
    this.saveState();
    this.notify(this.status());
  }

  async connect(onDeviceCode) {
    const pca = this.getPca();
    this.lastError = null;
    const result = await pca.acquireTokenByDeviceCode({
      scopes: SCOPES,
      deviceCodeCallback: (info) => onDeviceCode({
        userCode: info.userCode,
        verificationUri: info.verificationUri,
        message: info.message
      })
    });
    this.state.account = {
      homeAccountId: result.account.homeAccountId,
      username: result.account.username
    };
    // A fresh connection may be a different account: reset the mirror mapping.
    this.state.calendarId = null;
    this.state.map = {};
    this.state.hashes = {};
    this.saveState();
    this.notify(this.status());
    return this.status();
  }

  async disconnect() {
    try {
      const pca = this.getPca();
      const cache = pca.getTokenCache();
      const accounts = await cache.getAllAccounts();
      for (const a of accounts) await cache.removeAccount(a);
    } catch { /* cache may be empty */ }
    this.state.account = null;
    this.state.calendarId = null;
    this.state.map = {};
    this.state.hashes = {};
    this.lastError = null;
    this.saveState();
    this.notify(this.status());
  }

  async getToken() {
    if (!this.state.account) throw new Error('Not connected to a Microsoft account.');
    const pca = this.getPca();
    const account = (await pca.getTokenCache().getAllAccounts())
      .find((a) => a.homeAccountId === this.state.account.homeAccountId);
    if (!account) throw new Error('Saved account not found; please reconnect.');
    const res = await pca.acquireTokenSilent({ account, scopes: SCOPES });
    return res.accessToken;
  }

  async graph(method, apiPath, token, body, extraHeaders) {
    const res = await fetch(GRAPH + apiPath, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(extraHeaders || {})
      },
      body: body ? JSON.stringify(body) : undefined
    });
    if (res.status === 204) return null;
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = json && json.error ? `${json.error.code}: ${json.error.message}` : `HTTP ${res.status}`;
      const err = new Error(msg);
      err.httpStatus = res.status;
      throw err;
    }
    return json;
  }

  async ensureCalendar(token) {
    if (this.state.calendarId) {
      try {
        await this.graph('GET', `/me/calendars/${this.state.calendarId}?$select=id`, token);
        return this.state.calendarId;
      } catch { this.state.calendarId = null; }
    }
    const list = await this.graph('GET', '/me/calendars?$top=100&$select=id,name', token);
    let cal = (list.value || []).find((c) => c.name === CAL_NAME);
    if (!cal) cal = await this.graph('POST', '/me/calendars', token, { name: CAL_NAME });
    this.state.calendarId = cal.id;
    this.saveState();
    return cal.id;
  }

  buildPayload(task, tz) {
    const hh = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
    const payload = {
      subject: task.title || 'Untitled',
      start: { dateTime: `${task.date}T${hh(task.start)}:00`, timeZone: tz },
      end: { dateTime: `${task.date}T${hh(task.start + task.duration)}:00`, timeZone: tz },
      isReminderOn: false
    };
    const freq = task.repeat || 'none';
    if (freq !== 'none') {
      const dow = (new Date(task.date + 'T12:00:00').getDay() + 7) % 7; // 0=Sunday
      let pattern;
      if (freq === 'daily') pattern = { type: 'daily', interval: 1 };
      else if (freq === 'every2days') pattern = { type: 'daily', interval: 2 };
      else if (freq === 'every3days') pattern = { type: 'daily', interval: 3 };
      else if (freq === 'weekdays') pattern = { type: 'weekly', interval: 1, daysOfWeek: DAY_NAMES.slice(0, 5) };
      else pattern = { type: 'weekly', interval: 1, daysOfWeek: [DAY_NAMES[(dow + 6) % 7]] };
      payload.recurrence = {
        pattern,
        range: { type: 'noEnd', startDate: task.date, recurrenceTimeZone: tz }
      };
    }
    return payload;
  }

  async removeOccurrences(token, eventId, exdates, tz) {
    for (const d of exdates || []) {
      try {
        const inst = await this.graph(
          'GET',
          `/me/events/${eventId}/instances?startDateTime=${d}T00:00:00&endDateTime=${d}T23:59:59&$select=id`,
          token, null, { Prefer: `outlook.timezone="${tz}"` }
        );
        for (const occ of inst.value || []) {
          await this.graph('DELETE', `/me/events/${occ.id}`, token);
        }
      } catch (e) {
        if (e.httpStatus !== 404) throw e;
      }
    }
  }

  scheduleAutoSync(getTasks, delayMs = 5000) {
    if (!this.state.account) return;
    clearTimeout(this.autoTimer);
    this.autoTimer = setTimeout(() => {
      this.syncNow(getTasks()).catch(() => { /* status carries the error */ });
    }, delayMs);
  }

  async syncNow(tasks) {
    if (this.busy) return this.status();
    this.busy = true;
    this.lastError = null;
    this.notify(this.status());
    try {
      const token = await this.getToken();
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const calId = await this.ensureCalendar(token);
      const seen = new Set();
      let created = 0, updated = 0, deleted = 0;

      for (const task of tasks) {
        seen.add(task.id);
        const payload = this.buildPayload(task, tz);
        const hash = JSON.stringify(payload) + '|' + JSON.stringify(task.exdates || []);
        const eventId = this.state.map[task.id];

        if (!eventId) {
          const ev = await this.graph('POST', `/me/calendars/${calId}/events`, token, payload);
          this.state.map[task.id] = ev.id;
          await this.removeOccurrences(token, ev.id, task.exdates, tz);
          created++;
        } else if (this.state.hashes[task.id] !== hash) {
          try {
            await this.graph('PATCH', `/me/events/${eventId}`, token, payload);
            await this.removeOccurrences(token, eventId, task.exdates, tz);
            updated++;
          } catch (e) {
            if (e.httpStatus === 404) {
              const ev = await this.graph('POST', `/me/calendars/${calId}/events`, token, payload);
              this.state.map[task.id] = ev.id;
              await this.removeOccurrences(token, ev.id, task.exdates, tz);
              created++;
            } else throw e;
          }
        }
        this.state.hashes[task.id] = hash;
      }

      // Tasks deleted locally: remove their mirrored events.
      for (const taskId of Object.keys(this.state.map)) {
        if (seen.has(taskId)) continue;
        try {
          await this.graph('DELETE', `/me/events/${this.state.map[taskId]}`, token);
        } catch (e) {
          if (e.httpStatus !== 404) throw e;
        }
        delete this.state.map[taskId];
        delete this.state.hashes[taskId];
        deleted++;
      }

      this.state.lastSync = { at: new Date().toISOString(), created, updated, deleted };
      this.saveState();
    } catch (e) {
      this.lastError = e.message;
    } finally {
      this.busy = false;
      this.notify(this.status());
    }
    return this.status();
  }
}

module.exports = SyncManager;
