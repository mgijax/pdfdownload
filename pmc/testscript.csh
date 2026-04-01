#!/bin/csh -f

#
# To test old/new pdfdownload
# Simply compare old pdfs with new pdfs
#


rm -rf /data/loads/_New_Newcurrent/embargo_PDF_download*
rm -rf /data/loads/_New_Newcurrent/pdfdownload*
rm -rf /data/loads/lec/mgi/pdfdownload/logs*
mkdir /data/loads/_New_Newcurrent/embargo_PDF_download
mkdir /data/loads/_New_Newcurrent/pdfdownload
mkdir /data/loads/lec/mgi/pdfdownload/logs
cd /home/lec/mgi/pdfdownload.lec
./download_pmc_papers.sh
mv /data/loads/_New_Newcurrent/embargo_PDF_download /data/loads/_New_Newcurrent/embargo_PDF_download.old
mkdir /data/loads/_New_Newcurrent/embargo_PDF_download
mv /data/loads/_New_Newcurrent/pdfdownload /data/loads/_New_Newcurrent/pdfdownload.old
mkdir /data/loads/_New_Newcurrent/pdfdownload
mv /data/loads/lec/mgi/pdfdownload/logs /data/loads/lec/mgi/pdfdownload/logs.old
mkdir /data/loads/lec/mgi/pdfdownload/logs
cd /home/lec/mgi/pdfdownload
download_pmc_papers.sh
cd /data/loads/_New_Newcurrent
diff embargo_PDF_download embargo_PDF_download.old
diff pdfdownload pdfdownload.old

