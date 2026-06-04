#!/usr/bin/env python3
"""
PrivateGitPush - 将 git 仓库推送到私有服务器和 GitHub

在任意目录运行此工具，它会:
1. 检测当前目录是否为 git 仓库，若否初始化
2. 确保 git user.name/user.email 已配置 (交互询问)
3. 自动提交所有未提交的变更
4. 读取 .gitprivatetarget 中的目标配置
5. 处理目标: SSH 目标→创建裸仓库+推送, URL 目标→认证+创建+推送
6. 配置 git remote 并推送

.gitprivatetarget 格式 (每行一个目标):
  # 显式 remote 名 + SSH (推荐)
  origin user@host:port /path/to/repos/dir [repo_name]
  # 显式 remote 名 + URL (含 visibility)
  github https://github.com/user/repo [Private|Public]
  # SSH 格式 (原有)
  user@host:port /path/to/repos/dir [repo_name]

示例:
  origin https://github.com/cuihf06-Private/PrivateGitPush Public
  private1 cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
"""

import os
import sys
import subprocess
import re
import tempfile
import shutil
import time
from datetime import datetime

# ── ANSI 颜色 ──────────────────────────────────────────────
C_RED    = '\033[91m'
C_GREEN  = '\033[92m'
C_YELLOW = '\033[93m'
C_BLUE   = '\033[94m'
C_BOLD   = '\033[1m'
C_DIM    = '\033[2m'
C_RESET  = '\033[0m'


def cprint(color, msg, **kw):
    """带颜色的 print。"""
    print(f"{color}{msg}{C_RESET}", **kw)


# ── 通用命令执行 ───────────────────────────────────────────
def run_cmd(cmd, check=True, capture=False, env=None, timeout=None, input_data=None):
    """执行外部命令。"""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    kw = {'check': check, 'env': run_env}
    if capture:
        kw['capture_output'] = True
        kw['text'] = True
    if timeout:
        kw['timeout'] = timeout
    if input_data is not None:
        kw['input'] = input_data
        if not kw.get('text'):
            kw['text'] = True
    return subprocess.run(cmd, **kw)


def git_cmd(*args, capture=False, check=True, env=None):
    """执行 git 命令。"""
    return run_cmd(["git"] + list(args), capture=capture, check=check, env=env)


# ── Git 仓库操作 ───────────────────────────────────────────
def is_git_repo():
    """检测当前目录是否是 git 仓库。"""
    r = git_cmd("rev-parse", "--is-inside-work-tree", capture=True, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def init_git_repo():
    """在当前目录初始化 git 仓库。"""
    cprint(C_YELLOW, "当前目录不是 git 仓库，正在初始化...")
    r = git_cmd("init", check=False)
    if r.returncode == 0:
        cprint(C_GREEN, "✓ Git 仓库已初始化")
        return True
    cprint(C_RED, "✗ Git 初始化失败")
    return False


def has_commits():
    """检测仓库是否有提交记录。"""
    r = git_cmd("rev-parse", "HEAD", capture=True, check=False)
    return r.returncode == 0


def get_current_branch():
    """获取当前分支名。"""
    r = git_cmd("rev-parse", "--abbrev-ref", "HEAD", capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def get_branches():
    """获取所有本地分支。"""
    r = git_cmd("branch", "--format=%(refname:short)", capture=True, check=False)
    if r.returncode == 0:
        return [b.strip() for b in r.stdout.strip().split('\n') if b.strip()]
    return []


def has_uncommitted_changes():
    """检测是否有未提交的文件变更。"""
    r = git_cmd("status", "--porcelain", capture=True, check=False)
    return r.returncode == 0 and r.stdout.strip() != ''


def ensure_git_user_config():
    """确保 git user.name 和 user.email 已配置。
    优先检查全局+本地配置，若未设置则交互询问并写入本地配置。"""
    r = git_cmd("config", "user.name", capture=True, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        cprint(C_YELLOW, "未配置 git user.name")
        name = input("请输入用户名 (user.name): ").strip()
        if not name:
            cprint(C_RED, "✗ 未输入用户名，无法提交")
            return False
        git_cmd("config", "--local", "user.name", name)
        cprint(C_GREEN, f"✓ user.name 已设置: {name}")

    r = git_cmd("config", "user.email", capture=True, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        cprint(C_YELLOW, "未配置 git user.email")
        email = input("请输入邮箱 (user.email): ").strip()
        if not email:
            cprint(C_RED, "✗ 未输入邮箱，无法提交")
            return False
        git_cmd("config", "--local", "user.email", email)
        cprint(C_GREEN, f"✓ user.email 已设置: {email}")

    return True


def auto_commit():
    """自动添加并提交所有文件变更。

    commit 格式: yymmdd_自动推送_更改x_新增y_删除z
    - 更改: 已追踪且被修改的文件数
    - 新增: 新创建的文件数
    - 删除: 已追踪且被删除的文件数
    """
    # 添加所有文件到暂存区
    cprint(C_BLUE, "添加所有文件到暂存区...")
    git_cmd("add", ".", check=False)

    # 统计变更类型 (使用 cached diff，此时所有变更已暂存)
    r = git_cmd("diff", "--cached", "--name-status", capture=True, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        cprint(C_DIM, "  没有文件变更需要提交")
        return True

    modified = added = deleted = 0
    for line in r.stdout.strip().split('\n'):
        if not line.strip():
            continue
        status = line[0]
        if status in ('M', 'R'):      # M=修改, R=重命名 → 计为更改
            modified += 1
        elif status in ('A', 'C'):     # A=新增, C=复制 → 计为新增
            added += 1
        elif status == 'D':            # D=删除
            deleted += 1

    total = modified + added + deleted
    if total == 0:
        cprint(C_DIM, "  没有文件变更需要提交")
        return True

    # 生成 commit message
    date_str = datetime.now().strftime('%y%m%d')
    msg = f"{date_str}_自动推送_更改{modified}_新增{added}_删除{deleted}"

    cprint(C_BLUE, f"自动提交: {msg}")
    cprint(C_DIM, f"  ({modified} 更改, {added} 新增, {deleted} 删除)")

    r = git_cmd("commit", "-m", msg, check=False)
    if r.returncode != 0:
        cprint(C_RED, "✗ 提交失败")
        return False

    cprint(C_GREEN, f"✓ 已提交 {total} 个文件变更")
    return True


# ── SSH 多路复用 ───────────────────────────────────────────
def check_ssh_multiplexing_support():
    """检测本地 SSH 是否支持 ControlMaster/ControlPersist (OpenSSH >= 5.6)。"""
    r = run_cmd(["ssh", "-V"], check=False, capture=True)
    output = (r.stderr or '') + (r.stdout or '')
    m = re.search(r'OpenSSH_(\d+)\.(\d+)', output)
    if m:
        major, minor = int(m.group(1)), int(m.group(2))
        return (major, minor) >= (5, 6)
    return False


class SSHConnection:
    """SSH 连接管理器，支持 ControlMaster 多路复用以减少密码输入次数。"""

    def __init__(self, target):
        self.target = target
        self.use_mux = check_ssh_multiplexing_support()
        if self.use_mux:
            self.socket_dir = tempfile.mkdtemp(prefix="pgp_ssh_")
            self.socket_path = os.path.join(self.socket_dir, "ctrl")
            cprint(C_DIM, "  SSH 多路复用已启用 (同一目标只需输入一次密码)")
        else:
            self.socket_dir = None
            self.socket_path = None
            cprint(C_DIM, "  SSH 多路复用不可用 (每次操作需单独输入密码)")

    def _mux_options(self):
        """返回多路复用相关的 SSH 选项。"""
        if self.use_mux:
            return [
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={self.socket_path}",
                "-o", "ControlPersist=10m",
            ]
        return []

    def run_ssh(self, remote_cmd, check=True):
        """通过 SSH 执行远程命令 (支持交互密码输入)。"""
        cmd = ["ssh"] + self._mux_options() + \
              ["-p", self.target['port'],
               f"{self.target['user']}@{self.target['host']}",
               remote_cmd]
        return run_cmd(cmd, check=check)

    def git_ssh_env(self):
        """返回用于 git push 的 GIT_SSH_COMMAND 环境变量。"""
        if self.use_mux:
            opts = " ".join(self._mux_options())
            return {"GIT_SSH_COMMAND": f"ssh {opts}"}
        return {}

    def close(self):
        """关闭多路复用连接并清理临时文件。"""
        if self.use_mux and self.socket_path:
            cmd = ["ssh", "-S", self.socket_path, "-O", "exit",
                   "-p", self.target['port'],
                   f"{self.target['user']}@{self.target['host']}"]
            run_cmd(cmd, check=False, capture=True, timeout=5)
            shutil.rmtree(self.socket_dir, ignore_errors=True)


# ── 配置文件解析 ───────────────────────────────────────────
def parse_gitprivatetarget(filepath):
    """
    解析 .gitprivatetarget 文件。

    支持三种写法:
    1. 显式 remote 名: <remote_name> <ssh_spec> <base_path> [repo_name]
       交换行顺序不影响 remote 名映射。
    2. SSH 格式 (原有): user@host:port /path/to/repos/dir [repo_name]
       - repo_name 留空时运行时交互询问
    3. URL 格式: <remote_name> <url> 或 <url>
       仅配置 remote，不 SSH 创建裸仓库。

    检测规则: 第一个词不含 @ 且不以 URL 前缀开头 → 视为 remote 名
    """
    targets = []
    with open(filepath, 'r') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split()
            first_word = parts[0]

            # ── 检测第一列是否为显式 remote 名 ──
            is_name_prefix = (
                '@' not in first_word
                and not re.match(r'^https?://', first_word)
                and not re.match(r'^ssh://', first_word)
                and not re.match(r'^git@', first_word)
                and re.match(r'^[a-zA-Z][a-zA-Z0-9_.-]*$', first_word)
            )

            if is_name_prefix and len(parts) >= 2:
                explicit_name = first_word
                rest = parts[1:]
            else:
                explicit_name = None
                rest = parts

            # ── URL 格式 ──
            if rest and (
                re.match(r'^https?://', rest[0])
                or re.match(r'^ssh://', rest[0])
                or re.match(r'^git@', rest[0])
            ):
                url = rest[0]
                # 解析 visibility 列 (Private/Public), 默认 Private
                visibility = 'Private'
                if len(rest) >= 2 and rest[1] in ('Private', 'Public', 'private', 'public'):
                    visibility = rest[1].capitalize()
                targets.append({
                    'type': 'url',
                    'url': url,
                    'visibility': visibility,
                    'explicit_remote_name': explicit_name,
                })
                continue

            # ── SSH 格式 ──
            if len(rest) < 2:
                cprint(C_RED, f"第 {lineno} 行格式错误: {line}")
                continue

            ssh_spec = rest[0]       # e.g. cuihf@tinybot.cloud:29798
            base_path = rest[1]      # e.g. /data1/cuihf/GitRepos
            repo_name = rest[2] if len(rest) >= 3 else None

            # 解析 SSH 地址: user@host:port 或 user@host (默认端口22)
            m = re.match(r'^([^@]+)@([^:]+):(\d+)$', ssh_spec)
            if m:
                user, host, port = m.groups()
            else:
                m = re.match(r'^([^@]+)@(.+)$', ssh_spec)
                if m:
                    user, host = m.groups()
                    port = "22"
                else:
                    cprint(C_RED, f"第 {lineno} 行 SSH 地址格式错误: {ssh_spec}")
                    continue

            targets.append({
                'type': 'ssh',
                'user': user, 'host': host, 'port': port,
                'base_path': base_path, 'repo_name': repo_name,
                'ssh_spec': ssh_spec,
                'explicit_remote_name': explicit_name,
            })
    return targets


# ── 远程仓库管理 ───────────────────────────────────────────
def get_repo_path(target, repo_name):
    """远程裸仓库的完整路径。"""
    return f"{target['base_path']}/{repo_name}.git"


def get_remote_url(target, repo_name):
    """git remote URL (SSH 协议)。"""
    path = get_repo_path(target, repo_name)
    # 绝对路径以 / 开头，与 :port 后的 / 合并时只需保留一个
    if path.startswith('/'):
        return f"ssh://{target['user']}@{target['host']}:{target['port']}{path}"
    return f"ssh://{target['user']}@{target['host']}:{target['port']}/{path}"


def ensure_remote_repo(conn, target, repo_name):
    """
    确保远程裸仓库存在。
    在一条 SSH 命令中完成: 检测是否存在 → 不存在则创建。
    自动创建 base_path 目录 (如果不存在)。
    """
    path = get_repo_path(target, repo_name)
    remote_cmd = (
        f"if [ -d '{path}' ]; then "
        f"echo '✓ 仓库已存在: {path}'; "
        f"else "
        f"mkdir -p '{target['base_path']}' && "
        f"git init --bare '{path}' && "
        f"echo '✓ 仓库已创建: {path}'; "
        f"fi"
    )

    cprint(C_BLUE, f"检查/创建远程仓库: {target['ssh_spec']}:{path}")
    r = conn.run_ssh(remote_cmd, check=False)

    if r.returncode != 0:
        cprint(C_RED, "✗ SSH 连接或仓库操作失败")
        return False

    return True


# ── GitHub 仓库管理 ───────────────────────────────────────
def parse_github_url(url):
    """从 GitHub URL 中解析 owner 和 repo 名。

    支持: https://github.com/owner/repo, https://github.com/owner/repo.git
    返回: (owner, repo) 或 None
    """
    m = re.match(r'^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$', url)
    if m:
        return m.group(1), m.group(2)
    return None


def ensure_gh_auth():
    """确保 gh CLI 已认证。

    检查 gh auth status，若未认证则交互式要求用户提供 token。
    """
    cprint(C_BLUE, "检查 gh CLI 认证状态...")
    r = run_cmd(['gh', 'auth', 'status'], capture=True, check=False)
    if r.returncode == 0 and 'Logged in' in (r.stdout or '') + (r.stderr or ''):
        # 提取登录用户名
        output = (r.stderr or '') + (r.stdout or '')
        m = re.search(r'Logged in to github\.com as (\S+)', output)
        if m:
            cprint(C_GREEN, f"✓ gh 已认证: {m.group(1)}")
        else:
            cprint(C_GREEN, "✓ gh 已认证")
        return True

    cprint(C_YELLOW, "gh CLI 未认证，需要登录")
    cprint(C_DIM, "请提供 GitHub Personal Access Token (需要有 repo 权限)")
    cprint(C_DIM, "创建 Token: https://github.com/settings/tokens")

    # 交互式输入 token
    token = input("请输入 GitHub Token: ").strip()
    if not token:
        cprint(C_RED, "✗ 未提供 Token，无法操作 GitHub")
        return False

    # 用 token 登录
    cprint(C_BLUE, "正在登录 gh CLI...")
    r = run_cmd(['gh', 'auth', 'login', '--with-token'],
                capture=True, check=False,
                input_data=token)
    if r.returncode != 0:
        cprint(C_RED, "✗ gh 登录失败")
        cprint(C_DIM, f"  {r.stderr or r.stdout}")
        return False

    cprint(C_GREEN, "✓ gh CLI 登录成功")
    return True


def check_github_repo_exists(owner, repo):
    """检查 GitHub 仓库是否已存在。

    返回: True/False
    """
    r = run_cmd(['gh', 'repo', 'view', f'{owner}/{repo}',
                 '--json', 'name'],
                capture=True, check=False)
    return r.returncode == 0


def create_github_repo(owner, repo, visibility='Private'):
    """创建 GitHub 仓库。

    visibility: 'Private' 或 'Public'
    返回: True/False
    """
    vis_flag = '--private' if visibility == 'Private' else '--public'
    cprint(C_BLUE, f"创建 GitHub 仓库: {owner}/{repo} ({visibility})")

    # gh repo create <name> --private/--public
    # 不使用 --source/--push, 仅创建远程仓库, 推送由后续步骤处理
    # input_data='' 防止交互式提示阻塞
    r = run_cmd(['gh', 'repo', 'create', f'{owner}/{repo}',
                 vis_flag],
                capture=True, check=False,
                input_data='')
    if r.returncode != 0:
        cprint(C_RED, f"✗ 创建 GitHub 仓库失败")
        cprint(C_DIM, f"  {r.stderr or r.stdout}")
        return False

    cprint(C_GREEN, f"✓ GitHub 仓库已创建: {owner}/{repo}")
    return True


# ── Git Remote 配置 ────────────────────────────────────────
def setup_remote(name, url):
    """配置 git remote (添加或更新)。"""
    r = git_cmd("remote", "get-url", name, capture=True, check=False)

    if r.returncode == 0:
        existing = r.stdout.strip()
        if existing == url:
            cprint(C_DIM, f"  远程 '{name}' 已配置")
            return True
        cprint(C_YELLOW, f"更新远程 '{name}' → {url}")
        git_cmd("remote", "set-url", name, url)
        return True

    cprint(C_BLUE, f"添加远程 '{name}' → {url}")
    git_cmd("remote", "add", name, url)
    return True


def set_default_push_config(branch_name, pull_source_name='origin'):
    """
    设置当前分支的默认推送配置。

    - pull_source_name 作为默认拉取源 (第一行目标，无论 remote 名)
    - 自动配置 branch.<name>.remote 和 push
    """
    cprint(C_BLUE, "设置默认推送配置...")

    # 设置拉取源
    git_cmd("config", "--local", f"branch.{branch_name}.remote", pull_source_name)
    cprint(C_DIM, f"  {pull_source_name} 已设为默认拉取源")

    # 设置推送当前分支到拉取源
    git_cmd("config", "--local", f"branch.{branch_name}.push", "HEAD")

    # 获取所有 remote (除拉取源外)
    r = git_cmd("remote", capture=True, check=False)
    if r.returncode == 0:
        remotes = [r.strip() for r in r.stdout.strip().split('\n') if r.strip() and r.strip() != pull_source_name]
        if remotes:
            # 配置每个 remote 的 push refspec
            for remote in remotes:
                git_cmd("config", "--local", f"remote.{remote}.push", "+refs/heads/*:refs/heads/*")
            cprint(C_DIM, f"  已配置推送到 {len(remotes)} 个远程: {', '.join(remotes)}")

    cprint(C_GREEN, "✓ 推送配置完成")
    return True


# ── 推送 ────────────────────────────────────────────────────
def push_to_remote(name, env=None):
    """推送所有分支和标签到远程。"""
    if not has_commits():
        cprint(C_YELLOW, "仓库暂无提交记录，跳过推送")
        cprint(C_DIM, f"  提交后可运行: git push {name}")
        return True

    branches = get_branches()
    cprint(C_BLUE, f"推送 {len(branches)} 个分支到 '{name}'...")

    # 先推送所有分支
    r = git_cmd("push", name, "--all", check=False, env=env)
    if r.returncode != 0:
        # 全量推送失败时，尝试仅推送当前分支
        branch = get_current_branch()
        if branch and branch != "HEAD":
            cprint(C_YELLOW, f"全部推送失败，尝试推送当前分支 '{branch}'...")
            r = git_cmd("push", name, branch, check=False, env=env)
            if r.returncode != 0:
                cprint(C_RED, "✗ 推送失败")
                return False

    # 推送标签
    git_cmd("push", name, "--tags", check=False, env=env)

    cprint(C_GREEN, "✓ 推送完成")
    return True


# ── 交互式功能 ──────────────────────────────────────────────
def ask_repo_name(target, default):
    """交互询问仓库名。"""
    cprint(C_BOLD, f"\n目标: {target['ssh_spec']}")
    cprint(C_BOLD, f"路径: {target['base_path']}/")
    name = input(f"仓库名 (默认: {default}): ").strip()
    return name or default


def create_config_interactively(filepath):
    """交互式帮助用户创建 .gitprivatetarget 配置文件。"""
    cprint(C_YELLOW, "\n未找到配置文件 .gitprivatetarget")
    resp = input("是否创建? (Y/n): ").strip().lower()
    if resp == 'n':
        return False

    print()
    ssh = input("SSH 地址 (如 cuihf@tinybot.cloud:29798): ").strip()
    if not ssh:
        cprint(C_RED, "未输入 SSH 地址")
        return False

    path = input("仓库基础路径 (如 /data1/cuihf/GitRepos): ").strip()
    if not path:
        cprint(C_RED, "未输入路径")
        return False

    name = input("仓库名 (留空则每次运行时询问): ").strip()

    with open(filepath, 'w') as f:
        f.write("# PrivateGitPush targets\n")
        f.write("# 格式: user@host:port /path/to/repos/dir [repo_name]\n")
        line = f"{ssh} {path}"
        if name:
            line += f" {name}"
        f.write(line + "\n")

    cprint(C_GREEN, f"✓ 已创建: {filepath}")
    return True


# ── 主流程 ──────────────────────────────────────────────────
def main():
    # 确定工作目录
    if len(sys.argv) > 1:
        work_dir = os.path.abspath(sys.argv[1])
        if not os.path.isdir(work_dir):
            cprint(C_RED, f"目录不存在: {work_dir}")
            sys.exit(1)
    else:
        work_dir = os.getcwd()

    os.chdir(work_dir)
    dir_name = os.path.basename(work_dir)

    cprint(C_BOLD, "\n╔════════════════════════════╗")
    cprint(C_BOLD, "║      PrivateGitPush       ║")
    cprint(C_BOLD, "╚════════════════════════════╝")
    cprint(C_BOLD, f"工作目录: {work_dir}\n")

    # ── Step 1: 检测/初始化 git 仓库 ──
    if not is_git_repo():
        if not init_git_repo():
            sys.exit(1)

    # ── Step 2: 确保 git 用户配置 ──
    if not ensure_git_user_config():
        sys.exit(1)

    # ── Step 3: 自动提交未提交的变更 ──
    needs_commit = not has_commits() or has_uncommitted_changes()
    if needs_commit:
        if not has_commits():
            cprint(C_YELLOW, "仓库暂无提交记录，将自动提交所有文件")
        else:
            cprint(C_YELLOW, "存在未提交的变更，将自动提交")
        if not auto_commit():
            cprint(C_RED, "✗ 自动提交失败，无法继续推送")
            sys.exit(1)

    # ── Step 4: 查找/创建配置文件 ──
    config = os.path.join(work_dir, ".gitprivatetarget")
    if not os.path.exists(config):
        if not create_config_interactively(config):
            print(f"\n请手动创建 .gitprivatetarget，格式:")
            print(f"  user@host:port /path/to/repos/dir [repo_name]")
            print(f"  示例:")
            print(f"    cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos")
            sys.exit(1)

    targets = parse_gitprivatetarget(config)
    if not targets:
        cprint(C_RED, "配置文件中无有效目标")
        sys.exit(1)

    cprint(C_GREEN, f"找到 {len(targets)} 个推送目标\n")

    # ── Step 5: 处理每个目标 ──
    # 分配 remote 名称
    private_counter = 1
    named_targets = []
    for i, target in enumerate(targets):
        if target.get('explicit_remote_name'):
            remote_name = target['explicit_remote_name']
        elif i == 0:
            remote_name = 'origin'
        else:
            remote_name = f'private-{private_counter}'
            private_counter += 1
        named_targets.append((remote_name, target))

    # 分离 SSH 和 URL 目标
    ssh_named = [(n, t) for n, t in named_targets if t.get('type') != 'url']
    url_named = [(n, t) for n, t in named_targets if t.get('type') == 'url']

    # 处理 URL 目标: 认证 + 创建仓库 + 配置 remote + 推送
    url_success_count = 0
    if url_named:
        cprint(C_BOLD, "\n── URL 目标处理 ──")
        for remote_name, target in url_named:
            url = target['url']
            visibility = target.get('visibility', 'Private')
            cprint(C_BOLD, f"\n[{remote_name}] {url} ({visibility})")

            # 判断是否为 GitHub URL
            gh_info = parse_github_url(url)
            if gh_info:
                owner, repo = gh_info
                cprint(C_DIM, f"  GitHub: {owner}/{repo}")

                # Step A: 确保 gh 已认证
                if not ensure_gh_auth():
                    cprint(C_RED, "✗ GitHub 认证失败，跳过此目标")
                    setup_remote(remote_name, url)
                    cprint(C_DIM, f"  需手动推送: git push {remote_name}")
                    continue

                # Step B: 检查仓库是否存在，不存在则创建
                if check_github_repo_exists(owner, repo):
                    cprint(C_GREEN, f"✓ GitHub 仓库已存在: {owner}/{repo}")
                else:
                    cprint(C_YELLOW, f"GitHub 仓库不存在: {owner}/{repo}")
                    if not create_github_repo(owner, repo, visibility):
                        cprint(C_RED, "✗ 仓库创建失败，跳过此目标")
                        setup_remote(remote_name, url)
                        cprint(C_DIM, f"  需手动推送: git push {remote_name}")
                        continue
            else:
                cprint(C_DIM, f"  非 GitHub URL，仅配置 remote")

            # Step C: 配置 git remote
            setup_remote(remote_name, url)

            # Step D: 推送
            if push_to_remote(remote_name):
                url_success_count += 1
            else:
                cprint(C_YELLOW, f"⚠ 推送到 {remote_name} 失败，可能需手动推送")

    # 处理 SSH 目标: 完整推送流程
    success_count = 0
    for idx, (remote_name, target) in enumerate(ssh_named):
        repo_name = target['repo_name'] or ask_repo_name(target, dir_name)

        cprint(C_BOLD, f"\n── SSH 目标 [{idx+1}/{len(ssh_named)}]: {target['ssh_spec']} ──")

        conn = SSHConnection(target)
        try:
            # 确保远程裸仓库存在
            if not ensure_remote_repo(conn, target, repo_name):
                cprint(C_RED, "跳过此目标\n")
                continue

            # 配置 git remote
            url = get_remote_url(target, repo_name)
            setup_remote(remote_name, url)

            # 推送
            push_to_remote(remote_name, env=conn.git_ssh_env())
            success_count += 1
        finally:
            conn.close()

    # ── 总结 ──
    cprint(C_BOLD, f"\n══════════════════════════")
    ssh_total = len(ssh_named)
    if success_count == ssh_total:
        cprint(C_GREEN, f"✓ 全部 {success_count} 个 SSH 目标推送完成")
    elif success_count > 0:
        cprint(C_YELLOW, f"⚠ {success_count}/{ssh_total} 个 SSH 目标推送完成")
    else:
        cprint(C_RED, f"✗ 所有 SSH 目标推送失败")
    if url_named:
        url_total = len(url_named)
        if url_success_count == url_total:
            cprint(C_GREEN, f"✓ 全部 {url_success_count} 个 URL 目标推送完成")
        elif url_success_count > 0:
            cprint(C_YELLOW, f"⚠ {url_success_count}/{url_total} 个 URL 目标推送完成")
        else:
            cprint(C_DIM, f"  {url_total} 个 URL 目标需手动推送")
    
    # ── Step 6: 设置默认推送配置 ──
    # 拉取源始终为第一行 (无论 remote 名)
    pull_source_name = named_targets[0][0] if named_targets else 'origin'
    if success_count > 0:
        branch = get_current_branch()
        if branch and branch != "HEAD":
            set_default_push_config(branch, pull_source_name)
    
    print()


if __name__ == "__main__":
    main()

