# PrivateGitPush

将本地 git 仓库通过 SSH 一键推送到私有服务器，自动处理初始化、提交、远程仓库创建等全流程。

## 功能特性

- **一键推送**：在任意目录运行，自动完成 git 初始化 → 提交 → 远程仓库创建 → 推送
- **自动提交**：检测到未提交变更时自动 `git add . && git commit`，commit 信息包含变更统计
- **远程仓库管理**：通过 SSH 检测远程裸仓库是否存在，不存在则自动创建
- **SSH 多路复用**：支持 OpenSSH ControlMaster/ControlPersist，同一目标只需输入一次密码
- **交互式配置**：缺少 git 用户配置或推送目标配置时，交互询问并自动写入
- **多目标推送**：支持同时推送到多个服务器

## 系统要求

| 依赖 | 说明 |
|------|------|
| Python 3.6+ | 运行脚本 |
| git | 本地版本控制 |
| ssh | SSH 连接远程服务器 |
| OpenSSH 5.6+ | 可选，用于 SSH 多路复用 (ControlPersist) |

无需安装任何 Python 第三方包。

## 使用方法

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

## 配置文件

### `.gitprivatetarget`

在工作目录下创建此文件，定义推送目标。每行一个目标，格式：

```
user@host:port /path/to/repos/dir [repo_name]
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `user@host:port` | SSH 地址，端口可省略 (默认 22) | `cuihf@tinybot.cloud:29798` |
| `/path/to/repos/dir` | 远程仓库基础路径 | `/data1/cuihf/GitRepos` |
| `repo_name` | 仓库名，留空则运行时交互询问 | `myproject` |

**示例：**

```bash
# 单目标推送，仓库名每次询问
cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos

# 单目标推送，指定仓库名
cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos myproject

# 多目标推送
cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos myproject
dev@192.168.1.100 /home/dev/repos backup-project
```

远程仓库实际路径为：`基础路径/仓库名.git`，例如 `/data1/cuihf/GitRepos/myproject.git`。

> 如果 `.gitprivatetarget` 不存在，运行时会交互式引导创建。

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
  │  例如: 260604_自动推送_更改3_新增5_删除1

Step 4 ─ 查找/创建配置文件
  ├─ .gitprivatetarget 存在 → 解析目标
  └─ 不存在 → 交互式创建

Step 5 ─ 处理每个推送目标
  ├─ SSH 连接 (首次需输入密码)
  ├─ 检查远程裸仓库 → 不存在则 git init --bare 创建
  ├─ 配置 git remote (名为 private 或 private-0/private-1...)
  └─ git push --all + git push --tags

══════════════════════════
✓ 全部 N 个目标推送完成
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
260604_自动推送_更改3_新增5_删除1    ← 普通提交
```

### Git 用户配置

如果 `git config user.name` 或 `git config user.email` 未设置（无论是全局还是本地），工具会交互询问并写入本地配置：

```
未配置 git user.name
请输入用户名 (user.name): _

未配置 git user.email
请输入邮箱 (user.email): _
```

配置仅写入当前仓库的 `.git/config`（`--local`），不影响全局设置。

## SSH 多路复用

当系统 OpenSSH 版本 >= 5.6 时，工具自动启用 SSH ControlMaster/ControlPersist 多路复用：

- 首次 SSH 连接需要输入密码
- 后续所有 SSH 操作和 `git push` 复用同一连接，无需再次输入密码
- 连接保持 10 分钟 (`ControlPersist=10m`)，超时后自动关闭

实现方式：
- SSH 命令自动附加 `-o ControlMaster=auto -o ControlPath=<socket> -o ControlPersist=10m`
- `git push` 通过 `GIT_SSH_COMMAND` 环境变量注入相同的 SSH 参数

> 如果 OpenSSH 版本 < 5.6，每次 SSH 操作需单独输入密码。建议配置 SSH 密钥认证以避免重复输入。

## Git Remote 名称规则

| 目标数量 | Remote 名称 |
|----------|-------------|
| 1 个 | `private` |
| 2+ 个 | `private-0`, `private-1`, `private-2` ... |

后续可通过标准 git 命令管理：

```bash
# 查看远程
git remote -v

# 手动推送
git push private --all

# 修改 remote URL
git remote set-url private ssh://new-host:port/path

# 删除 remote
git remote remove private
```

## 推送策略

- 优先推送所有分支 (`git push --all`)
- 若全部推送失败，回退为仅推送当前分支
- 推送完成后追加推送标签 (`git push --tags`)

## 注意事项

1. **`.gitprivatetarget` 建议加入 `.gitignore`**：此文件包含服务器地址信息，通常不应推送到公开仓库
2. **SSH 密钥认证**：推荐配置 SSH 密钥以实现免密推送，即使不启用多路复用也能避免每次输入密码
3. **远程权限**：确保 SSH 用户在远程服务器上有 `base_path` 目录的写入权限
4. **裸仓库**：远程创建的是 `git init --bare` 裸仓库，不包含工作区文件，仅作为推送目标

## 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| SSH 连接失败 | 端口/地址错误 | 检查 `.gitprivatetarget` 中的 SSH 地址 |
| 远程仓库创建失败 | 无目录写入权限 | `chmod` 或 `chown` 远程 `base_path` |
| 推送失败 | 远程仓库已有冲突内容 | `git push --force` 或手动解决 |
| 密码需多次输入 | OpenSSH < 5.6 或不支持多路复用 | 配置 SSH 密钥认证 |
| 提交失败 | user.name/email 未配置 | 工具会自动询问，也可手动 `git config --local user.name "xxx"` |

## 目录结构

```
PrivateGitPush/
├── privategitpush.py    # 主程序 (单文件，无外部依赖)
└── README.md            # 本文档
```

## 许可

本项目仅供个人使用。