#!/usr/bin/env python3
"""
SyncRemotes - 基于 .gitprivatetarget 同步 git 推送目标配置

读取工作目录下的 .gitprivatetarget 文件，将推送目标同步到 git local config。
名为 origin 的 remote 为云端拉取源 (git pull 目标)，其余为推送备份目标。

.gitprivatetarget 支持三种写法:
1. 显式 remote 名格式 (推荐): <remote_name> <url_or_ssh_spec> [params]
   → origin cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
   → github https://github.com/user/repo
   交换行顺序不影响映射，remote 名与位置无关。
2. SSH 格式 (原有): user@host:port /path/to/repos/dir [repo_name]
   → cuihf@tinybot.cloud:29798 /data1/cuihf/GitRepos PrivateGitPush
   第一行 = origin，其余 = private-N (按位置分配)。
3. 直接 URL 格式: 完整的 git remote URL
   → https://github.com/user/repo
   → git@github.com:user/repo.git

使用方法:
  python3 syncremotes.py                  # 在当前 git 仓库目录运行
  python3 syncremotes.py /path/to/repo    # 在指定目录运行
"""

import os
import sys
import subprocess
import re

# ── ANSI 颜色 ──────────────────────────────────────────────
C_RED    = '\033[91m'
C_GREEN  = '\033[92m'
C_YELLOW = '\033[93m'
C_BLUE   = '\033[94m'
C_BOLD   = '\033[1m'
C_DIM    = '\033[2m'
C_CYAN   = '\033[96m'
C_RESET  = '\033[0m'


def cprint(color, msg, **kw):
    """带颜色的 print。"""
    print(f"{color}{msg}{C_RESET}", **kw)


# ── 命令执行 ───────────────────────────────────────────────
def run_cmd(cmd, check=True, capture=False):
    """执行外部命令。"""
    kw = {'check': check}
    if capture:
        kw['capture_output'] = True
        kw['text'] = True
    return subprocess.run(cmd, **kw)


def git_cmd(*args, capture=False, check=True):
    """执行 git 命令。"""
    return run_cmd(["git"] + list(args), capture=capture, check=check)


# ── Git 仓库检测 ───────────────────────────────────────────
def is_git_repo():
    """检测当前目录是否是 git 仓库。"""
    r = git_cmd("rev-parse", "--is-inside-work-tree", capture=True, check=False)
    return r.returncode == 0 and r.stdout.strip() == "true"


def get_current_branch():
    """获取当前分支名。"""
    r = git_cmd("rev-parse", "--abbrev-ref", "HEAD", capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def get_all_branches():
    """获取所有本地分支。"""
    r = git_cmd("branch", "--format=%(refname:short)", capture=True, check=False)
    if r.returncode == 0:
        return [b.strip() for b in r.stdout.strip().split('\n') if b.strip()]
    return []


def get_remote_names():
    """获取当前所有 remote 名称列表。"""
    r = git_cmd("remote", capture=True, check=False)
    if r.returncode == 0:
        return [name.strip() for name in r.stdout.strip().split('\n') if name.strip()]
    return []


def get_remote_url(name):
    """获取指定 remote 的 URL。"""
    r = git_cmd("remote", "get-url", name, capture=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


# ── 配置文件解析 ───────────────────────────────────────────
def parse_gitprivatetarget(filepath, default_repo_name=None):
    """
    解析 .gitprivatetarget 文件。

    支持三种写法:
    1. 显式 remote 名 (新格式): <remote_name> <url_or_ssh_spec> [params]
       第一列为 remote 名，不含 @ 且不以 URL 前缀开头。
       交换行顺序不影响 remote 名映射。
    2. SSH 格式 (旧格式): user@host:port /path/to/repos/dir [repo_name]
       第一行 = origin，其余按位置分配 remote 名。
    3. 直接 URL: https://... | git@...:... | ssh://...

    检测规则: 第一个词不含 @ 且不以 URL 前缀开头 → 视为 remote 名 (新格式)
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
            # remote 名: 纯标识符 (不含 @, 不以 URL 前缀开头)
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

            # ── 直接 URL 格式 ──
            if rest and (
                re.match(r'^https?://', rest[0])
                or re.match(r'^ssh://', rest[0])
                or re.match(r'^git@', rest[0])
            ):
                url = rest[0]
                targets.append({
                    'type': 'url',
                    'url': url,
                    'explicit_remote_name': explicit_name,
                })
                continue

            # ── SSH 格式 ──
            if len(rest) < 2:
                cprint(C_RED, f"✗ 第 {lineno} 行格式错误: {line}")
                continue

            ssh_spec = rest[0]       # e.g. cuihf@tinybot.cloud:29798
            base_path = rest[1]      # e.g. /data1/cuihf/GitRepos
            repo_name = rest[2] if len(rest) >= 3 else default_repo_name

            if not repo_name:
                cprint(C_YELLOW, f"⚠ 第 {lineno} 行未指定仓库名，使用目录名: {default_repo_name}")
                repo_name = default_repo_name

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
                    cprint(C_RED, f"✗ 第 {lineno} 行 SSH 地址格式错误: {ssh_spec}")
                    continue

            # 构造 git remote URL
            repo_path = f"{base_path}/{repo_name}.git"
            if repo_path.startswith('/'):
                url = f"ssh://{user}@{host}:{port}{repo_path}"
            else:
                url = f"ssh://{user}@{host}:{port}/{repo_path}"

            targets.append({
                'type': 'ssh',
                'user': user, 'host': host, 'port': port,
                'base_path': base_path, 'repo_name': repo_name,
                'ssh_spec': ssh_spec,
                'url': url,
                'explicit_remote_name': explicit_name,
            })

    return targets


def assign_remote_names(targets):
    """
    为每个目标分配 remote 名称。

    规则:
    - 有 explicit_remote_name → 使用指定名称 (与位置无关)
    - 无 explicit_remote_name → 按位置分配:
      第一个 → 'origin' (云端拉取源)
      其余 → 'private-N'
    """
    named = []
    private_counter = 1
    for i, target in enumerate(targets):
        if target.get('explicit_remote_name'):
            name = target['explicit_remote_name']
        elif i == 0:
            name = 'origin'
        else:
            name = f'private-{private_counter}'
            private_counter += 1
        named.append((name, target))
    return named


# ── Remote 同步 ────────────────────────────────────────────
def sync_remote(name, desired_url):
    """添加或更新 git remote，返回变更类型。"""
    existing_url = get_remote_url(name)

    if existing_url is not None:
        if existing_url == desired_url:
            cprint(C_DIM, f"  ✓ '{name}' 已配置: {desired_url}")
            return 'unchanged'
        cprint(C_YELLOW, f"  ↻ 更新 '{name}': {existing_url} → {desired_url}")
        git_cmd("remote", "set-url", name, desired_url)
        return 'updated'

    cprint(C_BLUE, f"  + 添加 '{name}': {desired_url}")
    git_cmd("remote", "add", name, desired_url)
    return 'added'


def remove_remote(name):
    """删除 git remote。"""
    url = get_remote_url(name)
    cprint(C_YELLOW, f"  - 删除 '{name}': {url}")
    git_cmd("remote", "remove", name)


# ── 分支配置 ───────────────────────────────────────────────
def sync_branch_config(branch_name, pull_source_name='origin'):
    """
    设置分支的默认拉取源和推送配置。

    - branch.<name>.remote = pull_source_name (拉取源为第一行目标，无论 remote 名)
    - branch.<name>.push = HEAD (推送到拉取源当前分支)
    """
    if not branch_name or branch_name == 'HEAD':
        cprint(C_DIM, "  (暂无有效分支，跳过分支配置)")
        return

    # 拉取源
    r = git_cmd("config", "--local", f"branch.{branch_name}.remote", capture=True, check=False)
    current = r.stdout.strip() if r.returncode == 0 else None
    if current != pull_source_name:
        git_cmd("config", "--local", f"branch.{branch_name}.remote", pull_source_name)
        cprint(C_DIM, f"  ✓ branch.{branch_name}.remote = {pull_source_name}")
    else:
        cprint(C_DIM, f"  ✓ branch.{branch_name}.remote 已为 {pull_source_name}")

    # 推送配置
    r = git_cmd("config", "--local", f"branch.{branch_name}.push", capture=True, check=False)
    current_push = r.stdout.strip() if r.returncode == 0 else None
    if current_push != 'HEAD':
        git_cmd("config", "--local", f"branch.{branch_name}.push", "HEAD")
        cprint(C_DIM, f"  ✓ branch.{branch_name}.push = HEAD")


def sync_all_branches_config(pull_source_name='origin'):
    """为所有本地分支设置拉取源。"""
    branches = get_all_branches()
    for b in branches:
        r = git_cmd("config", "--local", f"branch.{b}.remote", capture=True, check=False)
        current = r.stdout.strip() if r.returncode == 0 else None
        if current != pull_source_name:
            git_cmd("config", "--local", f"branch.{b}.remote", pull_source_name)
            cprint(C_DIM, f"  ✓ branch.{b}.remote = {pull_source_name}")


# ── 推送配置 ───────────────────────────────────────────────
def sync_push_config(remote_names):
    """
    为非拉取源的推送目标配置 push refspec。

    拉取源的推送通过 branch.<name>.push = HEAD 控制。
    其他 remote 配置 push all branches，确保所有分支同步推送。
    """
    for name in remote_names:
        r = git_cmd("config", "--local", f"remote.{name}.push", capture=True, check=False)
        current = r.stdout.strip() if r.returncode == 0 else None
        desired = "+refs/heads/*:refs/heads/*"
        if current != desired:
            git_cmd("config", "--local", f"remote.{name}.push", desired)
            cprint(C_DIM, f"  ✓ remote.{name}.push = {desired}")
        else:
            cprint(C_DIM, f"  ✓ remote.{name}.push 已配置")


# ── 主流程 ──────────────────────────────────────────────────
def main():
    # 确定工作目录
    if len(sys.argv) > 1:
        work_dir = os.path.abspath(sys.argv[1])
        if not os.path.isdir(work_dir):
            cprint(C_RED, f"✗ 目录不存在: {work_dir}")
            sys.exit(1)
    else:
        work_dir = os.getcwd()

    os.chdir(work_dir)
    dir_name = os.path.basename(work_dir)

    cprint(C_BOLD, "\n╔════════════════════════════╗")
    cprint(C_BOLD, "║       SyncRemotes          ║")
    cprint(C_BOLD, "╚════════════════════════════╝")
    cprint(C_BOLD, f"工作目录: {work_dir}\n")

    # ── Step 1: 检测 git 仓库 ──
    if not is_git_repo():
        cprint(C_RED, "✗ 当前目录不是 git 仓库")
        cprint(C_DIM, "请先运行: git init")
        sys.exit(1)

    # ── Step 2: 查找配置文件 ──
    config_path = os.path.join(work_dir, ".gitprivatetarget")
    if not os.path.exists(config_path):
        cprint(C_RED, "✗ 未找到配置文件: .gitprivatetarget")
        cprint(C_DIM, "请创建 .gitprivatetarget，支持以下格式:")
        cprint(C_DIM, "  # 显式 remote 名 (推荐，与位置无关)")
        cprint(C_DIM, "  origin user@host:port /path/to/repos/dir [repo_name]")
        cprint(C_DIM, "  github https://github.com/user/repo")
        cprint(C_DIM, "  # SSH 格式 (原有，按位置分配)")
        cprint(C_DIM, "  user@host:port /path/to/repos/dir [repo_name]")
        cprint(C_DIM, "  # 直接 URL 格式")
        cprint(C_DIM, "  https://github.com/user/repo")
        cprint(C_DIM, "  git@github.com:user/repo.git")
        sys.exit(1)

    # ── Step 3: 解析配置 ──
    targets = parse_gitprivatetarget(config_path, default_repo_name=dir_name)
    if not targets:
        cprint(C_RED, "✗ 配置文件中无有效目标")
        sys.exit(1)

    named_targets = assign_remote_names(targets)

    cprint(C_GREEN, f"找到 {len(targets)} 个目标:\n")
    for i, (name, target) in enumerate(named_targets):
        url = target['url']
        tag = "(拉取源)" if i == 0 else ""
        cprint(C_CYAN, f"  {name} → {url} {tag}")

    # ── Step 4: 获取当前 remotes ──
    current_remotes = get_remote_names()
    cprint(C_DIM, f"\n当前 remotes: {', '.join(current_remotes) or '无'}")

    # ── Step 5: 同步 remotes ──
    cprint(C_BOLD, "\n── 同步远程配置 ──")

    desired_names = {}
    changes = {'added': 0, 'updated': 0, 'unchanged': 0, 'removed': 0}

    for name, target in named_targets:
        url = target['url']
        result = sync_remote(name, url)
        changes[result] += 1
        desired_names[name] = url

    # 清理不再需要的 private-* remotes
    for existing_name in current_remotes:
        if existing_name not in desired_names and re.match(r'^private-\d+$', existing_name):
            remove_remote(existing_name)
            changes['removed'] += 1

    # ── Step 6: 设置分支配置 ──
    # 拉取源始终为第一行 (无论 remote 名是什么)
    pull_source_name = named_targets[0][0]
    cprint(C_BOLD, "\n── 设置分支配置 ──")
    cprint(C_DIM, f"  拉取源: {pull_source_name} (第一行)")

    branch = get_current_branch()
    if branch and branch != 'HEAD':
        sync_branch_config(branch, pull_source_name)

    # 为所有分支设置拉取源
    sync_all_branches_config(pull_source_name)

    # ── Step 7: 设置推送配置 ──
    push_names = [name for name, _ in named_targets if name != pull_source_name]
    if push_names:
        cprint(C_BOLD, "\n── 设置推送配置 ──")
        sync_push_config(push_names)

    # ── 总结 ──
    cprint(C_BOLD, "\n══════════════════════════")
    total_changes = changes['added'] + changes['updated'] + changes['removed']
    if total_changes == 0:
        cprint(C_GREEN, "✓ 所有远程配置已同步，无需更改")
    else:
        summary_parts = []
        if changes['added']:
            summary_parts.append(f"+{changes['added']}")
        if changes['updated']:
            summary_parts.append(f"↻{changes['updated']}")
        if changes['removed']:
            summary_parts.append(f"-{changes['removed']}")
        cprint(C_GREEN, f"✓ 同步完成: {' '.join(summary_parts)}")

    cprint(C_DIM, "\n当前远程配置:")
    r = git_cmd("remote", "-v", capture=True, check=False)
    if r.returncode == 0:
        for line in r.stdout.strip().split('\n'):
            cprint(C_DIM, f"  {line}")

    print()


if __name__ == "__main__":
    main()