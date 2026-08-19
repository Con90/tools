const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('plannerAPI', {
  load: () => ipcRenderer.invoke('planner:load'),
  save: (data) => ipcRenderer.invoke('planner:save', data),
  sync: {
    getStatus: () => ipcRenderer.invoke('sync:getStatus'),
    setClientId: (id) => ipcRenderer.invoke('sync:setClientId', id),
    connect: () => ipcRenderer.invoke('sync:connect'),
    disconnect: () => ipcRenderer.invoke('sync:disconnect'),
    now: () => ipcRenderer.invoke('sync:now'),
    onStatus: (cb) => ipcRenderer.on('sync:status', (_e, s) => cb(s)),
    onDeviceCode: (cb) => ipcRenderer.on('sync:deviceCode', (_e, i) => cb(i))
  }
});
