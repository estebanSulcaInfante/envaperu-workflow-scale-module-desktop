const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let backendProcess;

// Check if in development mode
const isDev = process.argv.includes('--dev');

function startBackend() {
  const backendPath = isDev
    ? path.join(__dirname, '..', 'backend', 'run.py')
    : path.join(process.resourcesPath, 'backend', 'scale_module_backend.exe');

  if (isDev) {
    // Development: run Python directly
    backendProcess = spawn('python', [backendPath], {
      cwd: path.join(__dirname, '..', 'backend'),
      env: { ...process.env }
    });
  } else {
    // Production: run the compiled executable
    backendProcess = spawn(backendPath, [], {
      cwd: path.dirname(backendPath),
      env: { ...process.env }
    });
  }

  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data}`);
  });

  backendProcess.on('close', (code) => {
    console.log(`[Backend] Process exited with code ${code}`);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 600,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    },
    icon: path.join(__dirname, 'icon.ico'),
    autoHideMenuBar: true,
    backgroundColor: '#0f172a'
  });

  // Load the frontend
  if (isDev) {
    // Development: load from Vite dev server
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    // Production: load built files
    const frontendPath = path.join(process.resourcesPath, 'frontend', 'index.html');
    mainWindow.loadFile(frontendPath);
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startBackend();
  
  // Wait a bit for backend to start
  setTimeout(createWindow, 1500);

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  // Kill backend process
  if (backendProcess) {
    backendProcess.kill();
  }
  
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});
