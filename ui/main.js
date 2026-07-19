/* Electron main process: window + Python agent sidecar over stdio JSON lines. */
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const readline = require('readline');

const REPO_ROOT = path.join(__dirname, '..');
const SMOKE = process.argv.includes('--smoke');

let win = null;
let bridge = null;

function startBridge() {
  if (bridge) { try { bridge.kill(); } catch (_) {} }
  bridge = spawn('uv', ['run', '--no-sync', 'python', '-m', 'smartcode.uiserver'], {
    cwd: REPO_ROOT,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: process.platform === 'win32', // uv is uv.exe/shim on Windows
  });
  const rl = readline.createInterface({ input: bridge.stdout });
  rl.on('line', (line) => {
    let msg;
    try { msg = JSON.parse(line); } catch (_) { return; }
    if (SMOKE && msg.type === 'ready') {
      console.log('SMOKE_OK bridge ready');
      app.exit(0);
    }
    if (win && !win.isDestroyed()) win.webContents.send('bridge-message', msg);
  });
  bridge.stderr.on('data', (d) => process.stderr.write(`[bridge] ${d}`));
  bridge.on('exit', (code) => {
    if (win && !win.isDestroyed()) {
      win.webContents.send('bridge-message', { type: 'bridge_exit', code });
    }
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 700,
    show: !SMOKE,
    backgroundColor: '#0b0f17',
    title: 'smartcode',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

ipcMain.handle('bridge-send', (_e, obj) => {
  if (bridge && bridge.stdin.writable) {
    bridge.stdin.write(JSON.stringify(obj) + '\n');
    return true;
  }
  return false;
});

ipcMain.handle('bridge-restart', () => { startBridge(); return true; });

ipcMain.handle('reveal-path', (_e, p) => {
  const abs = path.isAbsolute(p) ? p : path.join(REPO_ROOT, p);
  shell.showItemInFolder(abs);
  return true;
});

ipcMain.handle('pick-files', async () => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Select target files',
    properties: ['openFile', 'multiSelections'],
  });
  return res.canceled ? [] : res.filePaths;
});

ipcMain.handle('pick-save', async (_e, suggested) => {
  const res = await dialog.showSaveDialog(win, {
    title: 'Output file',
    defaultPath: suggested || path.join(REPO_ROOT, 'generated', 'solution.py'),
  });
  return res.canceled ? null : res.filePath;
});

app.whenReady().then(() => {
  startBridge();
  createWindow();
  if (SMOKE) setTimeout(() => { console.error('SMOKE_TIMEOUT'); app.exit(1); }, 60000);
});

app.on('window-all-closed', () => {
  try { bridge?.stdin.write(JSON.stringify({ cmd: 'shutdown' }) + '\n'); } catch (_) {}
  setTimeout(() => { try { bridge?.kill(); } catch (_) {} app.quit(); }, 300);
});
