const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('plannerAPI', {
  load: () => ipcRenderer.invoke('planner:load'),
  save: (data) => ipcRenderer.invoke('planner:save', data)
});
