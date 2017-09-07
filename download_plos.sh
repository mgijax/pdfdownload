#!/usr/bin/sh

# Usage:  download_plos.csh
#
# History
#
# jsb	09/04/2017

cd `dirname $0`
. ./Configuration

# if we don't have a log directory, create one
if [ ! -d ${PDFDOWNLOADLOGDIR} ]; then
	mkdir ${PDFDOWNLOADLOGDIR}
fi
 
# remove log files older than 90 days
find ${PDFDOWNLOADLOGDIR}/* -type f -mtime +90 -exec rm -rf {} \;

# if we have a current log file, rename it with a date/time and start a new one
LOG=${PDFDOWNLOADLOGDIR}/`basename $0`.log
if [ -e $LOG ]; then
	mv $LOG $LOG.`date '+%Y%m%d.%H%M'` | tee -a ${LOG}
fi
touch $LOG

date | tee -a ${LOG}

# Run the downloader script for default timeframe (passing in dates if specified)

./download_plos.py $1 $2 | tee -a ${LOG}

date | tee -a ${LOG}
