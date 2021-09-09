#!/usr/bin/env python3

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
# 5/11/20 - jak
#       TR13204 conversion to python 3.7
# 10/23/18 - jsb
#    updated to pull in six new journals' papers and to handle PLOS papers the same way
#    (rather than querying the PLOS site itself)
# 12/5/17 - sc
#	TR12737 removed PLOS Pathogens

import sys
sys.path.insert(0, '../shared')

USAGE = '''Usage: %s [yyyy-mm-dd] [yyyy-mm-dd] ['journal name']
    The default behavior (no parameters) is to get files for the sixty days
    preceding today for all ten allowed journals.  If you specify dates, you
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

# which journals do we want to search?  (All are immediate, open-access.  Embargoed journals are below.)
journals = [
    'Acta Neuropathol Commun',
    'Aging (Albany NY)',
    'Aging Cell',
    'Biol Open',
    'Biomed Res Int',
    'Biomolecules',
    'Biosci Rep',
    'Blood Adv',
    'BMC Genomics',
    'BMC Res Notes',
    'Cancer Sci',
    'Cell Death Dis',
    'Cell Mol Gastroenterol Hepatol',
    'Cells',
    'Commun Biol',
    'Dis Model Mech',
    'EBioMedicine',
    'eLife',
    'EMBO Mol Med',
    'eNeuro',
    'Exp Anim',
    'Exp Mol Med',
    'Front Aging Neurosci',
    'Front Behav Neurosci',
    'Front Cardiovasc Med',
    'Front Cell Dev Biol',
    'Front Cell Neurosci',
    'Front Endocrinol (Lausanne)',
    'Front Genet',
    'Front Immunol',
    'Front Mol Neurosci',
    'Front Neurol',
    'Front Neurosci',
    'Front Pharmacol',
    'Front Physiol',
    'G3 (Bethesda)',
    'Haematologica',
    'Int J Biol Sci',
    'Int J Mol Sci',
    'iScience',
    'J Am Heart Assoc',
    'J Biol Chem',
    'J Cell Mol Med',
    'J Neuroinflammation',
    'JCI Insight',
    'Life Sci Alliance',
    'mBio',
    'Mol Brain',
    'Mol Metab',
    'Mol Neurodegener',
    'Nat Commun',
    'Neural Dev',
    'Nucleic Acids Res', 
    'Oncotarget',
    'Oxid Med Cell Longev',
    'Physiol Rep',
    'PLOS Biology',
    'PLOS Genetics',
    'PLOS ONE',
    'PLoS Pathog',
    'Redox Biol',
    'Sci Adv',
    'Sci Rep',
    'Stem Cell Reports',
    'Theranostics',
    'Transl Psychiatry',
    ]
    
# journals that have their content embargoed for a period of time. We need to search them according to their
# respective time delays.  Each pair is journal title : number of months of delay.  Note that the 
# number of months is an approximate time, as we approximate a number of days per month.  See monthsAgo()
# function for details.
embargoedJournalDelays = {
    'Autophagy' : 12,
    'Cardiovasc Res' : 12,
    'Cell Death Differ' : 12,
    'Cereb Cortex' : 12,
    'EMBO J' : 12,
    'EMBO Rep' : 12,
    'Genes Dev' : 6,
    'Immunology' : 12,
    'J Am Soc Nephrol' : 12,
    'J Cell Biol' : 6,
    'J Clin Invest' : 3,
    'J Exp Med' : 6,
    'J Lipid Res' : 12,
    'J Neurosci' : 6,
    'Mol Cell Biol' : 6,
    'Proc Natl Acad Sci U S A' : 6,
    }

embargoedJournals = list(embargoedJournalDelays.keys())
embargoedJournals.sort()

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
    
    global journals, embargoedJournals
    
    # if the user specified a single journal to search, strip it from the parameters and update the global
    # list of journals to process
    
    if sys.argv[-1] in journals:
        journals = [ sys.argv[-1] ]
        embargoedJournals = []
        sys.argv = sys.argv[:-1]

    elif sys.argv[-1] in embargoedJournals:
        journals = []
        embargoedJournals = [ sys.argv[-1] ]
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

def monthsAgo (date, journal):
    # for date (formatted as 'yyyy-mm-dd'), return a suitable date based on the journal's embargo length
    
    if journal not in embargoedJournalDelays:
        raise Exception('Journal is not embargoed: %s' % journal)

    months = embargoedJournalDelays[journal] 
    if months == 12:
        days = 365              # don't worry about leap year
    elif months == 6:
        days = 183              # half year, rounded
    else:
        days = months * 30      # approximately 30 days per month
        
    dateAsSeconds = time.mktime(time.strptime(date, '%Y-%m-%d'))
    embDateAsSeconds = dateAsSeconds - days * 24 * 60 * 60
    
    return time.strftime('%Y-%m-%d', time.localtime(embDateAsSeconds))
    
###--- main program ---###

if __name__ == '__main__':
    startDate, stopDate = parseParameters()
    
    if len(journals) > 0:
        journalDateRanges = {}
        dateRange = '%s:%s' % (startDate.replace('-', '/'), stopDate.replace('-', '/'))
        for journal in journals:
            journalDateRanges[journal] = dateRange

        config = backPopulate.Config()
        config.setBasePath(os.environ['PDFDIR'])
        config.setJournals(journals)
        config.setDateRanges(journalDateRanges)
        config.setVerbose(False)
        
        if 'PDFDOWNLOADLOGDIR' in os.environ:
            noPdfFile = os.path.join(os.environ['PDFDOWNLOADLOGDIR'], 'noPdfs.log')
            config.setNoPdfFile(noPdfFile)
        else:
            raise Exception('Must define PDFDOWNLOADLOGDIR')
    
        backPopulate.process(config)

    if len(embargoedJournals) > 0:
        journalDateRanges = {}
        for journal in embargoedJournals:
            dateRange = '%s:%s' % (monthsAgo(startDate, journal).replace('-', '/'), monthsAgo(stopDate, journal).replace('-', '/'))
            journalDateRanges[journal] = dateRange

        embConfig = backPopulate.Config()
        embConfig.setBasePath(os.path.join(os.path.dirname(os.environ['PDFDIR']), 'embargo_PDF_download'))
        embConfig.setJournals(embargoedJournals)
        embConfig.setDateRanges(journalDateRanges)
        embConfig.setVerbose(False)
        
        if 'PDFDOWNLOADLOGDIR' in os.environ:
            noPdfFile = os.path.join(os.environ['PDFDOWNLOADLOGDIR'], 'embargoedNoPdfs.log')
            embConfig.setNoPdfFile(noPdfFile)
        else:
            raise Exception('Must define PDFDOWNLOADLOGDIR')
    
        backPopulate.process(embConfig)
