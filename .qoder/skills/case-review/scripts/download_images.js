/**
 * 批量下载图片工具（Node）
 * 用法: node download_images.js <tasks.json>
 * tasks.json 格式: [{"url":"https://...","out":"D:\\path\\1.png"}, ...]
 *
 * 设计原因:
 * 1. PowerShell 5.1 按 ANSI 读取无 BOM 的 UTF-8 脚本，脚本内中文路径会乱码，Node 处理 UTF-8 中文路径可靠
 * 2. TAPD 下载链接默认有效 300s，失败时需重新调用 get_image 获取新链接后重试
 */
const fs = require('fs');
const path = require('path');
const https = require('https');

if (process.argv.length < 3) {
  console.error('Usage: node download_images.js <tasks.json>');
  process.exit(2);
}

const tasks = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));

function download(task, redirects) {
  return new Promise((resolve) => {
    const dir = path.dirname(task.out);
    fs.mkdirSync(dir, { recursive: true });

    const req = https.get(task.url, (res) => {
      // 跟随重定向（最多 5 次）
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
        // 文件过小视为下载失败（如 13 字节的过期链接页面）
        resolve({ ...task, ok: size > 100, size });
      });
      ws.on('error', (e) => resolve({ ...task, ok: false, err: e.message }));
    });
    req.setTimeout(60000, () => req.destroy(new Error('timeout')));
    req.on('error', (e) => resolve({ ...task, ok: false, err: e.message }));
  });
}

(async () => {
  const results = [];
  for (const t of tasks) {
    results.push(await download(t, 0));
  }
  for (const r of results) {
    console.log(`${r.ok ? 'OK  ' : 'FAIL'} | ${r.size ? r.size + ' bytes' : r.err || 'too small'} | ${r.out}`);
  }
  const failed = results.filter((r) => !r.ok);
  if (failed.length > 0) {
    console.log(`\n${failed.length} file(s) failed. TAPD links expire in 300s - re-call get_image to refresh URLs then retry.`);
    process.exit(1);
  }
})();
