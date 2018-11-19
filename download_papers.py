#!/usr/local/bin/python

# Name: download_papers.py
# Purpose: Download PDFs from PubMed Central for the preceding sixty days.  This includes papers where:
#   1. title, abstract, or body contain "mice"
#   2. journal is one of those specified in the 'journals' global variable
#   3. issue and journal are non-null (to avoid uncorrected proofs)
#   4. the DOI ID is not already in MGI
# Notes: Destination folder of PDFs is pulled from configuration.  There is some lag time
#    between when papers are published and when they are available for download, and that
#    lag appears to be non-standard, so we allow a two month cushion in hopes to catch
#    all relevant papers eventually.
#
# Implementation history
#
# 10/23/18 - jsb
#    updated to pull in six new journals' papers and to handle PLOS papers the same way
#    (rather than querying the PLOS site itself)
# 12/5/17 - sc
#	TR12737 removed PLOS Pathogens

import sys
sys.path.insert(0, '/usr/local/mgi/live/lib/python')
sys.path.insert(0, './lib/python')

USAGE = '''Usage: %s [yyyy-mm-dd] [yyyy-mm-dd] ['journal name']
    The default behavior (no parameters) is to get files for the sixty days
    preceding today for all nine allowed journals.  If you specify dates, you
    must specify both.  The first is the start date and the second is the
    end date, both inclusive.  If you specify a journal name, it is case-
    sensitive, should be enclosed in quotes, and must be one of the 
    journals for which we usually search.
''' % sys.argv[0]

import os 
import re
import time
import caches
import backPopulate

###--- setup ---###

for envVar in [ 'PG_DBSERVER', 'PG_DBNAME', 'MGI_PUBLICUSER', 'MGI_PUBLICPASSWORD', 'PDFDIR', 'WINDOW_SIZE' ]:
    if envVar not in os.environ:
        raise Exception('Missing environment variable: %s' % envVar)

caches.initialize(os.environ['MGI_PUBLICUSER'], os.environ['MGI_PUBLICPASSWORD'],
    os.environ['PG_DBSERVER'], os.environ['PG_DBNAME'])

###--- Globals ---###

# which journals do we want to search?
journals = [ 'Aging Cell', 'Cilia', 'Dis Model Mech', 'Nucleic Acids Res', 'Cell Death Differ', 'J Lipid Res',
    'PLOS ONE', 'PLOS Genetics', 'PLOS Biology']

# number of days to look back to try to find articles (due to delay in transfer from journals to PubMed Central)
windowSize = int(os.environ['WINDOW_SIZE'])

###--- functions ---###

def bailout (error, showUsage = False):
    # Purpose: exit the script, giving an error message, and (optionally) showing the usage statement
    
    if showUsage:
        sys.stderr.write(USAGE)
    sys.stderr.write('Error: %s\n' % error)
    sys.exit(1)
    
def parseParameters():
    # Purpose: get the start and stop dates for the download
    # Returns: (start date, stop date)
    # Effects: modifies global 'journals' if a single journal is specified on the command-line
    # Throws: nothing
    # Notes: The stop date is midnight today, while the start date is midnight 'windowSize' days before.
    
    global journals
    
    # if the user specified a single journal to search, strip it from the parameters and update the global
    # list of journals to process
    
    if sys.argv[-1] in journals:
        journals = [ sys.argv[-1] ]
        sys.argv = sys.argv[:-1]

    elif sys.argv[-1] == '':            # empty string comes in if no journal specified; remove it
        sys.argv = sys.argv[:-1]
        
    if len(sys.argv) > 1:
        if len(sys.argv) != 3:
            bailout('Wrong number of parameters', True)

        startDate = sys.argv[1].strip()
        stopDate = sys.argv[2].strip()
        
        dateRE = re.compile('^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
        if not dateRE.match(startDate):
            bailout('Invalid start date: %s' % startDate)
        if not dateRE.match(stopDate):
            bailout('Invalid stop date: %s' % stopDate)
            
    else:
        # 24 hours per day, 60 minutes per hour, 60 seconds per minute
        startDate = time.strftime("%Y-%m-%d", time.localtime(time.time() - windowSize * 24 * 60 * 60))
        stopDate =  time.strftime("%Y-%m-%d", time.localtime(time.time()))

    return (startDate, stopDate)

###--- main program ---###

if __name__ == '__main__':
    startDate, stopDate = parseParameters()
    
    config = backPopulate.Config()
    config.setBasePath(os.environ['PDFDIR'])
    config.setJournals(journals)
    config.setDateRange('%s:%s' % (startDate.replace('-', '/'), stopDate.replace('-', '/')))
    config.setVerbose(False)
    
    if 'PDFDOWNLOADLOGDIR' in os.environ:
        noPdfFile = os.path.join(os.environ['PDFDOWNLOADLOGDIR'], 'noPdfs.log')
        config.setNoPdfFile(noPdfFile)
    else:
        raise Exception('Must define PDFDOWNLOADLOGDIR')
    
    backPopulate.process(config)
