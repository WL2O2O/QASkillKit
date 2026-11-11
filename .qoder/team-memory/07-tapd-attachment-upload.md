# 07 - TAPD 需求附件上传工作流（browser-use）

> 场景：将本地 MD/文件上传到 TAPD 需求详情页的**附件区**。
> 适用工具：browser-use MCP（navigate_page / evaluate_script / take_snapshot / upload_file）。
> 沉淀来源：S93 版本 9 个需求 MD 上传实战验证（2026-08-27，9/9 成功）。

## 一、核心难点（为什么直接 upload_file 会失败）

TAPD 需求详情页的附件上传控件有 **3 层隐藏/陷阱**，必须逐层处理后 upload_file 才能生效：

| # | 元素 | 默认状态 | 问题 |
|:---|:---|:---|:---|
| 1 | 附件区展开按钮 `.entity-detail-attachment-top__expand` | `visibility: hidden` | 不让可见直接 click 无效，附件区不展开 |
| 2 | 上传面板 `.inline-cell__attachments-panel` | 定位在屏幕外（`left: -630px`） | 即使展开也"看不见"，点击/上传落空 |
| 3 | 文件选择框 `input.upload-input` | `display: none` | upload_file 直接对着它传会报 `sort:不允许为空`，附件区始终为空 |

另外：`take_snapshot` 会把 `input.upload-input` 渲染为 **"选择文件" 按钮**（`value="未选择任何文件"`）——这个"按钮"就是 upload_file 的 uid 目标。

## 二、标准工作流（7 步，已验证可靠）

前置：需求详情页 URL 格式 `https://www.tapd.cn/tapd_fe/{workspace_id}/story/detail/11{workspace_id}00{需求ID}`（workspace_id 取 `config/project.config.json` 的 `tapd.workspace_id`）

### 步骤 1：导航到需求详情页

browser-use `navigate_page` → 上述 URL，然后等待 5 秒（PowerShell：`Start-Sleep -Seconds 5`）。

### 步骤 2：展开附件区 + 点击 + 按钮（evaluate_script）

```javascript
() => {
  const expandIcon = document.querySelector('.entity-detail-attachment-top__expand');
  if (expandIcon) {
    expandIcon.style.visibility = 'visible';
    expandIcon.click();
  }
  setTimeout(() => {
    const uploadContent = document.querySelector('.entity-detail-attachment .upload-content');
    if (uploadContent) {
      const btn = uploadContent.querySelector('button');
      if (btn) btn.click();
    }
  }, 200);
  return { expandClicked: !!expandIcon };
}
```

要点：先把 `+` 按钮 visibility 设为 visible 再 click；200ms 后再点 upload-content 里的 button 弹出 panel。
返回 `expandClicked: true` 即成功。

### 步骤 3：等待 3 秒（panel 展开动画）

### 步骤 4：重定位 panel + 让 file input 可见（evaluate_script）

```javascript
() => {
  const panel = document.querySelector('.inline-cell__attachments-panel');
  if (panel) {
    panel.style.left = '100px';
    panel.style.top = '100px';
    panel.style.zIndex = '99999';
  }
  const fileInput = document.querySelector('input.upload-input');
  if (fileInput) {
    fileInput.style.cssText = 'display: block !important; position: relative !important; width: 200px !important; height: 40px !important; opacity: 1 !important; visibility: visible !important; z-index: 99999 !important; left: 0; top: 0;';
  }
  return { panelExists: !!panel, fileInputVisible: fileInput ? getComputedStyle(fileInput).display : null };
}
```

要点：返回 `panelExists: true, fileInputVisible: "block"` 才能进行下一步。

### 步骤 5：take_snapshot 获取 "选择文件" 按钮 uid

在 snapshot 中找：`button "选择文件" value="未选择任何文件"`，记下其 uid（如 `80_284`）。

### 步骤 6：upload_file 上传

browser-use `upload_file`，参数：
- `filePath`：本地文件绝对路径
- `uid`：步骤 5 获取的 "选择文件" 按钮 uid

上传后 panel 中会短暂显示 `0%` 进度。

### 步骤 7：等待 5~8 秒后验证（evaluate_script）

```javascript
() => {
  const attachLinks = Array.from(document.querySelectorAll('a[href*="attachment"]'));
  return {
    attachLinks: attachLinks.map(a => ({ href: a.href, text: a.textContent.trim() }))
  };
}
```

返回的 `attachLinks` 中出现**文件名**（如 `【1019415】...-测试用例.md`）即上传成功。

## 三、批量上传（多个需求循环）

对每个需求 ID 重复步骤 1~7 即可，注意：

- 每次导航到新页面后，**panel / file input 的隐藏状态会重置**，必须重新执行步骤 2~5（不能复用旧 uid）
- 单个 MD 文件（<25KB）上传 + 落库全程约 10~15 秒，节奏：上传后 sleep 8 秒再验证

## 四、坑点清单

| 坑 | 现象 | 解法 |
|:---|:---|:---|
| 直接 upload_file 报 `sort:不允许为空` | 工具返回"成功"但附件区一直为空 | 必须先完成步骤 2~4（展开 + 重定位 panel + 显示 input） |
| 找不到上传入口 | 附件区为空，无任何按钮 | `+` 按钮 visibility hidden，用 evaluate_script 置 visible 后 click |
| panel 打开了却"看不到" | DOM 里存在但页面上找不到 | panel 定位在屏幕外，需重定位 left/top/zIndex |
| "选择文件" 按钮哪来的 | snapshot 里的 button 其实是 `input.upload-input` | 它就是 upload_file 的 uid 目标，不是真按钮 |
| PowerShell sleep 失败 | `timeout /t 8` 被 PS 解析为 Out-File 报错 | 用 `Start-Sleep -Seconds N` |
| 上传后立即验证为空 | attachLinks 无文件名 | panel 显示 0% 是异步上传中，等 5~8 秒再验证 |

## 五、相关记忆

- 个人记忆：《TAPD需求附件上传可靠工作流（browser-use）》（步骤索引，指向本文件）
- 任务记忆：《Excel需求文档转MD测试用例并上传TAPD》《批量Excel需求转标准化MD测试用例》
