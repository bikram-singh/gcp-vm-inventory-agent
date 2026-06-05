# agent/tools.py
# ─────────────────────────────────────────────────────────────────────────────
# ADK Tools for GCP VM Inventory Agent
#
# Tools:
#   1. fetch_vm_inventory             — single project scan → Excel
#   2. fetch_multi_project_inventory  — loop over multiple projects
#   3. send_slack_notification        — rich Slack blocks + file upload
#   4. check_vm_health                — flag High CPU / No Backup / Idle VMs
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from gcp_vm_inventory import main as run_inventory

from dotenv import load_dotenv
load_dotenv()


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1 — Single Project Inventory
# ─────────────────────────────────────────────────────────────────────────────

def fetch_vm_inventory(project_id: str, output_file: str = "") -> str:
    """
    Scans all zones in a single GCP project and exports full VM inventory
    details to an Excel (.xlsx) file. Details include: machine type, vCPU,
    RAM, boot disk size and type, OS image, internal/external IPs, VPC,
    subnet, snapshot schedule, uptime, application type, and environment.

    Args:
        project_id: The GCP Project ID to scan (e.g., 'dhg-vaccine-rateauto-nonpord').
        output_file: Optional. Output Excel filename. Defaults to '<project_id>-vms.xlsx'.

    Returns:
        A status message describing success or the error that occurred.
    """
    if not output_file:
        output_file = f"{project_id}-vms.xlsx"

    try:
        run_inventory(project_id=project_id, output_file=output_file)
        abs_path = os.path.abspath(output_file)
        return (
            f"✅ VM inventory for project '{project_id}' written to '{output_file}'.\n"
            f"   Full path: {abs_path}"
        )
    except Exception as e:
        return (
            f"❌ Failed for project '{project_id}': {str(e)}\n"
            f"   Tips: check gcloud auth, project ID, and Compute API enabled."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2 — Multi-Project Loop
# ─────────────────────────────────────────────────────────────────────────────

def fetch_multi_project_inventory(project_ids: str, output_dir: str = "reports") -> str:
    """
    Scans multiple GCP projects in sequence and exports one Excel inventory
    file per project into a specified output directory.

    Args:
        project_ids: Comma-separated list of GCP Project IDs.
                     Example: 'proj-dev, proj-test, proj-stage'
        output_dir:  Directory to save Excel files. Defaults to 'reports/'.

    Returns:
        A summary of which projects succeeded and which failed.
    """
    os.makedirs(output_dir, exist_ok=True)
    projects = [p.strip() for p in project_ids.split(",") if p.strip()]

    if not projects:
        return "❌ No project IDs provided."

    results = []
    succeeded, failed = [], []

    for project_id in projects:
        output_file = os.path.join(output_dir, f"{project_id}-vms.xlsx")
        try:
            run_inventory(project_id=project_id, output_file=output_file)
            abs_path = os.path.abspath(output_file)
            results.append(f"  ✅ {project_id} → {abs_path}")
            succeeded.append(project_id)
        except Exception as e:
            results.append(f"  ❌ {project_id} → FAILED: {str(e)}")
            failed.append({"project": project_id, "error": str(e)})

    summary = [
        f"Multi-project inventory complete.",
        f"  Scanned: {len(projects)} | Success: {len(succeeded)} | Failed: {len(failed)}",
        "",
        "Results:",
    ] + results
    return "\n".join(summary)


# ─────────────────────────────────────────────────────────────────────────────
# Tool 3 — Rich Slack Notification with Blocks
# ─────────────────────────────────────────────────────────────────────────────

def send_slack_notification(
    project_id: str,
    file_path: str = "",
    domain: str = "",
    total_vms: int = 0,
    running_vms: int = 0,
    stopped_vms: int = 0,
    high_cpu_vms: int = 0,
    no_backup_vms: int = 0,
    idle_vms: int = 0,
) -> str:
    """
    Sends a rich formatted Slack notification with VM inventory summary using
    Slack Block Kit. Includes project info, VM counts, health flags, and
    optionally uploads the Excel report file as an attachment.

    Requires SLACK_BOT_TOKEN and SLACK_CHANNEL_ID in the .env file.
    Bot scopes needed: chat:write, files:write.

    Args:
        project_id:    The GCP Project ID that was scanned.
        file_path:     Optional. Path to the Excel report to upload.
        domain:        Optional. Organization domain (e.g. gcpcloudhub.shop).
        total_vms:     Total number of VMs found.
        running_vms:   Number of running VMs.
        stopped_vms:   Number of stopped VMs.
        high_cpu_vms:  Number of VMs with CPU > 80%.
        no_backup_vms: Number of VMs with no snapshot backup.
        idle_vms:      Number of stopped/idle VMs flagged for review.

    Returns:
        A status string confirming the message was sent or describing the error.
    """
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError
    except ImportError:
        return "❌ slack-sdk not installed. Run: pip install slack-sdk"

    bot_token = os.getenv("SLACK_BOT_TOKEN", "")
    channel_id = os.getenv("SLACK_CHANNEL_ID", "")

    if not bot_token or "your-slack" in bot_token:
        return "❌ SLACK_BOT_TOKEN not configured in .env"
    if not channel_id:
        return "❌ SLACK_CHANNEL_ID not configured in .env"

    now = datetime.now(timezone.utc).strftime("%d-%b-%Y %I:%M %p UTC")
    filename = os.path.basename(file_path) if file_path else f"{project_id}-vms.xlsx"
    domain_display = domain if domain and domain != "None" else "N/A"

    # ── Health Flags ──
    health_lines = []
    if high_cpu_vms > 0:
        health_lines.append(f"⚠️  High CPU (>80%)  : *{high_cpu_vms} VM(s)*")
    if no_backup_vms > 0:
        health_lines.append(f"⚠️  No Backup        : *{no_backup_vms} VM(s)*")
    if idle_vms > 0:
        health_lines.append(f"💤  Idle/Stopped     : *{idle_vms} VM(s)*")
    if not health_lines:
        health_lines.append("✅  All VMs healthy — no issues detected")

    health_text = "\n".join(health_lines)

    # ── Slack Block Kit ──
    blocks = [
        # Header
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📊 GCP VM Inventory Report",
                "emoji": True
            }
        },
        {"type": "divider"},

        # Project Info
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🏢 *Project*\n{project_id}"},
                {"type": "mrkdwn", "text": f"🌍 *Domain*\n{domain_display}"},
                {"type": "mrkdwn", "text": f"⏱️ *Generated*\n{now}"},
                {"type": "mrkdwn", "text": f"📎 *Report File*\n{filename}"},
            ]
        },
        {"type": "divider"},

        # VM Summary
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*📈 VM Summary*"}
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🖥️ *Total VMs*\n{total_vms}"},
                {"type": "mrkdwn", "text": f"✅ *Running*\n{running_vms}"},
                {"type": "mrkdwn", "text": f"■ *Stopped*\n{stopped_vms}"},
                {"type": "mrkdwn", "text": f"🔄 *Healthy*\n{max(0, total_vms - high_cpu_vms - no_backup_vms)}"},
            ]
        },
        {"type": "divider"},

        # Health Check
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🏥 Health Check*\n{health_text}"
            }
        },
        {"type": "divider"},

        # Footer
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🤖 Sent by *GCP VM Inventory Bot* | Powered by Google ADK + Gemini"
                }
            ]
        }
    ]

    client = WebClient(token=bot_token)
    result_lines = []

    try:
        # Post rich block message
        client.chat_postMessage(
            channel=channel_id,
            text=f"📊 GCP VM Inventory Report — {project_id}",  # fallback text
            blocks=blocks
        )
        result_lines.append(f"✅ Rich Slack report sent to {channel_id}.")

        # Upload Excel file
        if file_path:
            abs_path = os.path.abspath(file_path)
            if not os.path.exists(abs_path):
                result_lines.append(f"⚠️  File not found: {abs_path}. Run fetch_vm_inventory first.")
            else:
                with open(abs_path, "rb") as f:
                    client.files_upload_v2(
                        channel=channel_id,
                        file=f,
                        filename=filename,
                        title=f"VM Inventory — {project_id}",
                        initial_comment=f"📎 Full VM inventory report for *{project_id}*",
                    )
                result_lines.append(f"✅ Excel report '{filename}' uploaded to Slack.")

        return "\n".join(result_lines)

    except SlackApiError as e:
        return (
            f"❌ Slack API error: {e.response['error']}\n"
            f"   Required scopes: chat:write, files:write"
        )
    except Exception as e:
        return f"❌ Unexpected Slack error: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# Tool 4 — VM Health Check
# ─────────────────────────────────────────────────────────────────────────────

def check_vm_health(project_id: str, file_path: str = "") -> str:
    """
    Reads the VM inventory Excel report and performs a health check on all VMs.
    Flags VMs with issues:
      - ⚠️  High CPU: CPU utilization mean > 80%
      - ⚠️  No Backup: VM has no snapshot configured
      - 💤  Idle: VM is stopped/terminated

    Also returns counts suitable for passing to send_slack_notification.

    Args:
        project_id: The GCP Project ID (used to find the Excel file if file_path not given).
        file_path:  Optional. Path to the Excel file. Defaults to '<project_id>-vms.xlsx'.

    Returns:
        A detailed health report string with flagged VMs and summary counts.
    """
    try:
        import pandas as pd
    except ImportError:
        return "❌ pandas not installed. Run: pip install pandas"

    if not file_path:
        file_path = f"{project_id}-vms.xlsx"

    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return (
            f"❌ Report file not found: {abs_path}\n"
            f"   Run fetch_vm_inventory for '{project_id}' first."
        )

    try:
        df = pd.read_excel(abs_path)
    except Exception as e:
        return f"❌ Could not read Excel file: {str(e)}"

    total_vms = len(df)
    if total_vms == 0:
        return f"ℹ️  No VMs found in report for project '{project_id}'."

    high_cpu, no_backup, idle = [], [], []

    for _, row in df.iterrows():
        vm_name = str(row.get("VM Instance Name", "Unknown"))
        status  = str(row.get("Machine Status", "")).lower()
        cpu_raw = str(row.get("CPU utilization [MEAN]", "None"))
        snaps   = str(row.get("Snapshots", "None")).lower()

        # ── Idle / Stopped ──
        if any(s in status for s in ["stopped", "terminated", "■", "idle", "suspended"]):
            idle.append(vm_name)

        # ── High CPU ──
        if cpu_raw not in ("None", "", "nan"):
            try:
                cpu_val = float(cpu_raw.replace("%", "").strip())
                if cpu_val > 80:
                    high_cpu.append(f"{vm_name} ({cpu_val:.1f}%)")
            except ValueError:
                pass

        # ── No Backup ──
        if snaps in ("none", "", "nan", "no"):
            no_backup.append(vm_name)

    # ── Running/Stopped counts ──
    running_vms = total_vms - len(idle)
    stopped_vms = len(idle)

    # ── Build report ──
    lines = [
        f"🏥 VM Health Check — {project_id}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🖥️  Total VMs    : {total_vms}",
        f"✅  Running      : {running_vms}",
        f"■   Stopped      : {stopped_vms}",
        f"⚠️   High CPU     : {len(high_cpu)}",
        f"⚠️   No Backup    : {len(no_backup)}",
        f"💤  Idle/Stopped : {len(idle)}",
        "",
    ]

    if high_cpu:
        lines.append("⚠️  HIGH CPU VMs (>80%):")
        for vm in high_cpu:
            lines.append(f"   • {vm}")
        lines.append("")

    if no_backup:
        lines.append("⚠️  NO BACKUP VMs (no snapshots):")
        for vm in no_backup:
            lines.append(f"   • {vm}")
        lines.append("")

    if idle:
        lines.append("💤  IDLE/STOPPED VMs:")
        for vm in idle:
            lines.append(f"   • {vm}")
        lines.append("")

    if not high_cpu and not no_backup and not idle:
        lines.append("✅  All VMs are healthy — no issues detected!")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"💡 To send this to Slack, use send_slack_notification with:\n"
        f"   project_id='{project_id}', total_vms={total_vms}, "
        f"running_vms={running_vms}, stopped_vms={stopped_vms}, "
        f"high_cpu_vms={len(high_cpu)}, no_backup_vms={len(no_backup)}, "
        f"idle_vms={len(idle)}"
    )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Tool 5 — Push to BigQuery
# ─────────────────────────────────────────────────────────────────────────────

def push_inventory_to_bigquery(project_id: str, excel_file: str = "") -> str:
    """
    Reads the VM inventory Excel report and pushes all rows into a BigQuery
    table (vm_inventory.vm_details) in the specified GCP project. Creates
    the dataset and table automatically if they don't exist. Each run appends
    a new date-partitioned snapshot so historical trends are preserved.

    After pushing, the data can be connected to Looker Studio for dashboards.

    Args:
        project_id: GCP Project ID where BigQuery dataset will be created.
                    Example: 'dhg-vaccine-rateauto-nonpord'
        excel_file: Optional. Path to the Excel file. Defaults to
                    '<project_id>-vms.xlsx' in the current directory.

    Returns:
        A status message with table details and a sample query.
    """
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from push_to_bigquery import push_to_bigquery

    if not excel_file:
        excel_file = f"{project_id}-vms.xlsx"

    return push_to_bigquery(project_id=project_id, excel_file=excel_file)