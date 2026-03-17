import os
import tarfile
import tempfile
import time
from pathlib import Path

import paramiko
from pathspec import PathSpec

from libertai_client.agentkit.infra.scripts import (
    DEPLOY_CODE_SCRIPT,
    INSTALL_DOCKER_SCRIPT,
    START_AGENT_SCRIPT,
)

AGENT_ZIP_BLACKLIST = [".git/**", ".idea/**", ".vscode/**", "__pycache__/**", ".venv/**", "node_modules/**"]
AGENT_ZIP_WHITELIST = [".env", ".env.prod"]


def _resolve_private_key(ssh_pubkey_path: Path) -> str:
    pub = str(ssh_pubkey_path)
    if pub.endswith(".pub"):
        return pub[:-4]
    return pub


def _auto_detect_ssh_key() -> str:
    ssh_dir = Path.home() / ".ssh"
    for name in ["id_ed25519", "id_rsa", "id_ecdsa"]:
        path = ssh_dir / name
        if path.exists():
            return str(path)
    raise FileNotFoundError("No SSH private key found in ~/.ssh/")


def _run_script(client: paramiko.SSHClient, script: str, label: str) -> None:
    remote_path = f"/tmp/libertai-agentkit-{label}.sh"
    with client.open_sftp() as sftp:
        with sftp.file(remote_path, "w") as f:
            f.write(script)
    _stdin, stdout, stderr = client.exec_command(f"bash {remote_path}")
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        err = stderr.read().decode()
        raise RuntimeError(f"{label} failed (exit {exit_status}):\n{err}")


def wait_for_ssh(
    host: str, ssh_pubkey_path: Path | None = None, timeout: int = 300
) -> paramiko.SSHClient:
    import logging

    logging.getLogger("paramiko.transport").setLevel(logging.CRITICAL)
    if ssh_pubkey_path is not None:
        key_path = _resolve_private_key(ssh_pubkey_path)
    else:
        key_path = _auto_detect_ssh_key()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        per_attempt = min(30.0, remaining)
        try:
            client.connect(
                hostname=host,
                username="root",
                key_filename=key_path,
                timeout=per_attempt,
                banner_timeout=per_attempt,
                auth_timeout=per_attempt,
            )
            logging.getLogger("paramiko.transport").setLevel(logging.WARNING)
            return client
        except Exception as e:
            last_error = e
            time.sleep(10)
    logging.getLogger("paramiko.transport").setLevel(logging.WARNING)
    raise TimeoutError(
        f"SSH connection to {host} timed out after {timeout}s: {last_error}"
    )


def upload_agent(client: paramiko.SSHClient, agent_path: Path) -> None:
    gitignore_path = agent_path / ".gitignore"
    if gitignore_path.exists():
        patterns = gitignore_path.read_text().splitlines()
    else:
        patterns = []
    spec = PathSpec.from_lines("gitwildmatch", patterns + AGENT_ZIP_BLACKLIST)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        with tarfile.open(tmp_path, "w:gz") as tf:
            for root, _, files in os.walk(agent_path):
                for fname in files:
                    full = os.path.join(root, fname)
                    rel = os.path.relpath(full, agent_path)
                    if not spec.match_file(rel) or rel in AGENT_ZIP_WHITELIST:
                        tf.add(full, arcname=rel)
        sftp = client.open_sftp()
        sftp.put(tmp_path, "/tmp/libertai-agentkit.tar.gz")
        sftp.close()
    finally:
        os.unlink(tmp_path)


def deploy_code(client: paramiko.SSHClient) -> None:
    _run_script(client, DEPLOY_CODE_SCRIPT, "deploy-code")


def install_docker(client: paramiko.SSHClient) -> None:
    _run_script(client, INSTALL_DOCKER_SCRIPT, "install-docker")


def start_agent(client: paramiko.SSHClient) -> None:
    _run_script(client, START_AGENT_SCRIPT, "start-agent")


def verify_service(client: paramiko.SSHClient) -> bool:
    _stdin, stdout, _stderr = client.exec_command(
        "cd /opt/libertai-agentkit && docker compose ps --format json"
    )
    output = stdout.read().strip()
    stdout.channel.recv_exit_status()
    if not output:
        return False
    return b'"running"' in output
