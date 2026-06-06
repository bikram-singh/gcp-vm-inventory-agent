<div align="center">

# 🤖 GCP VM Inventory Agent

### AI-Powered Infrastructure Monitoring · Google ADK · Gemini · BigQuery · Slack

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Google_ADK-2.1.0-4285F4?logo=google&logoColor=white)](https://google.github.io/adk-docs/)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash_Lite-8E44AD?logo=google&logoColor=white)](https://ai.google.dev)
[![BigQuery](https://img.shields.io/badge/BigQuery-Enabled-34A853?logo=google-cloud&logoColor=white)](https://cloud.google.com/bigquery)
[![Slack](https://img.shields.io/badge/Slack-Notifications-4A154B?logo=slack&logoColor=white)](https://slack.com)
[![GCP](https://img.shields.io/badge/GCP-Compute_Engine-FF6D00?logo=google-cloud&logoColor=white)](https://cloud.google.com/compute)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

*An AI-powered GCP VM inventory agent built with Google Agent Development Kit (ADK). Scans all virtual machines across GCP projects, performs health checks, pushes data to BigQuery for historical analytics, and sends rich formatted reports to Slack - all triggered by a single natural language command.*

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Agent Tools](#-agent-tools)
- [Repository Structure](#-repository-structure)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Running the Agent](#-running-the-agent)
- [VM Inventory Columns](#-vm-inventory-columns)
- [BigQuery Schema](#-bigquery-schema)
- [Slack Notifications](#-slack-notifications)
- [Looker Studio Dashboard](#-looker-studio-dashboard)
- [Example Conversations](#-example-conversations)
- [Snapshots](#-snapshots)
- [Repository](#-repository)

---

## 🌐 Overview

Rather than manually logging into the GCP console to check VM status, this agent automates the entire infrastructure inventory lifecycle through natural language. One command triggers a full pipeline — from GCP API calls to a Slack-delivered Excel report and a live BigQuery-backed dashboard.

### 🔑 Key Facts

| Property | Value |
|---|---|
| 🤖 **Agent Framework** | Google Agent Development Kit (ADK) 2.1.0 |
| 🧠 **LLM** | Gemini 2.5 Flash Lite |
| ☁️ **Cloud Platform** | Google Cloud Platform |
| 📊 **Analytics** | BigQuery + Looker Studio |
| 📢 **Notifications** | Slack (Block Kit rich messages) |
| 📁 **Output Format** | Excel (.xlsx) with styled status cells |
| 🐍 **Language** | Python 3.11+ |
| 🖥️ **UI** | ADK Web UI (`http://localhost:8080`) |

### ✨ What It Does

| Capability | Description |
|---|---|
| 🔍 **VM Scanning** | Scans all zones in one or multiple GCP projects |
| 🏥 **Health Check** | Flags High CPU (>80%), No Backup, and Idle VMs |
| 📤 **Excel Export** | Generates a styled 26-column Excel report |
| 🗄️ **BigQuery Push** | Appends date-partitioned rows with deduplication |
| 📊 **Dashboard** | Looker Studio dashboard auto-updates from BigQuery |
| 📣 **Slack Report** | Rich Block Kit message + Excel file attachment |

---

## 🏛️ Architecture

![GCP VM Agent Architecture](docs/snapshots/gcp_vm_agent_architecture.png)

> The diagram shows the complete data flow from the Developer through the ADK Agent, across all GCP services, to BigQuery, Looker Studio, and Slack.

### 🔄 Layer Breakdown

| Layer | Components |
|---|---|
| **User Layer** | Developer / Operator → ADK Web UI → Gemini 2.5 Flash Lite |
| **AI Agent Layer** | ADK Agent () · IAM/ADC Authentication |
| **GCP Services Layer** | Compute Engine API · Cloud Monitoring · Resource Manager API · Guest Attributes API |
| **Data Layer** |  · Excel Report (.xlsx) · BigQuery () |
| **Visualization Layer** | Looker Studio Dashboard (connected to BigQuery) |
| **Notification Layer** | Slack Block Kit messages + Excel file attachment |

### 🔄 Full Pipeline Flow

```
Step 1  fetch_vm_inventory        →  Scan GCP · Collect 26 fields · Export .xlsx
Step 2  check_vm_health           →  Read .xlsx · Flag CPU/Backup/Idle issues
Step 3  push_inventory_to_bigquery →  Deduplicate · Append date partition to BQ
Step 4  send_slack_notification   →  Rich Block Kit message · Upload .xlsx to Slack
```

---

## 🛠️ Agent Tools

The agent exposes **5 tools** that can be called individually or chained automatically:

### 1️⃣ `fetch_vm_inventory`

Scans all zones in a single GCP project and exports a full VM inventory to Excel.

```
Input:  project_id, output_file (optional)
Output: <project_id>-vms.xlsx with 26 columns
APIs:   Compute Engine, Cloud Monitoring, Resource Manager
```

**Collected fields per VM:**
- Identity: Instance ID, Name, Status, Machine Type, OS Image
- Compute: vCPU, RAM (GB)
- Network: Internal IP, External IP, VPC, Subnet, Target Network Project
- Storage: Boot Disk Size, Disk Type
- Snapshots: Snapshot status, latest date, schedule frequency
- Metadata: Domain, Hostname, Environment, Application Type
- Metrics: CPU Utilization (24h mean), RAM Usage (24h mean)
- Health: Uptime (weeks), Health status

---

### 2️⃣ `fetch_multi_project_inventory`

Scans multiple GCP projects in sequence, generating one Excel file per project.

```
Input:  project_ids (comma-separated), output_dir (optional, default: reports/)
Output: One .xlsx per project in the output directory
```

---

### 3️⃣ `check_vm_health`

Reads the Excel report and flags VMs with issues:

| Flag | Condition |
|---|---|
| ⚠️ **High CPU** | CPU utilization mean > 80% |
| ⚠️ **No Backup** | No snapshot configured |
| 💤 **Idle/Stopped** | Machine status is Stopped or Terminated |

Returns counts for passing to `send_slack_notification`.

---

### 4️⃣ `push_inventory_to_bigquery`

Pushes Excel data to BigQuery with date partitioning and automatic deduplication.

```
Dataset:   vm_inventory
Table:     vm_details
Partition: snapshot_date (DATE)
Mode:      Delete-then-insert (prevents duplicate rows on re-run)
```

---

### 5️⃣ `send_slack_notification`

Sends a rich formatted Slack Block Kit message with VM summary and health flags, then uploads the Excel file as an attachment.

```
Message format:  Header · Project info · VM summary · Health check · Footer
File upload:     Excel .xlsx attached to the same channel message
```

---

## 📁 Repository Structure

```
gcp-vm-inventory-agent/
│
├── 📁 agent/
│   ├── 📄 __init__.py          # ADK module entry point
│   ├── 📄 agent.py             # Root ADK agent definition (Gemini model + tools)
│   └── 📄 tools.py             # All 5 tool implementations
│
├── 📁 docs/
│   └── 📁 gallery/             # Screenshots for README
│
├── 📄 gcp_vm_inventory.py      # Core inventory script (v6.0)
│                                #   Compute Engine API · Monitoring API
│                                #   Resource Manager API · Excel export
│
├── 📄 push_to_bigquery.py      # BigQuery push with schema + deduplication
│
├── 📄 requirements.txt         # Python dependencies
├── 📄 .env                     # API keys and config (not committed ideally)
├── 📄 adc-credentials.json     # GCP Application Default Credentials
└── 📄 README.md                # This file
```

---

## ✅ Prerequisites

| Requirement | Details |
|---|---|
| 🐍 **Python** | 3.11 or higher |
| ☁️ **GCP Account** | With Compute Engine API enabled |
| 🔑 **Gemini API Key** | From [Google AI Studio](https://aistudio.google.com/app/apikey) |
| 🔧 **gcloud CLI** | For GCP authentication |
| 💬 **Slack Workspace** | With a Bot Token (optional) |

### 🔌 GCP APIs Required

```bash
gcloud services enable compute.googleapis.com \
  monitoring.googleapis.com \
  cloudresourcemanager.googleapis.com \
  bigquery.googleapis.com \
  --project=YOUR_PROJECT_ID
```

### 🔐 IAM Roles Required

| Role | Purpose |
|---|---|
| `roles/compute.viewer` | Read VM instances, disks, machine types |
| `roles/monitoring.viewer` | Read CPU and RAM metrics |
| `roles/resourcemanager.organizationViewer` | Read org domain |
| `roles/bigquery.dataEditor` | Write to BigQuery tables |
| `roles/bigquery.jobUser` | Run BigQuery jobs |

> **Note:** `Organization Administrator` role covers all of the above.

---

## 🚀 Installation

### Step 1 — Clone the repository

```bash
git clone https://github.com/bikram-singh/gcp-vm-inventory-agent.git
cd gcp-vm-inventory-agent
```

### Step 2 — Create virtual environment

```bash
# Windows (VS Code terminal)
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Authenticate with GCP

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

---

## ⚙️ Configuration

### `.env` file

Create a `.env` file in the project root:

```env
# ── Gemini / ADK ─────────────────────────────────────────────
# Get your key from: https://aistudio.google.com/app/apikey
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_API_KEY=your_gemini_api_key_here

# ── Slack (optional) ─────────────────────────────────────────
# Create a Bot at: https://api.slack.com/apps
# Required scopes: chat:write, files:write
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token-here
SLACK_CHANNEL_ID=C0XXXXXXXXX

# ── GCP Auth ─────────────────────────────────────────────────
# Run: gcloud auth application-default login
# No env var needed — ADC is picked up automatically.
```

### `adc-credentials.json`

For Windows/local environments where `gcloud auth application-default login` has browser redirect issues, copy credentials from Cloud Shell:

```bash
# In Google Cloud Shell
gcloud auth application-default login
cat /tmp/tmp.*/application_default_credentials.json
```

Paste the JSON into `adc-credentials.json` and set:

```powershell
# Windows PowerShell
$env:GOOGLE_APPLICATION_CREDENTIALS="D:\path\to\gcp-vm-inventory-agent\adc-credentials.json"
```

### Slack Bot Setup

1. Go to **https://api.slack.com/apps** → **Create New App** → **From Scratch**
2. Name: `GCP VM Inventory Bot` → Select your workspace
3. **OAuth & Permissions** → **Bot Token Scopes** → Add:
   - `chat:write`
   - `files:write`
4. **Install to Workspace** → Copy **Bot User OAuth Token** (`xoxb-...`)
5. In Slack: invite the bot → `/invite @GCP VM Inventory Bot`
6. Set `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` in `.env`

---

## ▶️ Running the Agent

### Option A — Web UI (recommended)

```powershell
# Windows
$env:GOOGLE_APPLICATION_CREDENTIALS="D:\path\to\adc-credentials.json"
$env:GOOGLE_API_KEY="your_api_key"
$env:GOOGLE_GENAI_USE_VERTEXAI="FALSE"
adk web . --port 8080
```

```bash
# macOS / Linux / Cloud Shell
export GOOGLE_API_KEY=your_api_key
export GOOGLE_GENAI_USE_VERTEXAI=FALSE
adk web . --port 8080
```

Open **http://localhost:8080** in your browser.

> **Cloud Shell users:** Use Web Preview → Preview on port 8080

### Option B — CLI (terminal)

```bash
export GOOGLE_API_KEY=your_api_key
export GOOGLE_GENAI_USE_VERTEXAI=FALSE
adk run agent
```

### Option C — Direct script (BigQuery push only)

```bash
python push_to_bigquery.py \
  --project_id your-project-id \
  --excel_file your-project-id-vms.xlsx
```

---

## 📊 VM Inventory Columns

The generated Excel report contains **26 columns**:

| # | Column | Description | Source |
|---|---|---|---|
| 1 | Project ID | GCP project identifier | Input |
| 2 | VM Instance Name | Name of the VM | Compute API |
| 3 | Machine Status | ✅ Running / ■ Stopped | Compute API |
| 4 | Instance ID | Unique GCP instance ID | Compute API |
| 5 | Domain | Organisation domain (e.g. gcpcloudhub.shop) | Resource Manager API |
| 6 | OS/Image | Boot disk source image | Compute API |
| 7 | Application Type | `Products` or `Products-DB` (based on VM name) | Derived |
| 8 | Environment | `production` or `non-production` (based on project ID) | Derived |
| 9 | Machine Type | e.g. `e2-medium`, `n2-standard-4` | Compute API |
| 10 | vCPU | Number of virtual CPUs | Machine Type API |
| 11 | RAM (GB) | Memory in gigabytes | Machine Type API |
| 12 | Hostname | Guest OS hostname (if guest attributes enabled) | Guest Attributes |
| 13 | Storage GB (Boot Disk) | Boot disk size in GB | Disks API |
| 14 | Internal IP | Private IP address(es) | Network Interface |
| 15 | Storage Type | e.g. `SSD persistent disk` | Disks API |
| 16 | Target Network Project | Shared VPC host project (if applicable) | Network Interface |
| 17 | VPC Name | VPC network name | Network Interface |
| 18 | Subnet Name | Subnetwork name | Network Interface |
| 19 | External IP | Public IP (if assigned) | Network Interface |
| 20 | Snapshots | `Yes` or `None` | Snapshots API |
| 21 | Snapshot Dates | Latest snapshot date | Snapshots API |
| 22 | Snapshot Schedules | Schedule frequency (e.g. `Every day`) | Resource Policies API |
| 23 | Uptime (W) | Weeks since VM creation | Compute API |
| 24 | CPU utilization [MEAN] | 24h mean CPU % (e.g. `45.2%`) | Cloud Monitoring API |
| 25 | RAM usage | 24h mean RAM % (requires Ops Agent) | Cloud Monitoring API |
| 26 | Health | `Healthy` (default) | Derived |

> **Note:** RAM usage requires the [Google Cloud Ops Agent](https://cloud.google.com/stackdriver/docs/solutions/agents/ops-agent) to be installed on the VM. Otherwise it shows `None`.

---

## 🗄️ BigQuery Schema

**Dataset:** `vm_inventory`
**Table:** `vm_details`
**Partitioning:** `snapshot_date` (DATE, daily)

| Field | Type | Description |
|---|---|---|
| `snapshot_date` | DATE | Date the inventory was collected |
| `project_id` | STRING | GCP project ID |
| `vm_instance_name` | STRING | VM name |
| `machine_status` | STRING | Running / Stopped |
| `instance_id` | STRING | GCP instance numeric ID |
| `domain` | STRING | Organisation domain |
| `os_image` | STRING | OS image name |
| `application_type` | STRING | Products / Products-DB |
| `environment` | STRING | production / non-production |
| `machine_type` | STRING | e2-medium, n2-standard-4, etc. |
| `vcpu` | INTEGER | Virtual CPU count |
| `ram_gb` | FLOAT | RAM in GB |
| `hostname` | STRING | Guest OS hostname |
| `storage_gb_boot_disk` | INTEGER | Boot disk size (GB) |
| `internal_ip` | STRING | Private IP |
| `storage_type` | STRING | Disk type |
| `target_network_project` | STRING | Shared VPC host project |
| `vpc_name` | STRING | VPC network name |
| `subnet_name` | STRING | Subnet name |
| `external_ip` | STRING | Public IP |
| `snapshots` | STRING | Yes / null |
| `snapshot_dates` | STRING | Latest snapshot date |
| `snapshot_schedules` | STRING | Snapshot schedule frequency |
| `uptime_weeks` | INTEGER | Weeks since creation |
| `cpu_utilization_mean` | STRING | 24h mean CPU % |
| `ram_usage` | STRING | 24h mean RAM % |
| `health` | STRING | Health status |

### Sample Query

```sql
-- Today's VM inventory
SELECT
  vm_instance_name,
  machine_status,
  machine_type,
  vcpu,
  ram_gb,
  environment,
  cpu_utilization_mean,
  health
FROM `your-project.vm_inventory.vm_details`
WHERE snapshot_date = CURRENT_DATE()
ORDER BY vm_instance_name;

-- VMs with no backup across all time
SELECT DISTINCT vm_instance_name, project_id, snapshot_date
FROM `your-project.vm_inventory.vm_details`
WHERE snapshots IS NULL
ORDER BY snapshot_date DESC;

-- VM count trend over time
SELECT snapshot_date, COUNT(*) as vm_count
FROM `your-project.vm_inventory.vm_details`
GROUP BY snapshot_date
ORDER BY snapshot_date;
```

---

## 📣 Slack Notifications

The agent sends rich **Slack Block Kit** messages to your configured channel:

```
📊 GCP VM Inventory Report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏢 Project    dhg-vaccine-rateauto-nonpord
🌍 Domain     gcpcloudhub.shop
⏱️ Generated  05-Jun-2026 08:01 AM UTC
📎 Report     dhg-vaccine-rateauto-nonpord-vms.xlsx

📈 VM Summary
🖥️ Total: 3    ✅ Running: 2    ■ Stopped: 1

🏥 Health Check
⚠️ No Backup (no snapshots)  : 2 VM(s)
💤 Idle/Stopped              : 1 VM(s)

🤖 Sent by GCP VM Inventory Bot | Powered by Google ADK + Gemini
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📎 dhg-vaccine-rateauto-nonpord-vms.xlsx   [Excel Spreadsheet]
```

---

## 📊 Looker Studio Dashboard

After pushing data to BigQuery, connect Looker Studio for a live dashboard:

1. Go to **https://lookerstudio.google.com**
2. **Create** → **Data Source** → **BigQuery**
3. Select your project → `vm_inventory` → `vm_details`
4. Click **Connect** → **Create Report**

### Recommended Charts

| Chart | Dimension | Metric | Purpose |
|---|---|---|---|
| Scorecard | — | Record Count | Total VMs |
| Scorecard | machine_status = Running | Record Count | Running VMs |
| Scorecard | machine_status = Stopped | Record Count | Stopped VMs |
| Scorecard | snapshots IS NULL | Record Count | No Backup VMs |
| Bar chart | machine_status | Record Count | VM Status breakdown |
| Bar chart | machine_type | Record Count | VMs by machine type |
| Table | All key fields | — | Full VM inventory |
| Time series | snapshot_date | Record Count | VM count over time |

> Add a **Date Range Control** at the top of the report to filter all charts to a specific date. Set default to **This week** to always show today's data.

---

## 💬 Example Conversations

### Single project scan

```
You:   Fetch VM inventory for project dhg-vaccine-rateauto-nonpord
Agent: ✅ VM inventory for project 'dhg-vaccine-rateauto-nonpord' written to
       'dhg-vaccine-rateauto-nonpord-vms.xlsx'.
       Found: 3 VMs across 2 zones.
```

### Full pipeline in one command

```
You:   Run full pipeline for dhg-vaccine-rateauto-nonpord
Agent: [Step 1] Scanning VMs... ✅ 3 VMs exported to Excel
       [Step 2] Health check... ⚠️ 2 VMs with no backup, 1 idle
       [Step 3] Pushing to BigQuery... ✅ 3 rows pushed to vm_details
       [Step 4] Sending Slack report... ✅ Message + Excel sent to #gcm-vm-inventory
```

### Multi-project scan

```
You:   Scan all three environments:
       dhg-rateauto-dev, dhg-rateauto-test, dhg-rateauto-stage
Agent: Multi-project inventory complete.
       Scanned: 3 | Success: 3 | Failed: 0
       ✅ dhg-rateauto-dev   → reports/dhg-rateauto-dev-vms.xlsx
       ✅ dhg-rateauto-test  → reports/dhg-rateauto-test-vms.xlsx
       ✅ dhg-rateauto-stage → reports/dhg-rateauto-stage-vms.xlsx
```

### Health check only

```
You:   Run health check for dhg-vaccine-rateauto-nonpord
Agent: 🏥 VM Health Check — dhg-vaccine-rateauto-nonpord
       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
       🖥️ Total VMs    : 3
       ✅ Running      : 2
       ■  Stopped      : 1
       ⚠️ High CPU     : 0
       ⚠️ No Backup    : 2
       💤 Idle/Stopped : 1

       ⚠️ NO BACKUP VMs (no snapshots):
          • windows-vm
          • test-vm
```

---

## 📸 Snapshots

### 1️⃣ ADK Web UI - Agent Running
![ADK Web UI](docs/snapshots/1_adk_web_ui.png)

---

### 2️⃣ Full Pipeline Execution - All 4 Tools Chained
![Full Pipeline](docs/snapshots/2_full_pipeline_execution.png)

---

### 3️⃣ Excel Report - VM Inventory
![Excel Report](docs/snapshots/3_excel_report.png)

---

### 4️⃣ BigQuery Table - vm_details
![BigQuery Table](docs/snapshots/4_bigquery_table.png)

---

### 5️⃣ Slack Notification - Rich Block Kit Report + Excel Attachment
![Slack Notification](docs/snapshots/5_slack_notification.png)

---

### 6️⃣ Looker Studio Dashboard
![Looker Studio Dashboard](docs/snapshots/6_looker_studio_dashboard.png)

---

## 🔗 Repository

| Repository | Purpose |
|---|---|
| [`gcp-vm-inventory-agent`](https://github.com/bikram-singh/gcp-vm-inventory-agent) | AI VM Inventory Agent |

---

<div align="center">

**Maintained by Bikram Singh**

`dhg-vaccine-rateauto-nonpord` · `us-central1` · Google Cloud Platform

*Built with Google ADK · Gemini · BigQuery · Slack*

</div>
