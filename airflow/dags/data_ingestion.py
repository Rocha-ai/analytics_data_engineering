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
import urllib.parse
import requests

PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET = os.environ.get("GCP_GCS_BUCKET")
API_KEY= os.environ.get("API_KEY")
DATASET = "pa"
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", 'pa_archive_all')


API_URL = "https://api.purpleair.com/v1/sensors"
#file_template = '{{ execution_date.strftime(\'%Y-%m-%d-%-H\') }}.json.gz'
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
    "latitude",
    "longitude",
    "humidity",
    "pm2.5_60minute",
    #"pm2.5_6hour",
    "last_seen",
]




def api_url():
    """Returns the download URL for the PurpleAir API."""


    # url = str(API_URL + "?" + urllib.parse.urlencode({
    #     "fields=": ",".join(_API_FIELDS)
    #     # "max_age": 300,      
    #     # "location_type": 0,  # Outside sensors only
        
    # }))
    #print(f" url is {url}")
    print(f" api is {API_KEY}")

    # Define the query parameters  #"pm2.5_6hour",
    _API_FIELDS = [
    "latitude",
    "longitude",
    "humidity",
    "pm2.5_60minute",
    "last_seen",
    ]
    location_type = 0
    max_age = 300

    # Convert the fields list to a comma-separated string
    fields_param = ','.join(_API_FIELDS)

    # Define the parameters dictionary
    params = {
        "fields": fields_param,
        "location_type": location_type,
        "max_age": max_age
    }   

    headers = {
    "X-API-Key": str(API_KEY)    #f"Bearer {API_KEY}"
    }
    #####
    req = requests.Request('GET', API_URL, headers=headers, params=params)

    # Prepare the request
    prepared = req.prepare()

    # Print the full URL and headers of the prepared request
    print("Full URL:", prepared.url)
    print("Headers:", prepared.headers)

    # Send the actual request and get the response
    with requests.Session() as session:
        response = session.send(prepared)

    # Optional: Check the response status and content
    print("Status Code:", response.status_code)
    print("Response Content:", response.text)

    #####
    response = requests.get(API_URL, headers=headers, params=params)
    filename = f"{path_to_local_home}/{file_template}"
    if response.status_code == 200:
        with open(filename, 'w') as file:
            file.write(response.text)
        print(f"JSON data saved to {filename}")
    else:
        print(f"Failed to retrieve data: {response.status_code}")

    return

with DAG(
    'purpleair_api_dag',
    default_args=default_args,
    description='DAG to fetch data from PurpleAir API',
    schedule_interval='@hourly',  #Run once an hour at the beginning of the hour
) as dag:

    fetch_data = PythonOperator(
            task_id="fetch_data",
            python_callable=api_url,
        # op_kwargs={
        #     "src_file": f"{path_to_local_home}/{dataset_file}",
        # },
     )

    # format_to_parquet_task = PythonOperator(
    #         task_id="format_to_parquet_task",
    #         python_callable=format_to_parquet,
    #         op_kwargs={
    #             "src_file": f"{path_to_local_home}/{dataset_file}",
    #         },
    #     )

    # fetch_data = BashOperator(
    #     task_id='fetch_purpleair_data',
    #     bash_command=f'curl -sSLf "{api_url_value}" -o {path_to_local_home}/{file_template}',
    #     dag=dag,
    # )

#   fetch_data >> format_to_parquet_task