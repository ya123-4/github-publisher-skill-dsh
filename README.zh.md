# github-publisher-skill-dsh

> [English](README.md) | 中文

DeepSeek Harness 技能插件：让 AI 把新创造的 DSH 插件**全自动**入库 GitHub——
创建仓库（默认公开）、推送源码、创建 `vX.Y.Z` Release 并把 `.tgz` 作为 Release 资产上传。
全程用户零操作。

纯技能插件（Python 标准库脚本，零第三方依赖）：无宿主 hooks、无原生工具、无安装脚本。

## 一次性配置：GitHub PAT

GitHub 不允许匿名写入，所以 token 只需你提供一次，之后 AI 可以无限次全自动入库。

1. GitHub → **Settings → Developer settings → Personal access tokens**。
2. 二选一：
   - **Classic token**：勾选 `repo` 作用域（覆盖建仓 + 内容写入 + Release）。
   - **Fine-grained token**：授予 **Administration（Read and write，Account）**
     与 **Contents（Read and write，All repositories）**。
3. 把 token（`ghp_...` / `github_pat_...`）在 DeepSeek Harness 对话里交给 AI 一次，
   AI 会写入专属配置文件。
4. 验证：运行自检

   ```
   python <skill-dir>/skills/github-publish/scripts/gh_check.py
   ```

   期望退出码 0、输出 JSON 中 `"ok": true`。

## 配置文件

按顺序探测（取第一个已存在者；都不存在时默认用第一个路径）：

1. `%USERPROFILE%\.dsh\github-publisher\config.json`
2. `<workspace>\ws-rt\github-publisher-config.json`

```json
{
  "owner": "ya123-4",
  "token": "<PAT>",
  "author": { "name": "DSH Maintainers", "email": "dsh-maintainers@users.noreply.github.com" },
  "defaults": { "visibility": "public", "repo_suffix": "-dsh" }
}
```

## AI 如何使用

AI 创造出插件（含 `package.json` 且已打包出 tgz）后运行：

```
python <skill-dir>/skills/github-publish/scripts/gh_publish.py --dir <插件源码目录> --tgz <tgz绝对路径>
```

流程：自检 → 幂等建仓 → 本地 git init + 提交（自动生成双语 README、LICENSE、.gitignore）→
安全推送 → Release `v<version>` → tgz 资产上传 → GitHub API 回查验证。

退出码：`0` 成功 · `2` 自检 · `3` 建仓 · `4` 提交 · `5` 推送 · `6` Release · `7` 资产。
失败输出 JSON `{ok:false, stage, message, hint}`。

## 安全

- token 只存在于配置文件与进程内存；绝不写入 `.git/config`、remote URL、日志或任何输出（一律打码 `***`）。
- `git push` 使用 openssl 后端 + 每次运行临时生成的 CA（系统根证书库 + 实时握手证书，自动适配
  SteamTools 等 TLS 中间层）+ 进程级 `Authorization` 头。
- 自动生成的 .gitignore 模板排除一切 config 文件。

## 本地开发

```powershell
$env:npm_config_cache = "$PSScriptRoot\.npm-cache"
npm pack .\github-publisher-skill-dsh --pack-destination .\dist
& "C:\Users\ybc12\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

## 许可证

MIT — 见 [LICENSE](LICENSE)。
