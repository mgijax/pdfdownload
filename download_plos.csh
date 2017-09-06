#!/usr/bin/csh -f

#
# Usage:  download_plos.csh
#
# History
#
# jsb	09/04/2017
#

cd `dirname $0` && source ./Configuration
echo $PDFDOWNLOADLOGDIR

setenv LOG	${PDFDOWNLOADLOGDIR}/`basename $0`.log
rm -rf $LOG
touch $LOG

date | tee -a ${LOG}

# Run the downloader script for default timeframe

./download_plos.py $1 $2 | tee -a ${LOG}

date | tee -a ${LOG}
