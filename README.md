# PrivateGitPush

将本地 git 仓库一键推送到私有服务器和 GitHub，自动处理初始化、提交、远程仓库创建、GitHub 认证等全流程。

## 功能特性

- **一键推送**：在任意目录运行，自动完成 git 初始化 → 提交 → 远程仓库创建 → 推送
- **GitHub 支持**：自动检测 GitHub 仓库是否存在，不存在则通过 `gh repo create` 创建（支持 Private/Public）
- **自动提交**：检测到未提交变更时自动 `git add . && git commit`，commit 信息包含变更统计
- **远程仓库管理**：SSH 目标通过 SSH 检测远程裸仓库是否存在并自动创建；GitHub 目标通过 gh CLI 检测并创建
- **SSH 多路复用**：支持 OpenSSH ControlMaster/ControlPersist，同一目标只需输入一次密码
- **交互式配置**：缺少 git 用户配置、推送目标配置或 gh 认证时，交互询问并自动写入
- **多目标推送**：支持同时推送到多个服务器（SSH 服务器 + GitHub）
- **位置决定拉取源**：`.gitprivatetarget` 第一行始终为默认拉取源，无论 remote 名叫什么
- **显式 remote 名**：支持在配置文件中指定 remote 名称，交换行顺序不影响 remote 映射
- **VSCode 集成**：配置 SSH 密钥后，VSCode 推送按钮可直接使用

## 系统要求

| 依赖 | 说明 |
|------|------|
| Python 3.6+ | 运行脚本 |
| git | 本地版本控制 |
| ssh | SSH 连接远程服务器 |
| gh CLI | 可选，用于 GitHub 仓库创建和推送 |
| OpenSSH 5.6+ | 可选，用于 SSH 多路复用 (ControlPersist) |

无需安装任何 Python 第三方包。

## 使用方法

### privategitpush.py — 一键推送

```bash
# 在当前目录运行
python3 privategitpush.py

# 在指定目录运行
python3 privategitpush.py /path/to/project
```

也可添加到 PATH 后直接运行：

```bash
chmod +x privategitpush.py
ln -s /path/to/PrivateGitPush/privategitpush.py ~/.local/bin/privategitpush

# 之后在任何目录直接运行
privategitpush
```

### syncremotes.py — 同步远程配置

当修改了 `.gitprivatetarget` 后，运行此脚本将变更同步到 `git config --local`：

```bash
python3 syncremotes.py
```

它会：
1. 解析 `.gitprivatetarget`
2. 添加/更新/删除 git remote
3. 设置分支拉取源（第一行的 remote）
4. 配置推送 refspec

## 配置文件

### `.gitprivatetarget`

在工作目录下创建此文件，定义推送目标。每行一个目标，支持三种格式：

#### 格式 1：显式 remote 名 + URL（推荐）

```
<remote_name> <url> [Private|Public]
```

适用于 GitHub 等非 SSH 目标。第三列指定仓库可见性，默认 `Private`。

```bash
origin https://github.com/cuihf06-Private/PrivateGitPush Public
github https://github.com/myorg/myrepo Private
```

#### 格式 2：显式 remote 名 + SSH（推荐）

```
<remote_name> <ssh_spec> <base_path> [repo_name]
```

交换行顺序不影响 remote 名映射。

```bash
private1 cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
backup dev@192.168.1.100:22 /home/dev/repos myproject
```

#### 格式 3：SSH 格式（原有，按位置分配 remote 名）

```
<ssh_spec> <base_path> [repo_name]
```

第一行分配 `origin`，其余依次分配 `private-1`、`private-2`...

```bash
cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
dev@192.168.1.100 /home/dev/repos backup-project
```

#### 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `remote_name` | 显式 remote 名（可选） | `origin`, `private1`, `github` |
| `url` | GitHub 或其他 HTTPS/SSH URL | `https://github.com/user/repo` |
| `Private/Public` | 仓库可见性，仅 URL 格式，默认 Private | `Public` |
| `ssh_spec` | SSH 地址，端口可省略（默认 22） | `cuihf@tinybot.cloud:29798` |
| `base_path` | 远程仓库基础路径 | `/data1/cuihf/GitRepos` |
| `repo_name` | 仓库名，留空则运行时交互询问 | `myproject` |

#### 格式检测规则

解析器自动检测格式：第一个词不含 `@` 且不以 URL 前缀开头 → 视为 remote 名（格式 1/2），否则视为原有 SSH 格式（格式 3）。

#### 拉取源规则

**拉取源始终为第一行**，由位置决定而非 remote 名决定。即使第一行叫 `private1`、第二行叫 `origin`，第一行仍然是默认拉取源。

**完整示例：**

```bash
# GitHub 为拉取源（第一行），私有服务器为推送备份
origin https://github.com/cuihf06-Private/PrivateGitPush Public
private1 cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush

# 私有服务器为拉取源（第一行），GitHub 为推送备份
private1 cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
github https://github.com/cuihf06-Private/PrivateGitPush Private

# 多 SSH 目标（原有格式）
cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos myproject
dev@192.168.1.100 /home/dev/repos backup-project
```

SSH 远程仓库实际路径为：`基础路径/仓库名.git`，例如 `/data1/cuihf/GitRepos/PrivateGitPush.git`。

> 如果 `.gitprivatetarget` 不存在，运行 `privategitpush.py` 时会交互式引导创建。

## 工具分工

| 工具 | 功能 |
|------|------|
| `privategitpush.py` | 一键推送：初始化 → 提交 → 创建远程仓库 → 配置 remote → 推送 |
| `syncremotes.py` | 仅同步配置：将 `.gitprivatetarget` 的变更同步到 `git config --local` |

## 完整工作流程

```
╔════════════════════════════╗
║      PrivateGitPush       ║
╚════════════════════════════╝

Step 1 ─ 检测/初始化 git 仓库
  ├─ 是 git 仓库 → 继续
  └─ 不是 → 自动 git init

Step 2 ─ 确保 git 用户配置
  ├─ user.name / user.email 已配置 → 继续
  └─ 未配置 → 交互询问，写入本地配置 (--local)

Step 3 ─ 自动提交未提交变更
  ├─ 有提交记录 & 无未提交变更 → 跳过
  ├─ 无提交记录 → 自动提交所有文件
  └─ 有未提交变更 → 自动提交所有变更
  │
  │  commit 格式: yymmdd_自动推送_更改x_新增y_删除z

Step 4 ─ 查找/创建配置文件
  ├─ .gitprivatetarget 存在 → 解析目标
  └─ 不存在 → 交互式创建

Step 5 ─ 处理 URL 目标 (GitHub 等)
  ├─ 检查 gh CLI 认证 → 未认证则交互输入 token 登录
  ├─ 检查仓库是否存在 → 不存在则 gh repo create
  ├─ 配置 git remote
  └─ git push

Step 5 ─ 处理 SSH 目标 (私有服务器)
  ├─ SSH 连接 (首次需输入密码)
  ├─ 检查远程裸仓库 → 不存在则 git init --bare 创建
  ├─ 配置 git remote
  └─ git push --all + git push --tags

Step 6 ─ 设置默认推送配置
  ├─ 第一行 remote 设为默认拉取源 (branch.<name>.remote)
  ├─ 配置推送到所有 remote
  └─ VSCode 推送按钮直接推送到拉取源

══════════════════════════
✓ 全部目标推送完成
```

## 自动提交详情

### 触发条件

- 仓库无任何提交记录（全新仓库）
- 仓库有未提交的文件变更（修改、新增、删除）

### Commit 信息格式

```
yymmdd_自动推送_更改x_新增y_删除z
```

| 部分 | 说明 | 来源 |
|------|------|------|
| `yymmdd` | 日期 (年月日各两位) | `datetime.now()` |
| `更改 x` | 已追踪文件被修改的数量 | `git diff --cached` 中 M/R 状态 |
| `新增 y` | 新创建文件的数量 | `git diff --cached` 中 A/C 状态 |
| `删除 z` | 已追踪文件被删除的数量 | `git diff --cached` 中 D 状态 |

**示例：**

```
260604_自动推送_更改0_新增2_删除0    ← 首次提交，2个新文件
260604_自动推送_更改1_新增1_删除1    ← 第二次提交，1修改+1新增+1删除
```

### Git 用户配置

如果 `git config user.name` 或 `git config user.email` 未设置（无论是全局还是本地），工具会交互询问并写入本地配置。配置仅写入当前仓库的 `.git/config`（`--local`），不影响全局设置。

## GitHub 认证

推送 GitHub 目标时，工具自动检查 `gh CLI` 认证状态：

- **已认证** → 直接继续
- **未认证** → 交互式要求提供 Personal Access Token，通过 `gh auth login --with-token` 登录

创建 Token: https://github.com/settings/tokens （需要 `repo` 权限）

## Git Remote 名称规则

| 场景 | Remote 名称 | 用途 |
|------|-------------|------|
| 显式指定（格式 1/2） | 配置文件中第一列指定的名称 | 按用户意图映射 |
| SSH 格式第 1 个（格式 3） | `origin` | 默认拉取源 |
| SSH 格式第 2+ 个（格式 3） | `private-1`, `private-2` ... | 额外备份目标 |

> **关键规则**：拉取源由**第一行位置**决定，而非 remote 名 "origin" 决定。

**VSCode 集成：**
- 运行 PrivateGitPush 后，VSCode 的"发布 branch"按钮直接推送到拉取源 remote
- VSCode 源代码管理面板显示拉取源为云端仓库
- 可通过 `git remote -v` 查看当前配置

后续可通过标准 git 命令管理：

```bash
# 查看远程
git remote -v

# 手动推送到拉取源
git push origin --all

# 手动推送到私有服务器
git push private1 --all

# 修改 remote URL
git remote set-url origin https://github.com/new-url

# 删除多余的 remote
git remote remove private1
```

## 推送策略

- 优先推送所有分支 (`git push --all`)
- 若全部推送失败，回退为仅推送当前分支
- 推送完成后追加推送标签 (`git push --tags`)
- GitHub 目标和 SSH 目标使用相同的推送策略

## 注意事项

1. **`.gitprivatetarget` 建议加入 `.gitignore`**：此文件包含服务器地址信息，通常不应推送到公开仓库
2. **SSH 密钥认证**（强烈推荐）：配置 SSH 密钥后可实现免密推送，VSCode 推送按钮也能正常工作。详见下方「SSH 密钥配置」
3. **远程权限**：确保 SSH 用户在远程服务器上有 `base_path` 目录的写入权限
4. **裸仓库**：远程创建的是 `git init --bare` 裸仓库，不包含工作区文件，仅作为推送目标
5. **VSCode 凭证问题**：如果 VSCode 推送时出现 "Missing or invalid credentials"，是因为 SSH 需要密码但 VSCode 后台进程无法弹出输入框。请配置 SSH 密钥认证（见下方）
6. **GitHub visibility**：URL 目标第三列为仓库可见性（Private/Public），默认 Private。仅对 `gh repo create` 有效
7. **Remote 名称唯一**：每个 remote 名称必须唯一，不能重复使用相同的名称

## SSH 密钥配置（VSCode 推送必需）

VSCode 的 Git 推送是后台进程，**不支持交互式输入密码**。如果出现 "Missing or invalid credentials" 错误，需要配置 SSH 密钥认证：

### 快速配置步骤

```bash
# 1. 生成 SSH 密钥（如果还没有）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 2. 将公钥复制到远程服务器（只需一次）
ssh-copy-id -p 29798 cuihf@tinybot.cloud

# 3. 测试无密码登录
ssh -p 29798 cuihf@tinybot.cloud
```

### 验证配置

```bash
# 测试 SSH 连接（不应提示输入密码）
ssh -T -p 29798 cuihf@tinybot.cloud

# 测试 git 推送（不应提示输入密码）
cd /path/to/repo
git push origin --dry-run
```

> 配置 SSH 密钥后，PrivateGitPush 和 VSCode 推送按钮都能无需密码正常工作。

## 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| SSH 连接失败 | 端口/地址错误 | 检查 `.gitprivatetarget` 中的 SSH 地址 |
| 远程仓库创建失败 | 无目录写入权限 | `chmod` 或 `chown` 远程 `base_path` |
| GitHub 仓库创建失败 | gh CLI 未认证或 token 权限不足 | 运行 `gh auth status`，确保 token 有 `repo` 权限 |
| 推送失败 | 远程仓库已有冲突内容 | `git push --force` 或手动解决 |
| 密码需多次输入 | OpenSSH < 5.6 或不支持多路复用 | 配置 SSH 密钥认证 |
| 提交失败 | user.name/email 未配置 | 工具会自动询问，也可手动 `git config --local user.name "xxx"` |
| **VSCode: Missing or invalid credentials** | SSH 需要密码但 VSCode 无法弹出输入框 | **配置 SSH 密钥认证（见上方）** |
| Remote 配置不对 | `.gitprivatetarget` 格式错误 | 确认格式：`<remote名> <URL> [visibility]` 或 `<remote名> <ssh> <path> [repo]` |
| 修改 `.gitprivatetarget` 后配置未更新 | git config 未同步 | 运行 `python3 syncremotes.py` |

## 目录结构

```
PrivateGitPush/
├── privategitpush.py    # 一键推送主程序 (单文件，无外部依赖)
├── syncremotes.py       # 远程配置同步工具 (单文件，无外部依赖)
├── .gitprivatetarget    # 推送目标配置文件 (不纳入 git)
├── .gitignore           # 忽略 .gitprivatetarget
└── README.md            # 本文档
```

## 许可

本项目仅供个人使用。