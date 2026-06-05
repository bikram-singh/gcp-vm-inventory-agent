# push_to_bigquery.py
# ─────────────────────────────────────────────────────────────────────────────
# Pushes VM inventory data from gcp_vm_inventory.py into a BigQuery table.
# Table: <project_id>.vm_inventory.vm_details
# Each run appends a new partition snapshot (date-stamped rows).
# ─────────────────────────────────────────────────────────────────────────────

import sys
from datetime import datetime, timezone

import pandas as pd
from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPICallError

DATASET_ID = "vm_inventory"
TABLE_ID   = "vm_details"

# BigQuery schema — maps exactly to gcp_vm_inventory.py column_order
BQ_SCHEMA = [
    bigquery.SchemaField("snapshot_date",          "DATE",    "REQUIRED"),
    bigquery.SchemaField("project_id",             "STRING",  "NULLABLE"),
    bigquery.SchemaField("vm_instance_name",       "STRING",  "NULLABLE"),
    bigquery.SchemaField("machine_status",         "STRING",  "NULLABLE"),
    bigquery.SchemaField("instance_id",            "STRING",  "NULLABLE"),
    bigquery.SchemaField("domain",                 "STRING",  "NULLABLE"),
    bigquery.SchemaField("os_image",               "STRING",  "NULLABLE"),
    bigquery.SchemaField("application_type",       "STRING",  "NULLABLE"),
    bigquery.SchemaField("environment",            "STRING",  "NULLABLE"),
    bigquery.SchemaField("machine_type",           "STRING",  "NULLABLE"),
    bigquery.SchemaField("vcpu",                   "INTEGER", "NULLABLE"),
    bigquery.SchemaField("ram_gb",                 "FLOAT",   "NULLABLE"),
    bigquery.SchemaField("hostname",               "STRING",  "NULLABLE"),
    bigquery.SchemaField("storage_gb_boot_disk",   "INTEGER", "NULLABLE"),
    bigquery.SchemaField("internal_ip",            "STRING",  "NULLABLE"),
    bigquery.SchemaField("storage_type",           "STRING",  "NULLABLE"),
    bigquery.SchemaField("target_network_project", "STRING",  "NULLABLE"),
    bigquery.SchemaField("vpc_name",               "STRING",  "NULLABLE"),
    bigquery.SchemaField("subnet_name",            "STRING",  "NULLABLE"),
    bigquery.SchemaField("external_ip",            "STRING",  "NULLABLE"),
    bigquery.SchemaField("snapshots",              "STRING",  "NULLABLE"),
    bigquery.SchemaField("snapshot_dates",         "STRING",  "NULLABLE"),
    bigquery.SchemaField("snapshot_schedules",     "STRING",  "NULLABLE"),
    bigquery.SchemaField("uptime_weeks",           "INTEGER", "NULLABLE"),
    bigquery.SchemaField("cpu_utilization_mean",   "STRING",  "NULLABLE"),
    bigquery.SchemaField("ram_usage",              "STRING",  "NULLABLE"),
    bigquery.SchemaField("health",                 "STRING",  "NULLABLE"),
]

# Column name mapping: Excel → BigQuery field names
COLUMN_MAP = {
    "Project ID":               "project_id",
    "VM Instance Name":         "vm_instance_name",
    "Machine Status":           "machine_status",
    "Instance ID":              "instance_id",
    "Domain":                   "domain",
    "OS/Image":                 "os_image",
    "Application Type":         "application_type",
    "Environment":              "environment",
    "Machine Type":             "machine_type",
    "vCPU":                     "vcpu",
    "RAM (GB)":                 "ram_gb",
    "Hostname":                 "hostname",
    "Storage GB (Boot Disk)":   "storage_gb_boot_disk",
    "Internal IP":              "internal_ip",
    "Storage Type":             "storage_type",
    "Target Network Project":   "target_network_project",
    "VPC Name":                 "vpc_name",
    "Subnet Name":              "subnet_name",
    "External IP":              "external_ip",
    "Snapshots":                "snapshots",
    "Snapshot Dates":           "snapshot_dates",
    "Snapshot Schedules":       "snapshot_schedules",
    "Uptime (W)":               "uptime_weeks",
    "CPU utilization [MEAN]":   "cpu_utilization_mean",
    "RAM usage":                "ram_usage",
    "Health":                   "health",
}


def ensure_dataset_and_table(client: bigquery.Client, project_id: str):
    """Creates the dataset and partitioned table if they don't already exist."""
    dataset_ref = bigquery.DatasetReference(project_id, DATASET_ID)

    # Create dataset
    try:
        client.get_dataset(dataset_ref)
        print(f"  Dataset '{DATASET_ID}' already exists.")
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        dataset.description = "GCP VM Inventory — daily snapshots"
        client.create_dataset(dataset, exists_ok=True)
        print(f"  Created dataset '{DATASET_ID}'.")

    # Create table with date partitioning
    table_ref = dataset_ref.table(TABLE_ID)
    try:
        client.get_table(table_ref)
        print(f"  Table '{TABLE_ID}' already exists.")
    except Exception:
        table = bigquery.Table(table_ref, schema=BQ_SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="snapshot_date",
        )
        table.description = "Daily VM inventory snapshots from GCP Compute Engine"
        client.create_table(table)
        print(f"  Created partitioned table '{TABLE_ID}'.")

    return table_ref


def push_to_bigquery(project_id: str, excel_file: str) -> str:
    """
    Reads the VM inventory Excel file and pushes the data to BigQuery.

    Args:
        project_id: GCP project where BigQuery dataset will be created.
        excel_file: Path to the Excel file generated by gcp_vm_inventory.py.

    Returns:
        Status message.
    """
    import os
    if not os.path.exists(excel_file):
        return f"❌ Excel file not found: {excel_file}. Run fetch_vm_inventory first."

    print(f"Reading Excel: {excel_file}")
    try:
        df = pd.read_excel(excel_file)
    except Exception as e:
        return f"❌ Could not read Excel file: {e}"

    if df.empty:
        return "ℹ️  No data found in Excel file — nothing to push."

    # ── Force STRING columns BEFORE rename (while still using Excel column names) ──
    # instance_id comes from GCP as a large int64 — must be string for BQ
    string_cols_excel = [
        "Instance ID", "Internal IP", "External IP",
        "VPC Name", "Subnet Name", "Target Network Project",
        "Snapshot Dates", "Snapshot Schedules",
    ]
    for col in string_cols_excel:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: str(int(x)) if pd.notna(x) and isinstance(x, float) and x == int(x)
                else (str(x) if pd.notna(x) else None)
            )

    # Rename columns
    df = df.rename(columns=COLUMN_MAP)

    # Add snapshot date
    today = datetime.now(timezone.utc).date()
    df.insert(0, "snapshot_date", today)

    # Clean up status emojis from Machine Status
    df["machine_status"] = df["machine_status"].astype(str).str.replace(
        r"[✅■💤⚠️]", "", regex=True
    ).str.strip()

    # Convert INTEGER columns safely
    for col in ["vcpu", "storage_gb_boot_disk", "uptime_weeks"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    # Convert FLOAT columns safely
    for col in ["ram_gb"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Ensure all STRING BQ columns are actually strings (not int64/float)
    string_cols_bq = [
        "project_id", "vm_instance_name", "machine_status", "instance_id",
        "domain", "os_image", "application_type", "environment",
        "machine_type", "hostname", "internal_ip", "storage_type",
        "target_network_project", "vpc_name", "subnet_name", "external_ip",
        "snapshots", "snapshot_dates", "snapshot_schedules",
        "cpu_utilization_mean", "ram_usage", "health",
    ]
    for col in string_cols_bq:
        if col in df.columns:
            df[col] = df[col].astype(object).where(df[col].notna(), None)
            df[col] = df[col].apply(lambda x: str(x) if x is not None else None)

    # Replace None/NaN strings with actual None
    df = df.replace({"None": None, "nan": None, "": None})

    print(f"Connecting to BigQuery project: {project_id}")
    try:
        client = bigquery.Client(project=project_id)
    except Exception as e:
        return f"❌ Could not create BigQuery client: {e}"

    print("Ensuring dataset and table exist...")
    try:
        table_ref = ensure_dataset_and_table(client, project_id)
    except Exception as e:
        return f"❌ Failed to create dataset/table: {e}"

    # ── Delete today rows to prevent duplicates ──
    table_full = "{}.{}.{}".format(project_id, DATASET_ID, TABLE_ID)
    delete_query = "DELETE FROM `{}` WHERE snapshot_date = '{}' AND project_id = '{}'".format(
        table_full, today, project_id
    )
    try:
        print("Removing existing rows for {} to prevent duplicates...".format(today))
        client.query(delete_query).result()
        print("  Done.")
    except Exception as e:
        print("  Note: Could not delete existing rows: {}".format(e))

    # Load data
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    print("Pushing {} rows to BigQuery...".format(len(df)))
    try:
        load_job = client.load_table_from_dataframe(
            df, table_ref, job_config=job_config
        )
        load_job.result()  # Wait for job to complete
        table = client.get_table(table_ref)
        return (
            f"✅ Successfully pushed {len(df)} VM(s) to BigQuery!\n"
            f"   Table  : {project_id}.{DATASET_ID}.{TABLE_ID}\n"
            f"   Date   : {today}\n"
            f"   Total rows in table: {table.num_rows}\n"
            f"   Query in BigQuery console:\n"
            f"   SELECT * FROM `{project_id}.{DATASET_ID}.{TABLE_ID}`\n"
            f"   WHERE snapshot_date = '{today}'"
        )
    except Exception as e:
        return f"❌ BigQuery load failed: {e}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Push VM inventory to BigQuery")
    parser.add_argument("--project_id",  required=True, help="GCP Project ID")
    parser.add_argument("--excel_file",  required=True, help="Path to Excel file")
    args = parser.parse_args()
    result = push_to_bigquery(args.project_id, args.excel_file)
    print(result)