# github-publisher-skill-dsh

> English | [中文](README.zh.md)

DeepSeek Harness skill bundle that lets the AI publish a newly created DSH plugin
straight to GitHub with **zero user interaction**: create the repo (default public),
push the source, create a `vX.Y.Z` Release and upload the `.tgz` as a release asset.

Skill-only bundle (Python stdlib scripts, no third-party deps): no host hooks,
no native tools, no install scripts.

## One-time setup: GitHub PAT

GitHub does not allow anonymous writes, so you provide a token exactly once.
The AI will then publish any number of plugins fully automatically.

1. GitHub → **Settings → Developer settings → Personal access tokens**.
2. Choose one of:
   - **Classic token**: enable the `repo` scope (covers repo creation + contents + releases).
   - **Fine-grained token**: grant **Administration (Read and write, Account)**
     and **Contents (Read and write, All repositories)**.
3. Copy the token (`ghp_...` / `github_pat_...`) and give it to the AI in the
   DeepSeek Harness chat once; the AI writes it into the dedicated config file
   via stdin (the token never appears on a command line):

   ```
   echo <PAT> | python <skill-dir>/skills/github-publish/scripts/gh_config.py init --owner ya123-4
   ```

4. Verify: run the self-check

   ```
   python <skill-dir>/skills/github-publish/scripts/gh_check.py
   ```

   Expect exit code 0 and JSON with `"ok": true`.

## Config file

Detected in order (first existing wins; if none exists, the first path is used):

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

## How the AI uses it

After creating a plugin (with `package.json` and a packed tgz), the AI runs:

```
python <skill-dir>/skills/github-publish/scripts/gh_publish.py \
  --dir <plugin source dir> --tgz <absolute tgz path>
```

Stages: self-check → idempotent repo creation → local git init + commit
(bilingual README, LICENSE, .gitignore) → secure push → Release `v<version>` →
tgz asset upload → GitHub API verification.

Exit codes: `0` success · `2` check · `3` repo · `4` commit · `5` push ·
`6` release · `7` asset. Failures print JSON `{ok:false, stage, message, hint}`.

## Security

- The token lives only in the config file and in process memory. It is never
  written to `.git/config`, remote URLs, logs, or any emitted output (masked `***`).
- `git push` uses the openssl backend with a per-run temporary CA bundle
  (auto-generated from the system root store + the live peer handshake, which
  adapts to TLS middleboxes) and a process-only `Authorization` header.
- Config files are excluded from git via the generated `.gitignore` template.

## Local development

```powershell
$env:npm_config_cache = "$PSScriptRoot\.npm-cache"
npm pack .\github-publisher-skill-dsh --pack-destination .\dist
& "C:\Users\ybc12\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

## License

MIT — see [LICENSE](LICENSE).
