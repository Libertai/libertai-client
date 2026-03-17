import asyncio
import os
from pathlib import Path

import paramiko
import typer
from dotenv import dotenv_values
from libertai_x402 import create_payment_client
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel

from libertai_client.agentkit.chain.balance import get_usdc_balance, wait_for_usdc_funding
from libertai_client.agentkit.chain.wallet import generate_wallet, load_existing_wallet
from libertai_client.agentkit.infra.aleph import (
    DEFAULT_CRN,
    buy_credits,
    check_existing_resources,
    create_instance,
    delete_existing_resources,
    get_aleph_account,
    get_credit_balance,
    get_user_ssh_pubkey,
    notify_allocation,
    wait_for_instance,
)
from libertai_client.agentkit.infra.ssh import (
    deploy_code,
    install_docker,
    start_agent,
    upload_agent,
    verify_service,
    wait_for_ssh,
)
from libertai_client.agentkit.ui import _fail, _run_step
from libertai_client.utils.typer import AsyncTyper, validate_optional_file_path_argument

app: AsyncTyper = AsyncTyper(name="agentkit", help="Deploy and manage AgentKit agents on Aleph Cloud")

console = Console()

MIN_USDC_FUNDING = 1.0


@app.command()
async def deploy(
    path: Path = typer.Argument(
        None,
        help="Path to agent directory (default: current working directory)",
    ),
    ssh_pubkey_path: Path = typer.Option(
        None,
        "--ssh-key",
        help="Path to SSH public key file (default: auto-detect from ~/.ssh/)",
        callback=validate_optional_file_path_argument,
    ),
    credits_amount: float = typer.Option(
        1.0,
        "--credits",
        help="Amount in USD to spend on Aleph credits",
    ),
    register_only: bool = typer.Option(
        False,
        "--register-only",
        help="Only create the Aleph instance, skip SSH deployment",
    ),
) -> None:
    """Deploy an AgentKit agent to Aleph Cloud with credit-based payment."""
    if path is None:
        path = Path.cwd()
    path = path.resolve()
    env_path = path / ".env.prod"

    if not register_only:
        compose_file = path / "docker-compose.yml"
        if not compose_file.exists():
            compose_file = path / "docker-compose.yaml"
        if not compose_file.exists():
            rprint(
                "[red]No docker-compose.yml found in agent directory. "
                "A docker-compose.yml is required for deployment.[/red]"
            )
            raise typer.Exit(1)

    console.rule("[bold blue]LibertAI AgentKit Deployment")
    rprint()

    step = 0
    ssh_client: paramiko.SSHClient | None = None

    try:
        # Step 1: Wallet setup
        step += 1
        rprint(f"[bold]Step {step}:[/bold] Setting up Base wallet...")
        try:
            existing = load_existing_wallet(path)
            if existing:
                address, private_key = existing
                rprint(f"  [green]Using existing wallet:[/green] {address}")
                env_vars = None
            else:
                address, private_key = generate_wallet()
                rprint(f"  [green]Wallet generated:[/green] {address}")
                env_vars = {"WALLET_PRIVATE_KEY": private_key}
        except Exception as e:
            _fail("Setting up Base wallet", e)
        rprint()

        # Step 2: Write .env.prod (only if new wallet)
        if env_vars is not None:
            step += 1
            rprint(f"[bold]Step {step}:[/bold] Configuring agent environment...")
            try:
                existing_env: dict[str, str | None] = {}
                if env_path.exists():
                    existing_env = dict(dotenv_values(env_path))
                existing_env.update(env_vars)
                env_content = (
                    "\n".join(f"{k}={v}" for k, v in existing_env.items() if v) + "\n"
                )
                os.makedirs(path, exist_ok=True)
                fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(env_content)
                rprint(
                    f"  [green]Saved to {env_path}[/green] "
                    "[yellow](contains wallet private key — keep secure)[/yellow]"
                )
            except Exception as e:
                _fail("Configuring agent environment", e)
            rprint()

        # Step 3: Check existing Aleph resources
        account = get_aleph_account(private_key)
        crn = DEFAULT_CRN

        resources = await _run_step(
            "Checking for existing Aleph resources",
            fn=lambda: check_existing_resources(account),
        )

        if resources.has_any:
            rprint(f"  [yellow]Found existing resources: {resources.summary}[/yellow]")
            delete = typer.confirm(
                "  Delete existing resources and proceed?", default=True
            )
            if not delete:
                rprint(
                    "  [red]Cannot proceed with existing resources. Use a different wallet.[/red]"
                )
                raise typer.Exit(1)
            await _run_step(
                "Deleting existing resources",
                fn=lambda: delete_existing_resources(account, resources),
            )
        rprint()

        # Step 4: Check USDC balance
        usdc_balance = get_usdc_balance(address)

        if usdc_balance < MIN_USDC_FUNDING:
            step += 1
            rprint(f"[bold]Step {step}:[/bold] Fund your agent wallet")
            rprint()
            rprint(
                Panel(
                    f"[bold]Send USDC (Base) to:[/bold]\n\n"
                    f"  [cyan]{address}[/cyan]\n\n"
                    f"This USDC will be used to buy Aleph Cloud credits.\n\n"
                    f"[dim]Minimum required: {MIN_USDC_FUNDING} USDC[/dim]",
                    title="[bold yellow]Fund Agent Wallet[/bold yellow]",
                    border_style="yellow",
                )
            )
            rprint()
            usdc_balance = await asyncio.to_thread(
                wait_for_usdc_funding, address, MIN_USDC_FUNDING
            )
            rprint(f"  [green]Received {usdc_balance:.2f} USDC[/green]")
        else:
            rprint(f"  [dim]USDC balance: {usdc_balance:.2f} — sufficient[/dim]")
        rprint()

        # Step 5: Check / buy Aleph credits
        step += 1
        rprint(f"[bold]Step {step}:[/bold] Aleph credits...")
        rprint()

        try:
            balance_usd = await get_credit_balance(address)
            rprint(f"  [dim]Current balance: ${balance_usd:.2f}[/dim]")
        except Exception:
            balance_usd = 0.0
            rprint("  [dim]Could not fetch credit balance, will purchase[/dim]")

        if balance_usd < credits_amount:
            payment_client = create_payment_client(private_key)
            result = await _run_step(
                f"Buying ${credits_amount:.2f} of Aleph credits",
                fn=lambda: buy_credits(payment_client, address, credits_amount),
            )
            rprint(f"  [dim]Credits purchased: {result}[/dim]")
        else:
            rprint(f"  [dim]Balance ${balance_usd:.2f} — sufficient, skipping purchase[/dim]")
        rprint()

        # Step 6: Create Aleph Cloud instance
        step += 1
        rprint(f"[bold]Step {step}:[/bold] Creating Aleph Cloud instance...")
        rprint()

        if ssh_pubkey_path is not None:
            ssh_pubkey = ssh_pubkey_path.expanduser().read_text().strip()
        else:
            ssh_pubkey = get_user_ssh_pubkey()

        if not ssh_pubkey:
            _fail(
                "Resolving SSH public key",
                RuntimeError(
                    "No SSH public key found. Use --ssh-key or generate one (e.g. ssh-keygen)"
                ),
            )

        instance_msg = await _run_step(
            "Creating Aleph instance",
            fn=lambda: create_instance(account, crn, ssh_pubkey=ssh_pubkey),
        )
        instance_hash = instance_msg.item_hash
        explorer_url = f"https://explorer.aleph.cloud/address/ETH/{address}/message/INSTANCE/{instance_hash}"
        rprint(
            f"  [dim]Instance: [link={explorer_url}]{instance_hash}[/link][/dim]"
        )

        await _run_step(
            "Notifying CRN for allocation",
            fn=lambda: notify_allocation(crn, instance_hash),
        )

        instance_ip = await _run_step(
            "Waiting for instance to come up",
            fn=lambda: wait_for_instance(crn, instance_hash),
        )
        rprint(f"  [dim]Instance IP: {instance_ip}[/dim]")

        if register_only:
            rprint()
            console.rule("[bold green]Instance Registered")
            rprint()
            rprint(
                Panel(
                    f"[bold]Agent Address:[/bold]    [cyan]{address}[/cyan]\n"
                    f"[bold]Instance IP:[/bold]      {instance_ip}\n"
                    f"[bold]Instance Hash:[/bold]    {instance_hash}\n"
                    f"[bold]Network:[/bold]          Base Mainnet\n"
                    f"\n"
                    f"[dim]Use 'libertai agentkit deploy' without --register-only to also deploy code.[/dim]",
                    title="[bold green]LibertAI AgentKit Instance[/bold green]",
                    border_style="green",
                )
            )
            return

        # Step 7: Deploy agent code via SSH
        step += 1
        rprint()
        rprint(f"[bold]Step {step}:[/bold] Deploying agent code...")
        rprint()

        ssh_key_path = ssh_pubkey_path if ssh_pubkey_path is not None else None
        ssh_client = await _run_step(
            "Waiting for SSH",
            fn=lambda: asyncio.to_thread(wait_for_ssh, instance_ip, ssh_key_path),
        )
        assert ssh_client is not None
        client = ssh_client

        await _run_step(
            "Uploading agent code",
            fn=lambda: asyncio.to_thread(upload_agent, client, path),
        )
        await _run_step(
            "Deploying agent code",
            fn=lambda: asyncio.to_thread(deploy_code, client),
        )
        await _run_step(
            "Installing Docker",
            fn=lambda: asyncio.to_thread(install_docker, client),
        )
        await _run_step(
            "Starting agent",
            fn=lambda: asyncio.to_thread(start_agent, client),
        )

        is_active = await _run_step(
            "Verifying agent is running",
            fn=lambda: asyncio.to_thread(verify_service, client),
        )
        if not is_active:
            _fail(
                "Verifying agent is running",
                RuntimeError("libertai-agentkit service failed to start"),
            )

        ssh_client.close()
        ssh_client = None

        # Step 8: Success summary
        rprint()
        console.rule("[bold green]Deployment Complete")
        rprint()
        rprint(
            Panel(
                f"[bold]Agent Address:[/bold]    [cyan]{address}[/cyan]\n"
                f"[bold]Instance IP:[/bold]      {instance_ip}\n"
                f"[bold]Instance Hash:[/bold]    {instance_hash}\n"
                f"[bold]Network:[/bold]          Base Mainnet\n"
                f"[bold]Service:[/bold]          [green]Docker (running)[/green]",
                title="[bold green]LibertAI AgentKit Agent[/bold green]",
                border_style="green",
            )
        )
    finally:
        if ssh_client is not None:
            ssh_client.close()


@app.command()
async def stop(
    path: Path = typer.Argument(
        None,
        help="Path to agent directory (default: current working directory)",
    ),
) -> None:
    """Stop a running AgentKit agent — tears down Aleph instance."""
    if path is None:
        path = Path.cwd()
    path = path.resolve()

    console.rule("[bold red]LibertAI AgentKit Stop")
    rprint()

    existing = load_existing_wallet(path)
    if not existing:
        rprint("[red]No wallet found in .env.prod or .env — nothing to stop.[/red]")
        raise typer.Exit(1)

    address, private_key = existing
    rprint(f"  Wallet: [cyan]{address}[/cyan]")

    account = get_aleph_account(private_key)

    resources = await _run_step(
        "Checking for existing Aleph resources",
        fn=lambda: check_existing_resources(account),
    )

    if not resources.has_any:
        rprint()
        rprint("[green]No active resources found — nothing to stop.[/green]")
        raise typer.Exit(0)

    rprint()
    rprint(f"  [yellow]Will stop: {resources.summary}[/yellow]")
    rprint()

    confirm = typer.confirm("  Proceed with stopping the agent?", default=False)
    if not confirm:
        rprint("  [dim]Aborted.[/dim]")
        raise typer.Exit(0)

    rprint()

    await _run_step(
        "Deleting resources",
        fn=lambda: delete_existing_resources(account, resources),
    )

    rprint()
    console.rule("[bold green]Agent Stopped")
    rprint()
    rprint(f"  [green]All resources for {address} have been cleaned up.[/green]")
