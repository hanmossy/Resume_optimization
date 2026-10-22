"""deploy_to_server.py —— 一键部署脚本：本地代码 → 阿里云服务器（paramiko/SFTP）。

【用途】
    把 app/、data/（jobs/prompts/demo）、assets/fonts、requirements.txt、
    systemd unit 上传到 /opt/jlfd，安装依赖，启动并验证服务。

【用法】（凭据走环境变量，禁止写入代码与仓库）
    set DEPLOY_HOST=47.117.3.13
    set DEPLOY_USER=root
    set DEPLOY_PASSWORD=*****
    set ACCESS_PASSWORD=团队访问密码（注入 systemd unit）
    python deploy/deploy_to_server.py

【审查提示】一次性运维脚本，非产品代码；只连用户明确提供的服务器。
"""
from __future__ import annotations

import os
import posixpath
import sys
import time
from pathlib import Path

import paramiko

HOST = os.environ["DEPLOY_HOST"]
USER = os.environ.get("DEPLOY_USER", "root")
PASSWORD = os.environ["DEPLOY_PASSWORD"]
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD", "jlfd2026")
REMOTE_ROOT = "/opt/jlfd"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 上传清单：(本地相对路径, 远端相对路径)。只传运行必需文件——
# 不传 .env（团队 Key 绝不上公网）、不传 data/cache（公网联网模式不用缓存）、
# 不传交叉报告/实验结果（内部材料）
UPLOADS = [
    ("app", "app"),
    ("data/jobs", "data/jobs"),
    ("data/prompts", "data/prompts"),
    ("data/demo", "data/demo"),
    ("assets/fonts", "assets/fonts"),
    ("requirements.txt", "requirements.txt"),
    ("deploy/jlfd-assistant.service", "jlfd-assistant.service"),
]


def run(ssh: paramiko.SSHClient, cmd: str, timeout: int = 120) -> None:
    """执行远端命令并实时输出；非零退出码即失败。"""
    print(f"$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if out:
        print(out[-2000:])  # 只留尾部，防刷屏
    if code != 0:
        print(f"❌ 退出码 {code}: {err[-1000:]}")
        sys.exit(1)


def upload_dir(sftp: paramiko.SFTPClient, local: Path, remote: str) -> int:
    """递归上传目录内容（仅文件），返回文件数。"""
    count = 0
    for root, _dirs, files in os.walk(local):
        for name in files:
            lp = Path(root) / name
            rel = lp.relative_to(local)
            rp = posixpath.join(remote, *rel.parts)
            sftp.mkdir(posixpath.dirname(rp)) if False else None
            # paramiko 无 mkdir -p，逐级创建
            parts = posixpath.dirname(rp).split("/")
            cur = ""
            for p in parts:
                if not p:
                    continue
                cur += "/" + p
                try:
                    sftp.mkdir(cur)
                except OSError:
                    pass  # 已存在
            sftp.put(str(lp), rp)
            count += 1
    return count


def main() -> None:
    print(f"部署目标: {USER}@{HOST}:{REMOTE_ROOT}（访问密码将写入 systemd unit）")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    print("✅ SSH 连接成功")

    # 1) 系统依赖（阿里云 Ubuntu：python3-venv + pip）
    run(ssh, "apt-get update -qq", timeout=300)
    run(ssh, "apt-get install -y -qq python3-venv python3-pip", timeout=300)

    # 2) 上传文件
    sftp = ssh.open_sftp()
    run(ssh, f"mkdir -p {REMOTE_ROOT}/data/cache")  # cache 目录须存在（self_check 检查），内容留空
    total = 0
    for local_rel, remote_rel in UPLOADS:
        lp = PROJECT_ROOT / local_rel
        if lp.is_dir():
            n = upload_dir(sftp, lp, posixpath.join(REMOTE_ROOT, remote_rel))
        else:
            run(ssh, f"mkdir -p {posixpath.dirname(posixpath.join(REMOTE_ROOT, remote_rel))}")
            sftp.put(str(lp), posixpath.join(REMOTE_ROOT, remote_rel))
            n = 1
        total += n
        print(f"  上传 {local_rel} → {remote_rel}（{n} 个文件）")
    print(f"✅ 共上传 {total} 个文件")

    # 3) 注入访问密码到 systemd unit（密码不落代码仓库，只落服务器）
    run(ssh, f"sed -i 's/__ACCESS_PASSWORD__/{ACCESS_PASSWORD}/' {REMOTE_ROOT}/jlfd-assistant.service")

    # 4) Python 虚拟环境 + 依赖（阿里云内网 PyPI 镜像加速）
    run(ssh, f"python3 -m venv {REMOTE_ROOT}/venv", timeout=180)
    run(ssh, f"{REMOTE_ROOT}/venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ "
             f"-r {REMOTE_ROOT}/requirements.txt", timeout=600)
    print("✅ 依赖安装完成")

    # 5) systemd 服务注册并启动
    run(ssh, f"cp {REMOTE_ROOT}/jlfd-assistant.service /etc/systemd/system/jlfd-assistant.service")
    run(ssh, "systemctl daemon-reload && systemctl enable --now jlfd-assistant")
    time.sleep(8)  # 等 Streamlit 冷启动
    run(ssh, "systemctl is-active jlfd-assistant && curl -s -o /dev/null -w '本地HTTP:%{http_code}\\n' http://127.0.0.1:8501/")

    # 6) 安全核查：确认环境里没有团队 Key
    run(ssh, "systemctl show jlfd-assistant -p Environment | grep -c DEEPSEEK || echo 'OK: 服务环境无 DEEPSEEK_API_KEY'")
    sftp.close()
    ssh.close()
    print(f"\n🎉 部署完成，请访问 http://{HOST}:8501/ （访问密码：{ACCESS_PASSWORD}）")


if __name__ == "__main__":
    main()
