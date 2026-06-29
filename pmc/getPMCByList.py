#
# For testing boto3 with PMC
#
# to test from command line:
# aws --no-sign-request s3 cp s3://pmc-oa-opendata/PMC12930826.1/PMC12930826.1.pdf .
#

import boto3
from botocore import UNSIGNED
from botocore.config import Config

# 1. Initialize S3 client without credentials for public access
s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

bucket_name = 'pmc-oa-opendata'
# 2. Example Key: OA_comm/all/PMC7xxxxxx/PMC7123456.pdf
#object_key = 'PMC12930826.1/PMC12930826.1.pdf' 
#object_key = 'PMC12930826.1/PMC12930826.1.pdf' 

fp = open('PMC.csv', 'r')
for line in fp.readlines():
    tokens = line[:-1].split(',')
    object_key = tokens[1] + '.1/' + tokens[1] + '.1.pdf' 
    local_file_name = '/mgi/all/wts2_projects/1800/WTS2-1869/' + tokens[0] + '.pdf'
    print(object_key, tokens[1], local_file_name)

    try:
       s3.download_file(bucket_name, object_key, local_file_name)
    except:
       print('could not find:', object_key)

fp.close()
