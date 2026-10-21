// Exposes only a folder picker to the page. The page itself talks to the local service over HTTP.
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("velouraNative", {
  chooseFolder: () => ipcRenderer.invoke("choose-folder"),
});
