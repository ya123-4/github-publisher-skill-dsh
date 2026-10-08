---
name: github-publish
description: Use when the AI has created a new DSH plugin and needs to publish it to GitHub automatically with zero user interaction — create the repo (default public), push the source, create a vX.Y.Z Release and upload the .tgz as a release asset. Also use for re-publishing an existing plugin (idempotent) or when the user asks to "入库 GitHub" / "发布到 GitHub".
---

# github-publish：插件自动入库 GitHub

把 AI 新创造的 DSH 插件**全自动**发布到 GitHub：建仓 → 推送 → Release + tgz 资产。
用户只需完成一次性 PAT 配置（见 README.zh.md），之后每次入库零操作。

## 前置条件

1. 插件源码目录存在且含 `package.json`（name/version/description）。
2. 插件已打包出 tgz：在插件包目录运行（Windows）：

   ```
   $env:npm_config_cache = "<workspace>\.npm-cache"
   & "C:\Program Files\nodejs\npm.cmd" pack <插件目录> --pack-destination <目录>
   ```

   记录 tgz 的绝对路径（本机 profile 依赖是绝对 file: 路径，tgz 不可移动）。
3. 一次性 PAT 已配置（否则先运行 gh_check.py 完成配置，见下）。

## 工作流

### 第 1 步：环境自检（配置过 PAT 时可跳过）

```
python <skills>/github-publish/scripts/gh_check.py [--config <配置文件>]
```

判据：退出码 0 且输出 JSON 中 `ok=true`（`tls_ok`、`token_ok`、`git_ok` 全为 true）。

若配置缺失（gh_check 报"无法读取配置文件"），向用户索要一次 PAT，然后用 **stdin** 方式写配置（
token 绝不能出现在命令行参数里）：

```
echo <PAT> | python <skills>/github-publish/scripts/gh_config.py init --owner <owner>
```

判据：输出 JSON `ok=true` 且 `config_path` 指向实际写入位置（home 不可写时自动回落 ws-rt）。

### 第 2 步：执行入库

```
python <skills>/github-publish/scripts/gh_publish.py --dir <插件源码目录> --tgz <tgz绝对路径> [--config <配置文件>]
```

参数默认规则：

| 参数 | 默认 |
|---|---|
| `--repo-name` | `package.json` 的 name 加 `defaults.repo_suffix`（`-dsh`，已含后缀则不重复加） |
| `--description` | `package.json` 的 description |
| `--private` | 不传 = 公开（`defaults.visibility`） |
| `--tag` | `v<package.json version>` |
| `--config` | 自动探测：`%USERPROFILE%\.dsh\github-publisher\config.json` → `<workspace>\ws-rt\github-publisher-config.json` |

脚本内部流程：自检（tgz 合法性、TLS、token 有效性）→ 幂等建仓（已存在则复用）→
本地 git init/commit（README 双语 + LICENSE + .gitignore 自动生成）→ 安全推送
（openssl 后端 + 临时 CA + Authorization 进程级注入，token 不落盘）→ 创建 Release →
上传 tgz 资产 → GitHub API 回查验证。

### 第 3 步：向用户报告

成功时输出 JSON 含 `repo_url`、`release_url`、`asset_url`、`tag`。用中文一句话报告，例如：

> 已入库：https://github.com/ya123-4/foo-dsh（Release v0.1.0，tgz 资产已上传）。

失败时按退出码对照表向用户解释原因与下一步。

## 退出码对照表

| 退出码 | 含义 | AI 的处理 |
|---|---|---|
| 0 | 成功 | 报告 URL |
| 2 | 自检/脚本自身失败（含 `stage=fatal` 的未预期错误） | 按 hint 处理：缺 PAT 就向用户索要一次（stdin 方式写配置）；tgz 缺失就重新 npm pack |
| 3 | 建仓失败 | 常见：token 权限不足（需 repo 作用域）——指引用户换 PAT |
| 4 | 本地提交失败 | 检查插件目录可写、git 可用 |
| 5 | 推送失败 | 输出 JSON 的 message 含 git stderr 摘要（pull/push 区分）；按摘要重试一次或报告用户 |
| 6 | Release 失败 | 常见：tag 已存在——bump 插件 version 后重发 |
| 7 | 资产上传失败 | 常见：同名资产内容不同（按 sha256 判定）——报告并请用户决定 |

## 安全铁律（必须遵守）

- token 只允许存在于配置文件与进程内存；绝不写入 `.git/config`、remote URL、日志或任何输出。
- 任何给用户看的输出中若出现 token 必须打码为 `***`。
- 配置文件路径必须被 .gitignore 排除（模板已含 `*config.json`）。
- 同一插件重复入库是幂等的：已存在仓库/Release 不会静默覆盖，脚本会明确报错或跳过。

## 本机环境适配（已内置，AI 无需处理）

- git push 固定使用 openssl 后端 + 脚本自动生成的临时 CA（自动适配 SteamTools 中间层）。
- GitHub API 全部走 Python urllib（本机已验证稳定通道）。
- 所有文件读写 UTF-8；PowerShell 仅用于调命令，不用来改写文本文件。
