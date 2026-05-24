# codex-switch

`codex-switch` 是一个本地 Codex 账号池切换工具，用来保存多个 Codex 登录状态，并在需要时快速切换当前使用的账号。

它会把账号快照保存在 `~/.codex/account-pool/` 下，并切换全局的 `~/.codex/auth.json`。工具不会在终端输出 token 内容。

## 安装

安装时需要让 `pip` 找到这个项目。你可以进入项目目录后执行：

```bash
python3 -m pip install -e .
```

也可以不进入项目目录，直接把项目路径传给 `pip`：

```bash
python3 -m pip install -e /Users/huxiaoshuai/Desktop/common/projects/codexSwitch
```

Windows 上可以在项目目录下执行：

```powershell
py -m pip install -e .
```

也可以不进入项目目录，直接传项目路径：

```powershell
py -m pip install -e C:\path\to\codexSwitch
```

安装完成后，`codex-switch` 和 `codex-switch-gui` 会成为终端命令，可以在任意目录运行，不需要每次进入项目目录：

```bash
codex-switch
codex-switch-gui
```

`codex-switch` 是终端命令，`codex-switch-gui` 是图形界面。

## macOS 使用方式

安装完成后，`codex-switch` 会作为系统终端命令使用。你可以在 macOS 自带终端、iTerm2、VS Code 终端等任意终端窗口中运行它，不需要每次进入项目目录。

### 添加第一个账号

1. 正常打开 Codex Desktop，并登录你的第一个账号。
2. 在终端执行：

```bash
codex-switch add --note "主账号"
```

如果工具无法自动读取下次额度刷新日期，可以手动指定：

```bash
codex-switch add --next-refresh 2026-06-06 --note "主账号"
```

### 添加更多账号

不要直接点击 Codex Desktop 里的 `Log out`。退出登录可能会让之前账号的 refresh token 失效。

推荐流程：

```bash
codex-switch prepare-add
```

这个命令会备份并移除本机的 `~/.codex/auth.json`，让 Codex Desktop 回到登录界面，但不会主动注销已经保存的账号。

然后在 Codex Desktop 里登录新账号，再执行：

```bash
codex-switch add --note "备用账号"
```

### 切换账号

查看已保存账号：

```bash
codex-switch list
```

切换到指定账号：

```bash
codex-switch use user@example.com
```

macOS 下，`use`、`auto` 和 `prepare-add` 默认会重启 Codex Desktop，让正在运行的桌面端重新读取新的 `auth.json`。重启时会关闭 Codex app-server/helper 等相关子进程，然后重新打开 Codex。

如果只想为之后的 CLI 进程切换账号，不需要影响正在运行的桌面端，可以加上：

```bash
codex-switch use user@example.com --no-restart-desktop
```

### 自动切换可用账号

```bash
codex-switch auto
```

`auto` 会先更新账号额度状态，然后选择一个可用账号切换。它会优先选择下次刷新日期最早的可用账号。

## Windows 使用方式

### 安装

在项目目录中打开 PowerShell：

```powershell
py -m pip install -e .
```

如果你的环境里没有 `py`，可以使用：

```powershell
python -m pip install -e .
```

安装完成后，`codex-switch` 会作为终端命令使用。你可以在 PowerShell、CMD、Windows Terminal、VS Code 终端等任意终端窗口中运行它，不需要每次进入项目目录。

### 添加账号

先正常打开 Codex Desktop 并登录一个账号，然后执行：

```powershell
codex-switch add --note "主账号"
```

如果需要手动指定额度刷新日期：

```powershell
codex-switch add --next-refresh 2026-06-06 --note "主账号"
```

### 添加更多账号

不要使用 Codex Desktop 的 `Log out` 按钮来切换准备保存的账号。推荐执行：

```powershell
codex-switch prepare-add
```

随后在 Codex Desktop 中登录新的账号，再执行：

```powershell
codex-switch add --note "备用账号"
```

### 切换账号

查看账号列表：

```powershell
codex-switch list
```

切换到指定账号：

```powershell
codex-switch use user@example.com
```

Windows 下，`use`、`auto` 和 `prepare-add` 默认会关闭 `Codex.exe`，然后尝试从常见安装位置重新打开 Codex Desktop。如果没有找到安装路径，会尝试使用 Microsoft Store 应用 ID，最后再回退到系统的 `start Codex` 命令。

如果 Codex Desktop 是从 Microsoft Store 安装的，通常不容易找到普通的 `Codex.exe`。这时可以先在 PowerShell 里查 Codex 的应用 ID：

```powershell
Get-StartApps | Where-Object { $_.Name -like "*Codex*" }
```

输出里会有 `Name` 和 `AppID`。把 `AppID` 配置到环境变量 `CODEX_DESKTOP_APP_ID`。

临时只对当前 PowerShell 窗口生效：

```powershell
$env:CODEX_DESKTOP_APP_ID = "查询到的AppID"
codex-switch-gui
```

永久写入当前用户环境变量：

```powershell
setx CODEX_DESKTOP_APP_ID "查询到的AppID"
```

执行 `setx` 后，需要重新打开终端或重新启动图形界面，让新环境变量生效。

如果你安装的是普通 exe 版本，也可以把 Codex Desktop 的真实 exe 路径配置到环境变量 `CODEX_DESKTOP_EXE`。

临时只对当前 PowerShell 窗口生效：

```powershell
$env:CODEX_DESKTOP_EXE = "C:\Users\你的用户名\AppData\Local\Programs\Codex\Codex.exe"
codex-switch-gui
```

永久写入当前用户环境变量：

```powershell
setx CODEX_DESKTOP_EXE "C:\Users\你的用户名\AppData\Local\Programs\Codex\Codex.exe"
```

执行 `setx` 后，需要重新打开终端或重新启动图形界面，让新环境变量生效。路径要替换成你电脑上真实存在的 `Codex.exe` 路径。

如果不想自动重启桌面端：

```powershell
codex-switch use user@example.com --no-restart-desktop
```

## 终端命令说明

### 保存当前登录账号

```bash
codex-switch add
codex-switch add --note "主账号"
codex-switch add user@example.com --note "主账号"
codex-switch add --next-refresh 2026-06-06 --note "主账号"
```

不传账号别名时，工具会尽量从当前 `auth.json` 中读取登录邮箱作为账号名。

### 准备添加新账号

```bash
codex-switch prepare-add
codex-switch prepare-add --restart-desktop
codex-switch prepare-add --no-restart-desktop
```

这个命令用于安全地清理本地登录状态，让 Codex Desktop 显示登录界面，方便你登录并保存另一个账号。

### 查看账号

```bash
codex-switch list
```

`list` 会刷新 Codex 用量信息后再输出账号列表。显示的 `used` 百分比对应 Codex Desktop 展开后的 `Usage remaining` 行，`remaining` 会按 `100 - used` 计算。

### 查看当前账号

```bash
codex-switch current
```

如果当前 `~/.codex/auth.json` 能匹配到账号池里的账号，会显示当前正在使用的账号。

### 切换到指定账号

```bash
codex-switch use user@example.com
codex-switch use user@example.com --restart-desktop
codex-switch use user@example.com --no-restart-desktop
```

默认会重启 Codex Desktop。只有在你明确不需要桌面端立刻切换账号时，才建议使用 `--no-restart-desktop`。

### 自动切换账号

```bash
codex-switch auto
codex-switch auto --restart-desktop
codex-switch auto --no-restart-desktop
```

`auto` 的逻辑：

1. 如果某个账号的 `next_refresh_at` 已经到期或早于今天，会先把它标记为 `available`，并把刷新日期向后推 7 天，直到变成未来日期。
2. 然后刷新实时用量。
3. 只会选择状态为 `available` 的账号。
4. 如果有多个可用账号，会选择下次刷新日期最早的账号。

### 手动标记账号状态

```bash
codex-switch mark user@example.com available
codex-switch mark user@example.com unavailable
codex-switch mark user@example.com unknown
```

可用状态包括：

- `available`：账号可用。
- `unavailable`：账号当前不可用。
- `unknown`：账号状态未知。

### 手动设置下次刷新日期

```bash
codex-switch refresh user@example.com --next-refresh 2026-06-06
```

日期格式必须是 `YYYY-MM-DD`。

### 同步账号邮箱

```bash
codex-switch sync-emails
```

这个命令会尝试把已保存账号重命名为它们真实的登录邮箱。

### 重启 Codex Desktop

```bash
codex-switch restart-desktop
```

当你手动改过登录状态，或者希望 Codex Desktop 重新读取当前 `auth.json` 时，可以单独执行这个命令。

### 启动图形界面

```bash
codex-switch-gui
```

图形界面适合日常查看账号池和切换账号；终端命令适合自动化、脚本和快速操作。

## 注意事项

- 不要用 Codex Desktop 的 `Log out` 来添加新账号，优先使用 `codex-switch prepare-add`。
- 如果某个账号的 access token 过期，工具会尝试使用保存的 refresh token 自动刷新。
- 如果 refresh token 已失效，该账号的用量状态会保持为 `unknown`，`auto` 不会选择它。你需要重新登录该账号，并再次执行 `codex-switch add` 更新快照。
- `--codex-home` 可以指定 Codex 数据目录，默认是 `~/.codex`。

示例：

```bash
codex-switch --codex-home ~/.codex list
```
