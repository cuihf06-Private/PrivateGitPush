#!/usr/bin/env python3
"""
PrivateGitPush - 将 git 仓库通过 SSH 推送到私有服务器

在任意目录运行此工具，它会:
1. 检测当前目录是否为 git 仓库，若否则初始化
2. 确保 git user.name/user.email 已配置 (交互询问)
3. 自动提交所有未提交的变更 (commit 格式: yymmdd_自动推送_更改x_新增y_删除z)
4. 读取 .gitprivatetarget 中的目标服务器配置
5. 在远程服务器检查/创建裸仓库 (git init --bare)
6. 配置 git remote 并推送

.gitprivatetarget 格式 (每行一个目标):
  user@host:port /path/to/repos/base/dir [repo_name]

示例:
  cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos
  cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos myproject
  cuihf@192.168.1.100:22 /home/user/repos another-repo
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
def run_cmd(cmd, check=True, capture=False, env=None, timeout=None):
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

    格式: user@host:port /path/to/repos/dir [repo_name]
    - repo_name 留空时运行时交互询问
    """
    targets = []
    with open(filepath, 'r') as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = line.split()
            if len(parts) < 2:
                cprint(C_RED, f"第 {lineno} 行格式错误: {line}")
                continue

            ssh_spec = parts[0]       # e.g. cuihf@tinybot.cloud:29798
            base_path = parts[1]      # e.g. /data1/cuihf/GitRepos
            repo_name = parts[2] if len(parts) >= 3 else None

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
                'user': user, 'host': host, 'port': port,
                'base_path': base_path, 'repo_name': repo_name,
                'ssh_spec': ssh_spec,
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


def set_default_push_config(branch_name):
    """
    设置当前分支的默认推送配置。
    
    - origin 作为默认拉取源 (第一个目标)
    - 自动配置 branch.<name>.remote 和 push
    """
    cprint(C_BLUE, "设置默认推送配置...")
    
    # 设置 origin 为默认拉取源
    git_cmd("config", "--local", f"branch.{branch_name}.remote", "origin")
    cprint(C_DIM, f"  origin 已设为默认拉取源")
    
    # 设置推送当前分支到 origin
    git_cmd("config", "--local", f"branch.{branch_name}.push", "HEAD")
    
    # 获取所有 remote (除 origin 外)
    r = git_cmd("remote", capture=True, check=False)
    if r.returncode == 0:
        remotes = [r.strip() for r in r.stdout.strip().split('\n') if r.strip() and r.strip() != 'origin']
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
    success_count = 0
    for i, target in enumerate(targets):
        repo_name = target['repo_name'] or ask_repo_name(target, dir_name)
        # 第一个目标命名为 origin，后续目标命名为 private-1, private-2...
        if i == 0:
            remote_name = "origin"
        else:
            remote_name = f"private-{i}"

        cprint(C_BOLD, f"── 目标 [{i+1}/{len(targets)}]: {target['ssh_spec']} ──")

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
    if success_count == len(targets):
        cprint(C_GREEN, f"✓ 全部 {success_count} 个目标推送完成")
    elif success_count > 0:
        cprint(C_YELLOW, f"⚠ {success_count}/{len(targets)} 个目标推送完成")
    else:
        cprint(C_RED, f"✗ 所有目标推送失败")
    
    # ── Step 6: 设置默认推送配置 ──
    if success_count > 0:
        branch = get_current_branch()
        if branch and branch != "HEAD":
            set_default_push_config(branch)
    
    print()


if __name__ == "__main__":
    main()

