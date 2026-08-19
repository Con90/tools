const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const SyncManager = require('./sync');

const dataFile = () => path.join(app.getPath('userData'), 'tasks.json');

let mainWin = null;
let syncMgr = null;

function loadTasks() {
  try {
    return JSON.parse(fs.readFileSync(dataFile(), 'utf8'));
  } catch {
    return { version: 1, tasks: [] };
  }
}

function saveTasks(data) {
  const file = dataFile();
  const tmp = file + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file);
}

function createWindow() {
  mainWin = new BrowserWindow({
    width: 1240,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    autoHideMenuBar: true,
    backgroundColor: '#f6f7f9',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  // Links (e.g. the device-login page) open in the system browser.
  mainWin.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWin.loadFile('index.html');
}

app.whenReady().then(() => {
  syncMgr = new SyncManager(app.getPath('userData'), (status) => {
    if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send('sync:status', status);
  });

  ipcMain.handle('planner:load', () => loadTasks());
  ipcMain.handle('planner:save', (_e, data) => {
    saveTasks(data);
    syncMgr.scheduleAutoSync(() => loadTasks().tasks);
    return true;
  });

  ipcMain.handle('sync:getStatus', () => syncMgr.status());
  ipcMain.handle('sync:setClientId', (_e, id) => { syncMgr.setClientId(id); return syncMgr.status(); });
  ipcMain.handle('sync:connect', async () => {
    return await syncMgr.connect((info) => {
      if (mainWin && !mainWin.isDestroyed()) mainWin.webContents.send('sync:deviceCode', info);
    });
  });
  ipcMain.handle('sync:disconnect', () => syncMgr.disconnect());
  ipcMain.handle('sync:now', async () => await syncMgr.syncNow(loadTasks().tasks));

  createWindow();

  // Catch up on any changes made while the app was closed.
  syncMgr.scheduleAutoSync(() => loadTasks().tasks, 3000);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
