# ui-automation 参考文档：通用操作技巧与注入代码（所有端适用）

> 按端分类的参考文档体系：
> - `common.md`（本文件）：通用技巧，所有端适用（入库开源）
> - `local/{端}.md`：各端环境信息与实战沉淀（团队私有，gitignore 不入库），首次使用按 `env-template.md` 创建
>
> 所有代码均通过 browser-use `evaluate_script` 注入执行；**仅用于测试环境**（内网测试环境地址见 `local/` 端文档），禁止在生产环境使用。

## 一、文件注入（upload_file 失效时的替代方案）

### 场景
`upload_file` MCP 工具对部分 `input[type=file]`（如 apk、zip、json 等非图片类型）不触发页面 change 事件，文件注入后页面无反应。

### 通用模板（evaluate_script 注入）

```javascript
// 1. 定位隐藏的 input[type=file]（按 accept 过滤）
const input = document.querySelector('input[type=file]');
// 或按 accept 属性精确匹配：
// const input = Array.from(document.querySelectorAll('input[type=file]'))
//   .find(i => (i.accept || '').includes('.apk'));

// 2. 用 DataTransfer 构造文件（参数：文件名、内容、MIME）
const dt = new DataTransfer();
dt.items.add(new File(['dummy'], 'test.apk', { type: 'application/vnd.android.package-archive' }));

// 3. 赋值并触发 change 事件（bubbles 必须为 true，否则部分框架监听不到）
input.files = dt.files;
input.dispatchEvent(new Event('change', { bubbles: true }));
```

### 注意事项
- 若页面有多个 `input[type=file]`，需按索引或 accept 精确选择：`document.querySelectorAll('input[type=file]')[3]`（索引与文件类型对应关系见各端文档）
- 注入后不要立即断言结果，页面可能异步处理（列表行出现、校验提示弹出），先 `take_snapshot` 或轮询 DOM
- 文件内容用占位字符串即可，多数上传场景只校验文件名/扩展名；若校验文件大小/内容结构，需用 `upload_file` 传真实文件或注入真实二进制内容
- 注入后若触发"必填校验静默拦截"（选文件无反应），先填齐其他必填项再注入

## 二、瞬时提示文案捕获（MutationObserver）

### 场景
toast / 错误横幅 / 确认弹窗出现后快速消失，`take_snapshot` 抓不到文案。

### 注入代码（先注入再操作）

```javascript
// 预埋捕获器：记录新增 DOM 节点的文本
window.__msgLog = [];
new MutationObserver(muts => {
  for (const m of muts) {
    for (const n of m.addedNodes) {
      if (n.nodeType === 1) {
        const t = (n.innerText || n.textContent || '').trim();
        if (t && t.length <= 500) window.__msgLog.push(t);
      }
    }
  }
}).observe(document.body, { childList: true, subtree: true });
```

### 读取捕获结果

```javascript
// 操作完成后读取（返回 JSON 字符串）
JSON.stringify(window.__msgLog)
```

### 注意事项
- 刷新页面后注入失效，需重新注入
- 弹窗（Modal）文案也会被捕获，注意区分 toast 与 Modal
- 捕获内容可能包含无关 DOM 文本，取最后几条与操作相关即可

## 三、XHR 拦截器（模拟上传慢速 / 失败场景）

### 场景
- 上传太快，无法观察到"上传中"状态（loading/进度）
- 需要复现上传失败、取消上传等异常提示

### 注入代码（完整版）

```javascript
// 拦截器：window.__ossBlock 失败模式 / window.__ossDelay 慢速模式（毫秒）
window.__ossBlock = false;   // true 时：200ms 后触发 error（模拟上传失败）
window.__ossDelay = 0;       // >0 时：延迟 N ms 再放行（模拟慢上传）
window.__ossDelay2 = 0;      // 第二档延迟（更慢，如 15000），便于观察长流程

(() => {
  const oOpen = XMLHttpRequest.prototype.open;
  const oSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url, ...rest) {
    this.__url = url || '';
    return oOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function(...args) {
    // 只拦截文件上传请求（按业务域名过滤，如 OSS 通常为 aliyuncs.com，见各端文档确认）
    if (this.__url.includes('aliyuncs.com')) {
      if (window.__ossBlock) {
        setTimeout(() => this.dispatchEvent(new Event('error')), 200);
        return;
      }
      const delay = window.__ossDelay2 || window.__ossDelay;
      if (delay > 0) {
        setTimeout(() => oSend.apply(this, args), delay);
        return;
      }
    }
    return oSend.apply(this, args);
  };
})();
```

### 使用示例
1. **模拟慢上传**（测"上传中"状态）：注入后设 `window.__ossDelay2 = 15000`，用 DataTransfer 注入大文件（如 30MB），上传后 100ms 轮询页面找"上传中"元素（如删除按钮、进度条），`take_snapshot` 或截图留证
2. **模拟上传失败**（测失败提示）：注入后设 `window.__ossBlock = true`，正常走上传流程，观察错误提示
3. **取消上传**（测取消场景）：慢速模式下点删除/取消按钮，观察提示；若 JS 触发删除走"未发送"路径不触发 error，按用户真实操作路径（发送中取消）验证，必要时用 MCP `click` 真实点击

### 注意事项
- 拦截器只对注入**之后**发起的请求生效
- 不同业务域名不同，过滤条件按实际网络请求调整（可用 `list_network_requests` 先确认上传域名，各端常见域名见分端文档）
- 用完恢复：`window.__ossBlock = false; window.__ossDelay = 0; window.__ossDelay2 = 0;`

## 四、前端源码核查（验证功能是否实现）

### 场景
UI 上观察不到某交互（如提示文案），需判断是"未触发"还是"未实现"。

### 方法
1. 浏览器 DevTools Network 中定位页面 JS chunk 文件（或从 `list_network_requests` 找 `.js` 资源）
2. 用 evaluate_script 抓取并搜索关键词：

```javascript
// 抓取指定 chunk 源码并按关键词搜索（返回命中片段）
fetch('/assets/chunk-2a287ffe.js')
  .then(r => r.text())
  .then(t => {
    const kws = ['versionName', 'uploadAPK', 'genStsToken', '一致', '请确认', '实际'];
    const hits = {};
    for (const kw of kws) {
      const idx = t.indexOf(kw);
      if (idx >= 0) hits[kw] = t.slice(Math.max(0, idx - 80), idx + 120);
    }
    return JSON.stringify(hits);
  })
```

### 判定逻辑
- 关键词无任何命中 → 功能未实现（对比需求描述，可建议提缺陷）
- 有关键词但逻辑与需求不符 → 记录实际逻辑，标注差异
- 注意：关键词可能命中无关代码（如错误码映射表），需结合上下文判断

## 五、接口链路验证（list_network_requests）

### 用法要点
- 在关键操作前后各调用一次，对比新增请求
- 支持按 `resourceTypes` 过滤（`fetch` / `xhr` 等），避免无关资源干扰
- 重点核对：请求 URL 是否指向预期接口、状态码、关键参数（body 中可查）
- 与 XHR 拦截器配合：先确认上传域名 → 再注入拦截器

### 建议验证点
- 上传链路：`genStsToken`（拿凭证）→ 上传域名 PUT（上传）→ 业务回调接口
- 保存/提交链路：请求体字段与表单填写是否一致
- 错误链路：失败时是否正确调用业务失败接口

## 六、快照 / 截图时机建议

- 每批操作开始前 `take_snapshot`（DOM 更新后旧 uid 失效，报 "No node with given id" 就重拍）
- 每个断言点：先 `take_snapshot` 观察 DOM → 需要留证再 `take_screenshot`（截图存 `_tmp/`，不污染归档目录）
- 瞬时状态（loading、上传中）：截图优先，snapshot 可能错过
- 弹窗出现后：先读 `window.__msgLog` 拿文案，再 snapshot 确认按钮结构
- 页面跳转后：`wait_for` 或重试 snapshot 确认加载完成再操作

## 七、其他高频技巧

| 技巧 | 说明 |
| :--- | :--- |
| 菜单点击不稳定 | 直接用 URL 导航（`#/xxx`），比层层点击菜单稳定 |
| `fill` 不生效 | 必须显式传 `value` 参数，且等待输入框可交互 |
| 必填校验静默拦截 | 先填齐必填项再触发提交；校验行为本身即测试点（记录"点击无反应"也是一种结果） |
| JS `.click()` 绕过校验 | UI 校验类用例必须用 MCP `click` 真实点击；仅数据准备类操作可用 JS 加速 |
| 删除按钮点击后 DOM 重渲染 | 旧 uid 失效 → 重新 snapshot 或改用 JS 选择器（如 `.anticon-delete`）点击 |
| 页面未加载完成 | `wait_for` 目标元素或重试 snapshot，禁止立即操作 |
