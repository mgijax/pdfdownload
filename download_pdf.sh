#!/bin/sh

# Name: download_pdf.sh
# Purpose: Download a single PDF file from a given URL and put it in a given
#	directory.  If the URL refers to a tarred, gzipped directory (rather
#	than a single PDF file), download it, unpackage it, then find and
#	move the PDF file from within it.
# Return Code: 0 if all is well, non-zero if not

USAGE="Usage: $0 <quoted URL> <directory>
"

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
		fail $2
	fi
}

###--- main script ---###

if [ $# -ne 2 ]; then
	echo $USAGE
	fail "bad parameters"
fi

filename=`basename $1`		# name of file to be downloaded
directory=$2			# destination directory for file

if [ ! -d ${directory} ]; then
	echo $USAGE
	fail "Invalid output directory: ${directory}"
fi

# download the file into the directory

curl "$1" > ${directory}/${filename}
exitIfFailed $? "curl failed"

# If we downloaded a tarred, gzipped file (rather than a PDF), there's more
# work to do...

suffix=`echo "${filename##*.}"`
if [ "${suffix}" == "gz" ]; then
	# 1. unzip the file
	# 2. list the files included in the tar file, and identify the PDF
	# 3. extract the PDF
	# 4. move the PDF to the correct directory
	# 5. remove the now-empty directory and the tar file

	gunzip ${directory}/${filename}
	exitIfFailed $? "failed to unzip file"

	# convert the filename from the gzipped name to just the *tar name
	filename=`echo ${filename} | sed 's/.gz$//'`

	pdfPath=`tar --list -f ${directory}/${filename} | grep 'pdf$'`
	if [ "${pdfPath}" != "" ]; then
		tar -x ${pdfPath} -f ${directory}/${filename}
		exitIfFailed $? "failed to pull ${pdfPath} from gzip file"

		mv ${pdfPath} ${directory}
		exitIfFailed $? "failed to move PDF file into directory"

		rm -rf `dirname ${pdfPath}`
		exitItFailed $? "failed to remove empty directory"

		rm ${directory}/${filename}
		exitIfFailed $? "failed to remove tar file"
	else
		fail "no PDF found in gzip file"
	fi
fi
