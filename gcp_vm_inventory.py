# gcp_vm_inventory.py (v6.0 - Full Inventory with Domain, Hostname, CPU & RAM Metrics)

import argparse
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import compute_v1
from google.cloud import monitoring_v3
from google.cloud import resourcemanager_v3

# Caches
machine_type_cache = {}
resource_policy_cache = {}
monitoring_cache = {}

# Keywords for Application Type detection
DB_KEYWORDS = [
    'db', 'alloydb', 'sql', 'postgre', 'mongodb', 'mongo', 'mysql',
    'cloud sql', 'sql server', 'spanner', 'nosql', 'firestore', 'bigtable', 'memorystore'
]

# Keywords for Environment detection
NON_PROD_KEYWORDS = ['dev', 'development', 'stg', 'staging', 'uat', 'non-prod']

STORAGE_TYPE_MAP = {
    'pd-standard': 'Standard persistent disk',
    'pd-balanced': 'Balanced persistent disk',
    'pd-ssd': 'SSD persistent disk',
    'pd-extreme': 'Extreme persistent disk',
    'hyperdisk-throughput': 'Hyperdisk Throughput',
    'hyperdisk-extreme': 'Hyperdisk Extreme',
}


# ─────────────────────────────────────────────────────────────
# Helper: Machine Type
# ─────────────────────────────────────────────────────────────
def get_machine_type_details(client, project_id, machine_type_url):
    if machine_type_url in machine_type_cache:
        return machine_type_cache[machine_type_url]
    try:
        parts = machine_type_url.split('/')
        zone, type_name = parts[-3], parts[-1]
        request = compute_v1.GetMachineTypeRequest(project=project_id, zone=zone, machine_type=type_name)
        response = client.get(request=request)
        details = {"vCPU": response.guest_cpus, "RAM (GB)": response.memory_mb / 1024}
        machine_type_cache[machine_type_url] = details
        return details
    except (GoogleAPICallError, IndexError) as e:
        print(f"Could not fetch machine type for {machine_type_url}: {e}", file=sys.stderr)
        return {}


# ─────────────────────────────────────────────────────────────
# Helper: Snapshot Schedule
# ─────────────────────────────────────────────────────────────
def get_schedule_frequency(client, project_id, policy_url):
    if policy_url in resource_policy_cache:
        return resource_policy_cache[policy_url]
    try:
        parts = policy_url.split('/')
        region, policy_name = parts[-3], parts[-1]
        request = compute_v1.GetResourcePolicyRequest(project=project_id, region=region, resource_policy=policy_name)
        policy = client.get(request=request)
        schedule = policy.snapshot_schedule_policy.schedule
        frequency = "Custom Schedule"
        if schedule.hourly_schedule:
            frequency = f"Every {schedule.hourly_schedule.hours_in_cycle} hours"
        elif schedule.daily_schedule:
            frequency = "Every day"
        elif schedule.weekly_schedule and schedule.weekly_schedule.day_of_weeks:
            day = schedule.weekly_schedule.day_of_weeks[0].day.capitalize()
            frequency = f"Every {day}"
        resource_policy_cache[policy_url] = frequency
        return frequency
    except (GoogleAPICallError, AttributeError, IndexError) as e:
        print(f"Could not fetch schedule for {policy_url.split('/')[-1]}: {e}", file=sys.stderr)
        return policy_url.split('/')[-1]


# ─────────────────────────────────────────────────────────────
# Helper: Domain from Organization
# ─────────────────────────────────────────────────────────────
def get_organization_domain(project_id):
    """Fetches the organization domain for a GCP project."""
    try:
        projects_client = resourcemanager_v3.ProjectsClient()
        project = projects_client.get_project(name=f"projects/{project_id}")
        
        # Walk up the ancestry to find the org
        org_id = None
        for ancestor in projects_client.get_project(name=f"projects/{project_id}").name.split('/'):
            pass  # just getting the project first

        # Use search ancestors
        ancestors_client = resourcemanager_v3.OrganizationsClient()
        
        # Get project's parent chain
        proj = projects_client.get_project(name=f"projects/{project_id}")
        parent = proj.parent  # e.g. "folders/123" or "organizations/456"
        
        # Traverse up to find org
        folders_client = resourcemanager_v3.FoldersClient()
        current = parent
        while current:
            if current.startswith("organizations/"):
                org = ancestors_client.get_organization(name=current)
                # org.display_name is usually the domain
                domain = org.display_name
                if domain:
                    return domain
                break
            elif current.startswith("folders/"):
                try:
                    folder = folders_client.get_folder(name=current)
                    current = folder.parent
                except Exception:
                    break
            else:
                break
        return "None"
    except Exception as e:
        print(f"Could not fetch org domain for {project_id}: {e}", file=sys.stderr)
        return "None"


# ─────────────────────────────────────────────────────────────
# Helper: Hostname from Guest Attributes
# ─────────────────────────────────────────────────────────────
def get_hostname(instance_client, project_id, zone, instance_name):
    """Fetches hostname from VM guest attributes if available."""
    try:
        request = compute_v1.GetGuestAttributesInstanceRequest(
            project=project_id,
            zone=zone,
            instance=instance_name,
            query_path="hostname"
        )
        response = instance_client.get_guest_attributes(request=request)
        for item in response.query_value.items:
            if item.key == "hostname":
                return item.value
        return "None"
    except Exception:
        return "None"


# ─────────────────────────────────────────────────────────────
# Helper: CPU & RAM from Cloud Monitoring
# ─────────────────────────────────────────────────────────────
def get_monitoring_metrics(project_id, instance_id, zone):
    """
    Fetches mean CPU utilization (last 24h) and RAM usage % (last 24h).
    RAM requires the Cloud Monitoring agent (ops agent) installed on the VM.
    """
    cache_key = f"{project_id}_{instance_id}"
    if cache_key in monitoring_cache:
        return monitoring_cache[cache_key]

    result = {"cpu": "None", "ram": "None"}

    try:
        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{project_id}"

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        interval = monitoring_v3.TimeInterval(
            start_time=start,
            end_time=now,
        )

        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": 86400},  # 24h window
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
            cross_series_reducer=monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
            group_by_fields=["resource.labels.instance_id"],
        )

        # ── CPU Utilization ──
        try:
            cpu_filter = (
                f'metric.type="compute.googleapis.com/instance/cpu/utilization" '
                f'AND resource.labels.instance_id="{instance_id}"'
            )
            cpu_request = monitoring_v3.ListTimeSeriesRequest(
                name=project_name,
                filter=cpu_filter,
                interval=interval,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                aggregation=aggregation,
            )
            cpu_series = list(client.list_time_series(request=cpu_request))
            if cpu_series and cpu_series[0].points:
                cpu_val = cpu_series[0].points[0].value.double_value * 100
                result["cpu"] = f"{cpu_val:.1f}%"
        except Exception as e:
            print(f"  CPU metric error for {instance_id}: {e}", file=sys.stderr)

        # ── RAM Usage (requires Ops Agent) ──
        try:
            ram_filter = (
                f'metric.type="agent.googleapis.com/memory/percent_used" '
                f'AND resource.labels.instance_id="{instance_id}" '
                f'AND metric.labels.state="used"'
            )
            ram_request = monitoring_v3.ListTimeSeriesRequest(
                name=project_name,
                filter=ram_filter,
                interval=interval,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                aggregation=aggregation,
            )
            ram_series = list(client.list_time_series(request=ram_request))
            if ram_series and ram_series[0].points:
                ram_val = ram_series[0].points[0].value.double_value
                result["ram"] = f"{ram_val:.1f}%"
        except Exception as e:
            print(f"  RAM metric error for {instance_id}: {e}", file=sys.stderr)

    except Exception as e:
        print(f"  Monitoring error for instance {instance_id}: {e}", file=sys.stderr)

    monitoring_cache[cache_key] = result
    return result


# ─────────────────────────────────────────────────────────────
# Helper: Application Type & Environment
# ─────────────────────────────────────────────────────────────
def determine_application_type(vm_name):
    lower_vm_name = vm_name.lower()
    for keyword in DB_KEYWORDS:
        if keyword in lower_vm_name:
            return "Products-DB"
    return "Products"


def determine_environment(project_id):
    lower_project_id = project_id.lower()
    for keyword in NON_PROD_KEYWORDS:
        if keyword in lower_project_id:
            return "non-production"
    return "production"


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main(project_id, output_file):
    print(f"Starting VM inventory for project: {project_id}")
    all_vm_details = []

    environment = determine_environment(project_id)

    # Fetch org domain once for entire project
    print("Fetching organization domain...")
    domain = get_organization_domain(project_id)
    print(f"  Domain: {domain}")

    try:
        instance_client = compute_v1.InstancesClient()
        disk_client = compute_v1.DisksClient()
        snapshot_client = compute_v1.SnapshotsClient()
        machine_type_client = compute_v1.MachineTypesClient()
        resource_policy_client = compute_v1.ResourcePoliciesClient()

        request = compute_v1.AggregatedListInstancesRequest(project=project_id)
        all_instances = instance_client.aggregated_list(request=request)
        print("Fetching all instances across all zones... (This may take a moment)")

        for zone, response in all_instances:
            if not response.instances:
                continue
            zone_name = zone.split('/')[-1]
            print(f"Processing instances in zone: {zone_name}")

            for instance in response.instances:
                try:
                    machine_details = get_machine_type_details(machine_type_client, project_id, instance.machine_type)

                    # ── Network ──
                    internal_ip, external_ip, vpc_name, subnet_name, target_network_project = "None", "None", "None", "None", "None"
                    if instance.network_interfaces:
                        internal_ips_list = [ni.network_i_p for ni in instance.network_interfaces if ni.network_i_p]
                        internal_ip = ", ".join(internal_ips_list) if internal_ips_list else "None"
                        primary_ni = instance.network_interfaces[0]
                        if primary_ni.access_configs:
                            external_ip = primary_ni.access_configs[0].nat_i_p or "None"
                        if primary_ni.network:
                            vpc_name = primary_ni.network.split('/')[-1]
                        if primary_ni.subnetwork:
                            subnet_name = primary_ni.subnetwork.split('/')[-1]
                        source_url = primary_ni.subnetwork if primary_ni.subnetwork else primary_ni.network
                        if source_url:
                            try:
                                url_parts = source_url.split('/')
                                project_idx = url_parts.index('projects')
                                network_host_project = url_parts[project_idx + 1]
                                if network_host_project != project_id:
                                    target_network_project = network_host_project
                            except (ValueError, IndexError):
                                target_network_project = "Parse Error"

                    # ── Disk & Snapshots ──
                    boot_disk_size_gb, boot_disk_type, os_image = "None", "None", "None"
                    snapshot_schedules, has_snapshots, latest_snapshot_timestamp = [], False, ""
                    if instance.disks:
                        boot_disk_info = next((d for d in instance.disks if d.boot), None)
                        if boot_disk_info:
                            boot_disk_name = boot_disk_info.source.split('/')[-1]
                            disk_request = compute_v1.GetDiskRequest(project=project_id, zone=zone_name, disk=boot_disk_name)
                            disk_details = disk_client.get(request=disk_request)
                            boot_disk_size_gb = disk_details.size_gb
                            api_disk_type = disk_details.type.split('/')[-1]
                            boot_disk_type = STORAGE_TYPE_MAP.get(api_disk_type, api_disk_type)
                            if disk_details.source_image:
                                os_image = disk_details.source_image.split('/')[-1]
                            elif disk_details.source_snapshot:
                                os_image = f"From Snapshot: {disk_details.source_snapshot.split('/')[-1]}"
                            else:
                                os_image = "Custom/Unknown"
                            snap_request = compute_v1.ListSnapshotsRequest(
                                project=project_id,
                                filter=f'sourceDisk="{disk_details.self_link}"'
                            )
                            for snap in snapshot_client.list(request=snap_request):
                                has_snapshots = True
                                if snap.creation_timestamp > latest_snapshot_timestamp:
                                    latest_snapshot_timestamp = snap.creation_timestamp
                            for policy_url in disk_details.resource_policies:
                                frequency = get_schedule_frequency(resource_policy_client, project_id, policy_url)
                                snapshot_schedules.append(frequency)
                            if has_snapshots and not snapshot_schedules:
                                snapshot_schedules.append("Manually")

                    snapshots_output = "Yes" if has_snapshots else "None"
                    latest_snapshot_date_output = "None"
                    if latest_snapshot_timestamp:
                        parsed_date = datetime.fromisoformat(latest_snapshot_timestamp)
                        latest_snapshot_date_output = parsed_date.strftime("%b %d, %Y")

                    # ── Uptime ──
                    created_time = datetime.fromisoformat(instance.creation_timestamp).astimezone(timezone.utc)
                    uptime_weeks = (datetime.now(timezone.utc) - created_time).days // 7

                    # ── Hostname ──
                    print(f"  Fetching hostname for {instance.name}...")
                    hostname = get_hostname(instance_client, project_id, zone_name, instance.name)

                    # ── CPU & RAM Metrics ──
                    print(f"  Fetching metrics for {instance.name}...")
                    metrics = get_monitoring_metrics(project_id, str(instance.id), zone_name)

                    # ── Application Type ──
                    application_type = determine_application_type(instance.name)

                    vm_details = {
                        "Project ID": project_id,
                        "VM Instance Name": instance.name,
                        "Machine Status": instance.status,
                        "Instance ID": str(instance.id),
                        "Domain": domain,
                        "OS/Image": os_image,
                        "Application Type": application_type,
                        "Environment": environment,
                        "Machine Type": instance.machine_type.split('/')[-1],
                        "vCPU": machine_details.get('vCPU', 'None'),
                        "RAM (GB)": machine_details.get('RAM (GB)', 'None'),
                        "Hostname": hostname,
                        "Storage GB (Boot Disk)": boot_disk_size_gb,
                        "Internal IP": internal_ip,
                        "Storage Type": boot_disk_type,
                        "Target Network Project": target_network_project,
                        "VPC Name": vpc_name,
                        "Subnet Name": subnet_name,
                        "External IP": external_ip,
                        "Snapshots": snapshots_output,
                        "Snapshot Dates": latest_snapshot_date_output,
                        "Snapshot Schedules": ", ".join(snapshot_schedules) if snapshot_schedules else "None",
                        "Uptime (W)": uptime_weeks,
                        "CPU utilization [MEAN]": metrics["cpu"],
                        "RAM usage": metrics["ram"],
                        "Health": "Healthy",
                    }
                    all_vm_details.append(vm_details)

                except Exception as e:
                    print(f"  - Error processing instance {instance.name}: {e}", file=sys.stderr)

        if not all_vm_details:
            print("\nNo processable VM instances found in the project.")
            return

        print(f"\nSuccessfully processed {len(all_vm_details)} VMs. Exporting to {output_file}...")
        df = pd.DataFrame(all_vm_details)

        column_order = [
            "Project ID", "VM Instance Name", "Machine Status", "Instance ID", "Domain", "OS/Image",
            "Application Type", "Environment", "Machine Type", "vCPU", "RAM (GB)", "Hostname",
            "Storage GB (Boot Disk)", "Internal IP", "Storage Type", "Target Network Project",
            "VPC Name", "Subnet Name", "External IP", "Snapshots", "Snapshot Dates",
            "Snapshot Schedules", "Uptime (W)", "CPU utilization [MEAN]", "RAM usage", "Health",
        ]
        df = df[column_order]

        status_map = {
            'RUNNING': '✅ Running',
            'TERMINATED': '■ Stopped',
            'STOPPED': '■ Stopped',
            'SUSPENDED': '■ Stopped',
        }
        df['Machine Status'] = df['Machine Status'].apply(lambda x: status_map.get(x, x))

        def style_status(val):
            if '✅' in str(val): return 'color: green'
            elif '■' in str(val): return 'color: red'
            return ''

        def style_health(val):
            if val == "Healthy": return 'background-color: lightgreen; color: black'
            return ''

        styler = df.style.map(style_status, subset=['Machine Status']) \
                         .map(style_health, subset=['Health'])
        styler.to_excel(output_file, index=False, engine="openpyxl")
        print("Export complete.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="GCP VM Inventory Agent v6.0")
    parser.add_argument("--project_id", required=True, help="The GCP Project ID to scan.")
    parser.add_argument("--output_file", default="gcp_vm_inventory.xlsx", help="Output Excel file path.")
    args = parser.parse_args()
    main(args.project_id, args.output_file)