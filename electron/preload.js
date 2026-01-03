const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods to the renderer process
contextBridge.exposeInMainWorld('electronAPI', {
  // Platform info
  platform: process.platform,
  
  // App version
  getVersion: () => ipcRenderer.invoke('get-version'),
  
  // Future: native dialogs, file system access, etc.
});
