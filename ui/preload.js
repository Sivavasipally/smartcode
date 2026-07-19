const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('smartcode', {
  send: (obj) => ipcRenderer.invoke('bridge-send', obj),
  restart: () => ipcRenderer.invoke('bridge-restart'),
  pickFiles: () => ipcRenderer.invoke('pick-files'),
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
  pickSave: (suggested) => ipcRenderer.invoke('pick-save', suggested),
  reveal: (path) => ipcRenderer.invoke('reveal-path', path),
  onMessage: (cb) => ipcRenderer.on('bridge-message', (_e, msg) => cb(msg)),
});
