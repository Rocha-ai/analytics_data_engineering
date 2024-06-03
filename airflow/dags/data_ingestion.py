import os
import logging

from datetime import datetime, timedelta
from airflow import DAG
from airflow.utils.dates import days_ago
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryCreateExternalTableOperator
#from airflow.providers.google.cloud.operators.bigquery import BigQueryCreateExternalTableOperator, BigQueryInsertJobOperator

from google.cloud import storage

import pyarrow as pa
import pyarrow.csv as pv
import pyarrow.parquet as pq
import pandas as pd
import json
import urllib.parse
import requests
from glom import glom

PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET = os.environ.get("GCP_GCS_BUCKET")
API_KEY= os.environ.get("API_KEY")
DATASET = "pa"
BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", 'pa_archive_all')


API_URL = "https://api.purpleair.com/v1/sensors"
#file_template = '{{ execution_date.strftime(\'%Y-%m-%d-%-H\') }}.json.gz'
path_to_local_home = os.environ.get("AIRFLOW_HOME", "/opt/airflow/")
file_template = '{{ execution_date.strftime(\'%Y-%m-%d-%-H\') }}.json'
parquet_file = file_template.replace('.json', '.parquet')

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': days_ago(1),    #datetime(2024, 1, 1)
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    #'retry_delay': timedelta(minutes=5),
}

# Define the query parameters  #"pm2.5_6hour",
_API_FIELDS = [
"latitude",
"longitude",
"humidity",
"pm2.5_60minute",
"temperature",
]
location_type = 0
max_age = 300


def api_url():
    """Returns the download URL for the PurpleAir API."""

    # Convert the fields list to a comma-separated string
    fields_param = ','.join(_API_FIELDS)

    # Define the parameters dictionary
    params = {
        "fields": fields_param,
        "location_type": location_type,
        "max_age": max_age
    }   

    headers = {
    "X-API-Key": str(API_KEY)   
    }
    ########
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

    #########
    response = requests.get(API_URL, headers=headers, params=params)
    filename = f"{path_to_local_home}/{file_template}"
    if response.status_code == 200:
        with open(filename, 'w') as file:
            file.write(response.text)
        print(f"JSON data saved to {filename}")
    else:
        print(f"Failed to retrieve data: {response.status_code}")

    return

def format_to_parquet(src_file):
    if not src_file.endswith('.json'):
        logging.error("Can only accept source files in json format for the moment")
        return
    
    try:
        with open('data.json', 'r') as file:
            json_data = json.load(file)
            print(json_data)
    except FileNotFoundError:
        print("The file 'data.json' was not found.")
    except json.JSONDecodeError:
        print("Failed to decode JSON from the file.")
    # with open(src_file, 'r') as file:
    #     json_data = json.load(file)
    #     print(f"json data is {json_data}")
    # Extract fields and data
    print(glom(json_data, 'fields'))
    fields = glom.glom(json_data, 'fields')
    data = glom.glom(json_data, 'data')
    print(f"the fields glom are{fields}")
    #print(f"the data glom are{data}")

    # Create DataFrame
    df = pd.DataFrame(data, columns=fields)

    # Define the types for each column
    dtypes = {
        "latitude": "string",
        "longitude": "string",
        "humidity": "float64",
        "pm2.5_60minute": "float64",
        "temperature": "float64",
        "sensor_index": "Int64",     
    }

    df.created_at = pd.to_datetime(df.created_at) # make sure that timestamp is correct
    # Set the column types
    df = df.astype(dtypes)
    #save file
    df.to_parquet(src_file.replace('.json', '.parquet'))

def upload_to_gcs(bucket, object_name, local_file):
    """
    Ref: https://cloud.google.com/storage/docs/uploading-objects#storage-upload-object-python
    :param bucket: GCS bucket name
    :param object_name: target path & file-name
    :param local_file: source path & file-name
    :return:
    """
    # WORKAROUND to prevent timeout for files > 6 MB on 800 kbps upload speed.
    # (Ref: https://github.com/googleapis/python-storage/issues/74)
    storage.blob._MAX_MULTIPART_SIZE = 5 * 1024 * 1024  # 5 MB
    storage.blob._DEFAULT_CHUNKSIZE = 5 * 1024 * 1024  # 5 MB
    # End of Workaround

    client = storage.Client()
    bucket = client.bucket(bucket)

    blob = bucket.blob(object_name)
    blob.upload_from_filename(local_file)


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

    format_to_parquet_task = PythonOperator(
            task_id="format_to_parquet_task",
            python_callable=format_to_parquet,
            op_kwargs={
                "src_file": f"{path_to_local_home}/{file_template}",
            },
        )

    local_to_gcs_task = PythonOperator(
        task_id="local_to_gcs_task",
        python_callable=upload_to_gcs,
        op_kwargs={
            "bucket": BUCKET,
            "object_name": f"raw/{parquet_file}",
            "local_file": f"{path_to_local_home}/{parquet_file}",
        },
    )

    gcs_2_bq_ext_task = BigQueryCreateExternalTableOperator(
        task_id=f"bq_{DATASET}_external_table_task",
        table_resource={
            "tableReference": {
                "projectId": PROJECT_ID,
                "datasetId": BIGQUERY_DATASET,
                "tableId": f"{DATASET}_external_table",
            },
            # "schema": {
            #     "fields": schema
            # },
            "externalDataConfiguration": {
                "autodetect": "True",
                "sourceFormat": "PARQUET",
                "sourceUris": [f"gs://{BUCKET}/raw/*"],
            },
        },
    )

fetch_data >> format_to_parquet_task >> local_to_gcs_task >> gcs_2_bq_ext_task