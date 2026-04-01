#
# For testing boto3 with PMC
#

import boto3
from botocore import UNSIGNED
from botocore.config import Config

# 1. Initialize S3 client without credentials for public access
s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

bucket_name = 'pmc-oa-opendata'
# 2. Example Key: OA_comm/all/PMC7xxxxxx/PMC7123456.pdf
object_key = 'PMC12930826.1/PMC12930826.1.pdf' 
local_file_name = 'lec.pdf'

# 3. Download the PDF file
try:
    print(f"Downloading {object_key}...")
    s3.download_file(bucket_name, object_key, local_file_name)
    print(f"Downloaded to {local_file_name}")
except Exception as e:
    print(f"Error: {e}")
