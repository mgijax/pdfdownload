#!/usr/bin/env python3

# Name: download_elsevier_papers.py
# Purpose: download PDF papers for the preceding 60 days for a set of selected journals from Elsevier's SciDirect collection
# Notes: 1. based on work in the MGIJax/elsevier_client GitHub product
#    2. Destination folder of PDFs is pulled from configuration.
#    3. The SciDirect API does not allow an end date when searching by date, only a start date.  So, if we are to implement
#        an end date, we'll need to do that in code in this script.

import sys
sys.path.insert(0, '../shared')

import os
import json
import re
import time
import caches
from SciDirectLib import ElsClient, SciDirectSearch, SciDirectReference

USAGE = '''Usage: %s [yyyy-mm-dd] [yyyy-mm-dd] ['journal name']
    The default behavior (no parameters) is to get files for the sixty days
    preceding today for all 17 allowed journals.  If you specify dates, you
    must specify both.  The first is the start date and the second is the
    end date, both inclusive.  If you specify a journal name, it is case-
    sensitive, should be enclosed in quotes, and must be one of the 
    journals for which we usually search.
''' % sys.argv[0]

###--- setup ---###

windowSize = 60         # number of days to search

for envVar in [ 'PG_DBSERVER', 'PG_DBNAME', 'MGI_PUBLICUSER', 'MGI_PUBLICPASSWORD', 'PDFDIR', 'WINDOW_SIZE' ]:
    if envVar not in os.environ:
        raise Exception('Missing environment variable: %s' % envVar)

caches.initialize(os.environ['MGI_PUBLICUSER'], os.environ['MGI_PUBLICPASSWORD'],
    os.environ['PG_DBSERVER'], os.environ['PG_DBNAME'])

# Load API key and Jax institution token from config file
apikey = os.environ['ELSEVIER_APIKEY']
insttoken = os.environ['ELSEVIER_INSTTOKEN']

###--- journal definitions ---###

class Journal(object):  # simple journal struct
    def __init__(self, mgiName, elsevierName):
        self.mgiName = mgiName
        self.elsevierName = elsevierName

journals = [
    Journal('Arch Biochem Biophys', 'Archives of Biochemistry and Biophysics'),
    Journal('Dev Biol', 'Developmental Biology'),
    Journal('J Mol Cell Cardiol','Journal of Molecular and Cellular Cardiology'),
    Journal('Brain Research', 'Brain Research'),
    Journal('Experimental Cell Research', 'Experimental Cell Research'),
    Journal('Experimental Neurology', 'Experimental Neurology'),
    Journal('Neuron', 'Neuron'),
    Journal('Neurobiology of Disease', 'Neurobiology of Disease'),
    Journal('Bone', 'Bone'),
    Journal('Neurosci Letters', 'Neuroscience Letters'),
    Journal('J Invest Dermatol', 'Journal of Investigative Dermatology'),
    Journal('Cancer Cell', 'Cancer Cell'),
    Journal('Cancer Lett', 'Cancer Letters'),
    Journal('Neuroscience', 'Neuroscience'),
    Journal('Neurobiology of Aging', 'Neurobiology of Aging'),
    Journal('Matrix Biology', 'Matrix Biology'),
    Journal('J Bio Chem', 'Journal of Biological Chemistry'),
   ]

###--- functions ---###

def bailout (error, showUsage = False):
    # Purpose: exit the script, giving an error message, and (optionally) showing the usage statement
    
    if showUsage:
        sys.stderr.write(USAGE)
    sys.stderr.write('Error: %s\n' % error)
    sys.exit(1)

def parseParameters():
    # Purpose: get the start and stop dates for the download, narrow the set of journals to search(if needed)
    # Returns: (start date, stop date)
    # Effects: modifies global 'journals' if a single journal is specified on the command-line
    # Throws: nothing
    # Notes: By default, the stop date is midnight today, while the start date is midnight 'windowSize' days before.
    
    global journals
    
    # if the user specified a single journal to search, strip it from the parameters and update the global
    # list of journals to process
    
    if sys.argv[-1] != '':
        keep = []
        for journal in journals:
            if sys.argv[-1] == journal.mgiName:
                keep.append(journal)
                break
        journals = keep

        if not journals:
            bailout('Unrecognized journal: "%s"' % sys.argv[-1], True)

        journals = [ sys.argv[-1] ]
        sys.argv = sys.argv[:-1]

    else:
        # Empty string comes in if no journal specified; remove it and keep list of all journals as-is.
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
    