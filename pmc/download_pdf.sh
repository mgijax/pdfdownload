#!/bin/sh

# Name: download_pdf.sh
# Purpose: Download a single PDF file from a given URL and put it in a given
#	directory.  If the URL refers to a tarred, gzipped directory (rather
#	than a single PDF file), download it, unpackage it, then find and
#	move the PDF file from within it.
# Return Code: 0 if all is well, non-zero if not
# jak, 8/20/2018, adapted from
#   https://github.com/mgijax/pdfdownload/blob/master/download_plos.py
#   changed to take a 3rd param for the PDF file name and to work on MacOS

USAGE="Usage: $0 <quoted URL> <directory> <final PDF filename>
"
# Example
# download_pdf.sh 'https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/07/07/PMC3519825.tar.gz' dataDir PMC351925.pdf

###--- functions ---###

# echo an error message to stdout and exit with an error code of 1
# takes one parameters:
#    $1 - error message to echo
fail () {
	echo "Error: $1"
	exit 1
}

# verify that the previous operation succeeded, and if not, bail out.
# takes two parameters:
#    $1 - exit code we'd like to ensure is 0
#    $2 - error message to echo if $1 is non-zero
exitIfFailed () {
	if [ $1 -ne 0 ]; then
		fail "Exit code: $1 Msg: $2"
	fi
}

###--- main script ---###

if [ $# -ne 3 ]; then
	echo $USAGE
	fail "bad parameters"
fi

filename=`basename $1`		# basename of file to be downloaded
directory=$2			# destination directory for file
finalPDFname=$3			# basename of the downloaded PDF

if [ ! -d ${directory} ]; then
	echo $USAGE
	fail "Invalid output directory: ${directory}"
fi

# download the file into the directory

/usr/bin/curl $1 > ${directory}/${filename}
if [ $? -ne 0 ]; then
      #echo "curl failed, removing: ${directory}/${filename}"
      rm -rf ${directory}/${filename}
      exitIfFailed $? "curl did not complete, removing ${directory}/${filename}"
fi

# If we downloaded a tarred, gzipped file (rather than a PDF), there's more
# work to do...

# "Find Shortest" filename alias. Sorts by filename length, shortest 1st
#  this works on MacOS
#alias fs="awk '{x = length(\$0); print x, \$0}' | sort -n | sed 's/^[0-9][0-9]* //'"

suffix=`echo "${filename##*.}"`
if [ "${suffix}" == "gz" ]; then
	# 1. unzip the file
	# 2. list the files included in the tar file, and identify the PDF
	# 3. extract the PDF
	# 4. move the PDF to the correct directory
	# 5. remove the now-empty directory and the tar file

	gunzip -f ${directory}/${filename}
	#exitIfFailed $? "failed to unzip file"

        if [ $? -ne 0 ]; then
              ret=$?
              #echo "before rm failed to unzip: ${directory}/${filename}"
              rm -f ${directory}/${filename}
              exitIfFailed ret "failed to unzip file ${directory}/${filename}"
        fi

	# convert the filename from the gzipped name to just the *tar name
	filename=`echo ${filename} | sed 's/.gz$//'`

	cwd=`pwd`
	# Finding PDF article filename in the tar is complicated as many
	#    supp data files are also PDFs
	# The logic for finding the article PDF is in find_pdf_in_tar.py
	pdfPath=`tar tvf ${directory}/${filename} | ${PYTHON} ${cwd}/find_pdf_in_tar.py`

	if [ "${pdfPath}" != "" ]; then
		# Linux: tar -x ${pdfPath} -f ${directory}/${filename}
		#     This doesn't work in MacOS tar
		# This works for both:
		#     tar -xf filename ${pdfPath}
		cd ${directory}		# so we do all unpacking in $dir not .
		tar -xf ${filename} ${pdfPath}
		exitIfFailed $? "failed to pull ${pdfPath} from gzip file"

		mv ${pdfPath} ${finalPDFname}
		exitIfFailed $? "failed to move PDF file into directory"

		rm -rf `dirname ${pdfPath}`
		exitIfFailed $? "failed to remove empty directory"

		rm ${filename}
		exitIfFailed $? "failed to remove tar file"
	else
		rm -rf ${directory}/${filename}
		fail "no PDF found in gzip file"
	fi
elif [ "$suffix" == "pdf" -o "$suffix" == "PDF" ]; then 
    mv ${directory}/${filename} ${directory}/${finalPDFname}
    exitIfFailed $? "failed to rename downloaded PDF"
else
    fail "downloaded file has bad file extension"
fi
