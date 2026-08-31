/**
 * 批量下载图片工具（Node）v2：下载 + manifest 缓存一致性校验
 *
 * 设计原因:
 * 1. PowerShell 5.1 按 ANSI 读取无 BOM 的 UTF-8 脚本，脚本内中文路径会乱码，Node 处理 UTF-8 中文路径可靠
 * 2. TAPD 下载链接默认有效 300s，失败时需重新调用 get_image 获取新链接后重试
 * 3. 缓存一致性：下载成功后写 .manifest.json（记录 md5/size/cached_at），校验模式比对实时图 Content-Length，
 *    解决"TAPD 同名图片内容被更新但缓存未失效"的盲区
 *
 * 用法:
 *   下载模式: node download_images.js <tasks.json>
 *     tasks.json: [{"url":"https://...","out":"D:\\path\\1.png"}, ...]
 *     下载成功后自动更新缓存目录 .manifest.json（key = 文件名 basename）
 *   校验模式: node download_images.js --verify <tasks.json>
 *     tasks.json: [{"url":"https://...","out":"D:\\path\\1.png"}, ...]
 *     从缓存目录 .manifest.json 读取记录的 size，发 GET+Range: bytes=0-0 请求比对实时 Content-Length
 *     输出: VERIFY OK / VERIFY CHANGED / VERIFY UNKNOWN（无 manifest 记录或网络异常）
 *     exit code: 全部 OK=0；存在 CHANGED/UNKNOWN=1
 *
 *   ⚠️ --verify 依赖 get_image 刚返回的 download_url（300s 有效），须在有效期内完成校验与重下
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const https = require('https');
const http = require('http');

const MANIFEST_NAME = '.manifest.json';
const CONCURRENCY = 4; // 下载/校验并发数（IO 瓶颈，并行收益大；限流避免 CDN 限流）
const isVerify = process.argv[2] === '--verify';
const tasksFile = isVerify ? process.argv[3] : process.argv[2];

if (!tasksFile) {
  console.error('Usage: node download_images.js [--verify] <tasks.json>');
  process.exit(2);
}

const tasks = JSON.parse(fs.readFileSync(tasksFile, 'utf-8'));

/* ---------- manifest 读写 ---------- */
function manifestPath(outFile) {
  return path.join(path.dirname(outFile), MANIFEST_NAME);
}

function readManifest(outFile) {
  const p = manifestPath(outFile);
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch {
    return { version: 1, files: {} };
  }
}

function writeManifest(outFile, files) {
  const p = manifestPath(outFile);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ version: 1, files }, null, 2), 'utf-8');
}

/* ---------- 下载（成功后写 manifest） ---------- */
function download(task, redirects) {
  return new Promise((resolve) => {
    const dir = path.dirname(task.out);
    fs.mkdirSync(dir, { recursive: true });
    const lib = task.url.startsWith('https:') ? https : http;

    const req = lib.get(task.url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location && redirects < 5) {
        res.resume();
        download({ ...task, url: res.headers.location }, redirects + 1).then(resolve);
        return;
      }
      if (res.statusCode !== 200) {
        resolve({ ...task, ok: false, err: `HTTP ${res.statusCode}` });
        res.resume();
        return;
      }
      const ws = fs.createWriteStream(task.out);
      res.pipe(ws);
      ws.on('finish', () => {
        ws.close();
        const size = fs.statSync(task.out).size;
        resolve({ ...task, ok: size > 100, size });
      });
      ws.on('error', (e) => resolve({ ...task, ok: false, err: e.message }));
    });
    req.setTimeout(60000, () => req.destroy(new Error('timeout')));
    req.on('error', (e) => resolve({ ...task, ok: false, err: e.message }));
  });
}

function recordToManifest(task, size) {
  const m = readManifest(task.out);
  const buf = fs.readFileSync(task.out);
  m.files[path.basename(task.out)] = {
    md5: crypto.createHash('md5').update(buf).digest('hex'),
    size,
    cached_at: new Date().toISOString(),
  };
  writeManifest(task.out, m.files);
}

/* ---------- 校验模式：GET + Range: bytes=0-0 比对 Content-Length ---------- */
function verifySize(task) {
  return new Promise((resolve) => {
    const m = readManifest(task.out);
    const key = path.basename(task.out);
    const expected = m.files && m.files[key] ? m.files[key].size : null;
    if (expected === null || expected === undefined) {
      resolve({ ...task, verdict: 'UNKNOWN', reason: 'no manifest record', expected: null });
      return;
    }
    const lib = task.url.startsWith('https:') ? https : http;
    const req = lib.get(task.url, { headers: { Range: 'bytes=0-0' } }, (res) => {
      let real = null;
      if (res.statusCode === 206 && res.headers['content-range']) {
        const mm = /bytes\s+\d+-\d+\/(\d+)/.exec(res.headers['content-range']);
        if (mm) real = parseInt(mm[1], 10);
      } else if (res.statusCode === 200 && res.headers['content-length']) {
        real = parseInt(res.headers['content-length'], 10);
      }
      res.destroy(); // 只读响应头，不消费 body
      if (real === null) {
        resolve({ ...task, verdict: 'UNKNOWN', reason: `HTTP ${res.statusCode} no size`, expected });
      } else {
        resolve({
          ...task, verdict: real === expected ? 'OK' : 'CHANGED', reason: `${real} vs ${expected}`, expected,
        });
      }
    });
    req.setTimeout(30000, () => req.destroy(new Error('timeout')));
    req.on('error', (e) => resolve({ ...task, verdict: 'UNKNOWN', reason: e.message, expected }));
  });
}

/* ---------- 并发控制（限流 map） ---------- */
async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let idx = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (idx < items.length) {
      const i = idx++;
      results[i] = await fn(items[i]);
    }
  });
  await Promise.all(workers);
  return results;
}

/* ---------- 主流程 ---------- */
(async () => {
  if (isVerify) {
    const results = await mapLimit(tasks, CONCURRENCY, (t) => verifySize(t));
    for (const r of results) {
      console.log(`VERIFY ${r.verdict} | ${path.basename(r.out)} | ${r.reason}`);
    }
    const bad = results.filter((r) => r.verdict !== 'OK');
    if (bad.length > 0) {
      console.log(`\n${bad.length} file(s) changed or unknown. Re-download via get_image refresh then run download mode.`);
      process.exit(1);
    }
    process.exit(0);
  }

  const results = await mapLimit(tasks, CONCURRENCY, (t) => download(t, 0));
  for (const r of results) {
    if (r.ok) {
      recordToManifest(r, r.size);
      console.log(`OK   | ${r.size} bytes | ${r.out}`);
    } else {
      console.log(`FAIL | ${r.err || 'too small'} | ${r.out}`);
    }
  }
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    console.log(`\n${failed.length} file(s) failed. TAPD links expire in 300s - re-call get_image to refresh URLs then retry.`);
    process.exit(1);
  }
})();
