#
# Get PMC by a List
#

import boto3
from botocore import UNSIGNED
from botocore.config import Config

# 1. Initialize S3 client without credentials for public access
s3 = boto3.client('s3', config=Config(signature_version=UNSIGNED))

# copy to WTS2 ticket folder
local_file_name = '/mgi/all/wts2_projects/1800/WTS2-1869/' + tokens[0] + '.pdf'

# use a list of pmid,pmc (40475700,PMC12138534)
fp = open('PMC.csv', 'r')
for line in fp.readlines():
    tokens = line[:-1].split(',')
    object_key = tokens[1] + '.1/' + tokens[1] + '.1.pdf' 
    #print(object_key, tokens[1], local_file_name)

    try:
       s3.download_file('pmc-oa-opendata, object_key, local_file_name)
    except:
       print(object_key)
fp.close()
