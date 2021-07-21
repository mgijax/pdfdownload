#!/usr/bin/sh

# Usage:  identify_missed_papers_plos.sh
#
# History
#
# jsb	09/07/2017

cd `dirname $0`
. ./Configuration

# if we don't have a log directory, create one
if [ ! -d ${PDFDOWNLOADLOGDIR} ]; then
	mkdir ${PDFDOWNLOADLOGDIR}
fi
 
# just replace any prior version of this script's log file
LOG=${PDFDOWNLOADLOGDIR}/`basename $0`.log
if [ -e $LOG ]; then
	rm $LOG
fi
touch $LOG

date | tee -a ${LOG}

# Run the identification script for default timeframe (passing in dates if specified)

cd pmc
${PYTHON} ./identify_missed_papers_plos.py $1 $2 | tee -a ${LOG}
cd ..

date | tee -a ${LOG}
