import { execFileSync } from "node:child_process";
import {
  copyFile,
  cp,
  mkdir,
  readFile,
  rename,
  stat,
  writeFile
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild-wasm";
import * as PELibrary from "pe-library";
import * as ResEdit from "resedit";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const BUILD = path.join(ROOT, "build");
const RELEASE_ROOT = path.resolve(ROOT, "..", "TechPulse");
const EXE_NAME = "TechPulse.exe";
const ICON_PNG = path.join(BUILD, "tech-pulse.png");
const ICON_ICO = path.join(BUILD, "tech-pulse.ico");
const EXE = path.join(BUILD, EXE_NAME);
const BLOB = path.join(BUILD, "tech-pulse.blob");
const PORT = "4199";

function assertSafeBuildPath(target) {
  if (target !== path.join(ROOT, "build")) {
    throw new Error(`Unsafe build path: ${target}`);
  }
}

async function createIco(pngPath, icoPath) {
  const png = await readFile(pngPath);
  const header = Buffer.alloc(22);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);
  header.writeUInt8(0, 6);
  header.writeUInt8(0, 7);
  header.writeUInt8(0, 8);
  header.writeUInt8(0, 9);
  header.writeUInt16LE(1, 10);
  header.writeUInt16LE(32, 12);
  header.writeUInt32LE(png.length, 14);
  header.writeUInt32LE(22, 18);
  await writeFile(icoPath, Buffer.concat([header, png]));
}

async function patchWindowsSubsystem(filePath) {
  const image = Buffer.from(await readFile(filePath));
  if (image[0] !== 0x4d || image[1] !== 0x5a) {
    throw new Error("EXE 缺少有效的 MZ 头");
  }
  const peOffset = image.readUInt32LE(0x3c);
  if (image.toString("ascii", peOffset, peOffset + 4) !== "PE\u0000\u0000") {
    throw new Error("EXE 缺少有效的 PE 头");
  }
  const optionalHeader = peOffset + 24;
  const subsystemOffset = optionalHeader + 68;
  if (![2, 3].includes(image.readUInt16LE(subsystemOffset))) {
    throw new Error("无法识别 EXE 的 Windows 子系统");
  }
  image.writeUInt16LE(2, subsystemOffset);
  await writeFile(filePath, image);
}

async function applyWindowsResources(exePath, iconPath) {
  const image = await readFile(exePath);
  const exe = PELibrary.NtExecutable.from(image, { ignoreCert: true });
  const resources = PELibrary.NtExecutableResource.from(exe);
  const iconFile = ResEdit.Data.IconFile.from(await readFile(iconPath));
  const iconGroups = ResEdit.Resource.IconGroupEntry.fromEntries(resources.entries);
  const iconGroupId = iconGroups[0]?.id ?? 1;
  ResEdit.Resource.IconGroupEntry.replaceIconsForResource(
    resources.entries,
    iconGroupId,
    1033,
    iconFile.icons.map((entry) => entry.data)
  );

  const versions = ResEdit.Resource.VersionInfo.fromEntries(resources.entries);
  if (versions.length) {
    const version = versions[0];
    version.setFileVersion(1, 1, 0, 0, 1033);
    version.setProductVersion(1, 1, 0, 0, 1033);
    version.setStringValues(
      { lang: 1033, codepage: 1200 },
      {
        CompanyName: "Tech Pulse",
        FileDescription: "科技脉冲 - 每日科技与 DIY 项目雷达",
        ProductName: "科技脉冲",
        OriginalFilename: EXE_NAME,
        LegalCopyright: "Local personal tool"
      }
    );
    version.outputToResourceEntries(resources.entries);
  }

  resources.outputResource(exe);
  const temporary = `${exePath}.resources.tmp`;
  await writeFile(temporary, Buffer.from(exe.generate()));
  await rename(temporary, exePath);
}

async function smokeTest(exePath) {
  const { spawn } = await import("node:child_process");
  const child = spawn(exePath, ["--background"], {
    cwd: BUILD,
    env: { ...process.env, PORT },
    stdio: "ignore",
    windowsHide: true
  });
  let passed = false;
  try {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      try {
        const response = await fetch(`http://127.0.0.1:${PORT}/api/bootstrap`, {
          signal: AbortSignal.timeout(800)
        });
        if (response.ok) {
          const payload = await response.json();
          if (!payload.config || !payload.today) throw new Error("接口返回不完整");
          passed = true;
          break;
        }
      } catch {
        // The process is still starting.
      }
    }
    if (!passed) throw new Error("EXE 启动后未通过接口自检");
  } finally {
    child.kill();
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

await mkdir(BUILD, { recursive: true });
assertSafeBuildPath(BUILD);
await esbuild.initialize({});

await esbuild.build({
  entryPoints: [path.join(ROOT, "server.mjs")],
  outfile: path.join(BUILD, "server.cjs"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node24",
  legalComments: "none",
  sourcemap: false
});

await esbuild.build({
  entryPoints: [path.join(ROOT, "public", "app.js")],
  outfile: path.join(BUILD, "app-check.cjs"),
  bundle: false,
  platform: "browser",
  format: "iife",
  target: ["es2022"],
  write: false
});

execFileSync(process.execPath, ["--experimental-sea-config", "sea-config.json"], {
  cwd: ROOT,
  stdio: "inherit"
});

execFileSync("powershell.exe", [
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-File",
  path.join(ROOT, "scripts", "make-icon.ps1"),
  "-Output",
  ICON_PNG
]);
await createIco(ICON_PNG, ICON_ICO);

await copyFile(process.execPath, EXE);
execFileSync(
  process.execPath,
  [
    path.join(ROOT, "node_modules", "postject", "dist", "cli.js"),
    EXE,
    "NODE_SEA_BLOB",
    BLOB,
    "--sentinel-fuse",
    "NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2"
  ],
  { cwd: ROOT, stdio: "inherit" }
);

await applyWindowsResources(EXE, ICON_ICO);

await patchWindowsSubsystem(EXE);
await smokeTest(EXE);

await mkdir(RELEASE_ROOT, { recursive: true });
await copyFile(EXE, path.join(RELEASE_ROOT, EXE_NAME));
await copyFile(ICON_ICO, path.join(RELEASE_ROOT, "tech-pulse.ico"));
await copyFile(
  path.join(ROOT, "node_modules", "webview-node", "bin", "webview2-host.exe"),
  path.join(RELEASE_ROOT, "webview2-host.exe")
);
await copyFile(
  path.join(ROOT, "node_modules", "webview-node", "bin", "WebView2Loader.dll"),
  path.join(RELEASE_ROOT, "WebView2Loader.dll")
);
const releaseData = path.join(RELEASE_ROOT, "data");
try {
  await stat(releaseData);
} catch {
  await mkdir(releaseData, { recursive: true });
  try {
    await cp(path.join(ROOT, "data"), releaseData, { recursive: true });
  } catch (error) {
    // 全新检出时 data/ 还不存在（被 .gitignore 忽略），留一个空目录即可。
    if (error.code !== "ENOENT") throw error;
  }
}
const releaseFiles = [
  ["release-readme.md", "使用说明.md"],
  ["stop-tech-pulse.ps1", "stop-tech-pulse.ps1"],
  ["stop-tech-pulse.cmd", "停止科技脉冲.cmd"],
  ["remove-startup.ps1", "remove-startup.ps1"],
  ["remove-startup.cmd", "移除开机启动.cmd"]
];
for (const [source, destination] of releaseFiles) {
  await copyFile(path.join(ROOT, source), path.join(RELEASE_ROOT, destination));
}

console.log(`构建完成：${path.join(RELEASE_ROOT, EXE_NAME)}`);
console.log(`单文件大小：${(await stat(path.join(RELEASE_ROOT, EXE_NAME))).size} bytes`);
