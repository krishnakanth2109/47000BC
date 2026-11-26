// Startup script — run from project root
// Usage: node start.js

const { spawn } = require("child_process");
const path = require("path");

const root = __dirname;
const backendDir = path.join(root, "backend");
const frontendDir = path.join(root, "frontend");

console.log("Starting CCTV Attendance System...\n");

// Start FastAPI backend
const backend = spawn("uvicorn", ["main:app", "--reload", "--host", "0.0.0.0", "--port", "8080"], {
  cwd: backendDir,
  stdio: "inherit",
  shell: true,
});

// Start Vite frontend dev server
const frontend = spawn("npm", ["run", "dev"], {
  cwd: frontendDir,
  stdio: "inherit",
  shell: true,
});

process.on("SIGINT", () => {
  backend.kill();
  frontend.kill();
  process.exit(0);
});

backend.on("close", (code) => {
  console.log(`Backend exited with code ${code}`);
  process.exit(code);
});
