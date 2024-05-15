import os
import logging

from datetime import datetime, timedelta
from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
#from airflow.providers.google.cloud.operators.bigquery import BigQueryCreateExternalTableOperator, BigQueryInsertJobOperator

from google.cloud import storage

import pyarrow as pa
import pyarrow.csv as pv
import pyarrow.parquet as pq
import pandas as pd
import json

PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET = os.environ.get("GCP_GCS_BUCKET")
API_KEY= os.environ.get("API_KEY")
DATASET = "pa"
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", 'pa_archive_all')


API_URL = "https://api.purpleair.com/v1/sensors"
file_template = '{{ execution_date.strftime(\'%Y-%m-%d-%-H\') }}.json.gz'
#url = url_prefix + file_template
path_to_local_home = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")
file_template = '{{ execution_date.strftime(\'%Y-%m-%d-%-H\') }}.json'

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': days_ago(1),    #datetime(2024, 1, 1)
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    #'retry_delay': timedelta(minutes=5),
}


_API_FIELDS = [
    "sensor_index",
    "latitude",
    "longitude",
    "humidity",
    "pm2.5_60minute",
    "pm2.5_6hour",
    "last_seen",
]

def api_url():
    """Returns the download URL for the PurpleAir API."""
    return API_URL + "?" + API_KEY + urllib.parse.urlencode({
        "max_age": 300,      
        "location_type": 0,  # Outside sensors only
        "fields": ",".join(_API_FIELDS)
    })

api_url_value = api_url()

dag = DAG(
    'purpleair_api_dag',
    default_args=default_args,
    description='DAG to fetch data from PurpleAir API',
    schedule_interval=timedelta(days=1),
)

fetch_data = BashOperator(
    task_id='fetch_purpleair_data',
    bash_command=f'curl -sSLf "{api_url_value}" -o {path_to_local_home}/{file_template}',
    dag=dag,
)