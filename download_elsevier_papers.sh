#!/usr/bin/sh

# Usage:  download_elsevier_papers.sh
#
# History
#
# lec	06/02/2025
#	to run just the Elsevier
#

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

# Run the downloader scripts for default timeframe (passing in dates if specified)

export PDFDOWNLOADLOGDIR

CWD=`pwd`

# do Elsevier's SciDirect
cd elsevier
${PYTHON} ./download_elsevier_papers.py $1 $2 "$3" 2>&1 | tee -a ${LOG}
cd ${CWD}

date | tee -a ${LOG}

# mail the two noPdf logs to Nancy for manual processing
if [ "${MAIL_LOG_CUR}" != "" ]; then
    if [ `hostname` = "bhmgiapp01" ]; then
	for i in `echo ${MAIL_LOG_CUR} | sed 's/,/ /g'`
	do
		if [ -f ${PDFDOWNLOADLOGDIR}/noPdfs_elsevier.log ]; then
			mailx -s "pdfdownload - No PDF Log" ${MAIL_LOG_CUR} < ${PDFDOWNLOADLOGDIR}/noPdfs_elsevier.log
		else
			echo "No ${PDFDOWNLOADLOGDIR}/noPdfs_elsevier.log to email" | tee -a ${LOG}
		fi

		if [ -f ${PDFDOWNLOADLOGDIR}/embargoedNoPdfs_elsevier.log ]; then
			mailx -s "pdfdownload - No PDF Log (Embargoed Journals)" ${MAIL_LOG_CUR} < ${PDFDOWNLOADLOGDIR}/embargoedNoPdfs_elsevier.log
		else
			echo "No ${PDFDOWNLOADLOGDIR}/embargoedNoPdfs_elsevier.log to email" | tee -a ${LOG}
		fi
	done
    fi
fi
