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
import SciDirectLib
import MapCache
import PubMedAgent

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

# Initialize Elsevier API client
elsClient = SciDirectLib.ElsClient(apikey, inst_token=insttoken)

# Should we actually write out the PDF files or not?  (True / False)
ACTUALLY_WRITE_PDFS = True

# run in debug mode to get more log output (True / False)
DEBUG = True

# cache of papers already in the MGI db that have PDFs
pubmedWithPDF = caches.PubMedWithPDF()

# output directories
PDF_OUTPUT_DIR = None       # for PDF files
PDF_LOG_DIR = None          # for output logs
DIAG_LOG = None             # diagnostic log

HISTORICAL_WINDOW_SIZE = 240           # how many days is our window for searching (roughly 8 months)

if 'PDFDOWNLOADLOGDIR' in os.environ:
    PDF_LOG_DIR = os.environ['PDFDOWNLOADLOGDIR']
    SciDirectLib.initLogger(PDF_LOG_DIR)
else:
    raise Exception('Must define PDFDOWNLOADLOGDIR')

if 'PDFDIR' in os.environ:
    PDF_OUTPUT_DIR = os.environ['PDFDIR']
else:
    raise Exception('Must define PDFDIR')

# cache to look up PubMed IDs for each pii
pmidCache = MapCache.MapCache('pdfdownload_pmidCache.txt')

# cache to look up publication date for each PubMed ID
pubDateCache = MapCache.MapCache('pdfdownload_pubDateCache.txt')

# cache to look up publication type for each PubMed ID
pubTypeCache = MapCache.MapCache('pdfdownload_pubTypeCache.txt')

monthMap = {
    'Jan' : ('01', '31'),       # month number, default day number (if day not specified)
    'Feb' : ('02', '28'),
    'Mar' : ('03', '31'),
    'Apr' : ('04', '30'),
    'May' : ('05', '31'),
    'Jun' : ('06', '30'),
    'Jul' : ('07', '31'),
    'Aug' : ('08', '31'),
    'Sep' : ('09', '30'),
    'Oct' : ('10', '31'),
    'Nov' : ('11', '30'),
    'Dec' : ('12', '31'),
    }

pmDate1 = re.compile('([0-9]{4}) ([A-Z][a-z]{2})[-]([A-Z][a-z]{2})')    # e.g. - 2021 Jan-Jul
pmDate2 = re.compile('([0-9]{4}) ([A-Z][a-z]{2}) ([0-9]{1,2})')         # e.g. - 2021 Jun 1  OR  2021 Jun 12
pmDate3 = re.compile('([0-9]{4}) ([A-Z][a-z]{2})')                      # e.g. - 2021 Jan

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
   ]

# Used to collect and report debugging info related to date handling
class DateTracker:
    # values for 'date format' -- what sort of date format was received?
    NULL = 'null'
    EXACT_DATE = 'exact date'      
    BY_MONTH = 'full month'
    BY_RANGE = 'multiple months'
    
    # values for 'flag' -- how does the date relate to our desired range?
    NULL = 'null'
    PAST = 'skipped: before desired range'
    FUTURE = 'skipped: in the future'
    IN_RANGE = 'kept: within desired range'
    
    def __init__ (self, startDate, endDate):
        self.startDate = startDate
        self.endDate = endDate
        self.byJournal = {}      # { journal : { date format : { flag : count } } }
        return
    
    def track (self, journal, rawDate, pubDate):
        if journal not in self.byJournal:
            self.byJournal[journal] = {}
            
        # identify the type of date specified
        dateType = DateTracker.NULL
        if rawDate != None:
            match1 = pmDate1.match(rawDate)
            if match1:
                dateType = DateTracker.BY_RANGE
            else:
                match2 = pmDate2.match(rawDate)
                if match2:
                    dateType = DateTracker.EXACT_DATE
                else: 
                    dateType = DateTracker.BY_MONTH
                
        flag = DateTracker.NULL
                       
        # identify how the date relates to our desired range
        if pubDate != None:
            if pubDate < self.startDate:
                flag = DateTracker.PAST
            elif pubDate > self.endDate:
                flag = DateTracker.FUTURE
            else:
                flag = DateTracker.IN_RANGE
        
        # work down through the layers and update our counter for this (journal, date type, and flag)
        if dateType not in self.byJournal[journal]:
            self.byJournal[journal][dateType] = {}
            
        if flag not in self.byJournal[journal][dateType]:
            self.byJournal[journal][dateType][flag] = 0
            
        self.byJournal[journal][dateType][flag] = 1 + self.byJournal[journal][dateType][flag]
        return
    
    def reportByJournal(self):
        # write a debugging report regarding the dates retrieved for each journal, showing types of dates, etc.

        debug('Analysis of Dates Returned by Journal')
        debug(' ')
        
        journals = list(self.byJournal.keys())
        journals.sort()
        
        for journal in journals:
            debug(journal)
            
            dateTypes = list(self.byJournal[journal].keys())
            dateTypes.sort()
            
            for dateType in dateTypes:
                debug('  ' + dateType)
                
                flags = list(self.byJournal[journal][dateType].keys())
                flags.sort()
                
                for flag in flags:
                    debug('    %s : %d' % (flag, self.byJournal[journal][dateType][flag]))
        return 

    def report(self):
        # write a debugging report regarding the dates retrieved for each journal, showing types of dates, etc.
        
        debug('-' * 50)
        self.reportByJournal()
        
        return

dateTracker = None

###--- functions ---###

def bailout (error, showUsage = False):
    # Purpose: exit the script, giving an error message, and (optionally) showing the usage statement
    
    if showUsage:
        sys.stderr.write(USAGE)
    sys.stderr.write('Error: %s\n' % error)
    sys.exit(1)

def debug(s, flush = False):
    # If running in DEBUG mode, write s to the DIAG_LOG.
    
    global DIAG_LOG
    
    if DEBUG:
        if not DIAG_LOG:
            DIAG_LOG = open(os.path.join(PDF_LOG_DIR, 'elsevier.diag.log'), 'w')
        DIAG_LOG.write(s + '\n')
        if flush:
            DIAG_LOG.flush()

    return
    
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

def searchJournal (journal, startDate, stopDate):
    # Look in the given journal for relevant articles that may fall between startDate and stopDate.
    # (We cannot search by publication date, so we don't know for sure.  We'll filter them in the
    # downloadPapers method to only retrieve those truly within that range.

    # We want to cast a wide net to ensure that we get all papers published between startDate
    # and stopDate, so we'll look for loaded dates up to HISTORICAL_WINDOW_SIZE days ago.
    startAsStruct = time.strptime(startDate, '%Y-%m-%d')
    startAsSeconds = time.mktime(startAsStruct)
    searchDateAsSeconds = startAsSeconds - (HISTORICAL_WINDOW_SIZE * 24 * 60 * 60)     # go back 'n' days
    searchDateAsStruct = time.localtime(searchDateAsSeconds)
    searchDate = time.strftime('%Y-%m-%d', searchDateAsStruct) 
    
    longName = journal.elsevierName
    query = {'pub'        : '"%s"' % longName,
             'qs'         : 'mice',
             'loadedAfter': searchDate + 'T00:00:00Z',
             'display'    : { 'sortBy': 'date' }
             }
    search = SciDirectLib.SciDirectSearch(elsClient, query, getAll=True).execute()

    debug(' ')
    debug("=" * 40)
    debug("%s: %d total search results since %s" % (longName, search.getTotalNumResults(), searchDate))
    return search

def isWithin (pubDate, startDate, stopDate):
    # Return True if the given pubDate falls between the startDate and stopDate, inclusive.  Return False
    # otherwise, as we don't want papers published outside our window.
    
    return (pubDate != None) and (pubDate >= startDate) and (pubDate <= stopDate)

def getStandardDateFormat(pmd):
    # Take the given PubMed date and convert it to a standard yyyy-mm-dd date format.  PubMed dates can come
    # in like:  "2021 Jul 2"  or  "2021 Jul"  or  "2021 Jan-Jun"
    
    yyyy = '9999'       # bogus default date will always be outside the desired range
    mm = '99'
    dd = '99'

    if pmd == None:
        return '%s-%s-%s' % (yyyy, mm, dd)

    match1 = pmDate1.match(pmd)
    if match1:
        yyyy = match1.group(1)
        mm, dd = monthMap[match1.group(3)]
    else:
        match2 = pmDate2.match(pmd)
        if match2:
            yyyy = match2.group(1)
            mm = monthMap[match2.group(2)][0]
            dd = match2.group(3)
            if len(dd) == 1:
                dd = '0' + dd
        else: 
            match3 = pmDate3.match(pmd)
            if match3:
                yyyy = match3.group(1)
                mm, dd = monthMap[match3.group(2)]
    
    return '%s-%s-%s' % (yyyy, mm, dd)
    
def downloadPapers (journal, results, startDate, stopDate):
    # Given our journal and and set of results, download all the PDFs that were published by the stopDate.
    # (The start date was considered in the search, but the stop date is not.  So we need to handle that here.)
    
    longName = journal.elsevierName         # long-form of the desired journal name
    refTypes = {}                           # maps from each reference type to a count of those kept
    numPMIDs = 0                            # number with PubMed IDs
    numPDFs = 0                             # number of PDFs written

    beyondStop = []     # references loaded after the stop date (by DOI)
    wrongJournals = []  # list of wrong journals that were returned by the search
    noIDs = []          # references with no PubMed IDs yet (by DOI)
    noPdfs = []         # references with PubMed IDs but no PDFs (by PubMed)
    downloaded = []     # successfully downloaded (by PubMed)
    
    debug('-- search returned %s references' % results.getTotalNumResults())

    # Sadly, we need to switch to use PubMed to look up accurate publication dates for these
    # references.  The SciDirect ones are not consistent with the dates in the downloaded PDFs.
    
    publicationDates = {}

    pmAgent = PubMedAgent.PubMedAgentMedline()
    publicationDates = {}           # PM ID -> publication date
    missed = 0
    for r in results.getIterator():
        pmid = None
        if pmidCache.contains(r.getPii()):
            pmid = pmidCache.get(r.getPii())
        else:
            pmid = r.getPmid()
            if pmid != 'no PMID':
                pmidCache.put(r.getPii(), pmid)

        # TODO: should fix to consider caching of reference dates!
        if pmid != 'no PMID':
            pmRef = pmAgent.getReferenceInfo(pmid)
            if pmRef != None:
                publicationDates[pmid] = getStandardDateFormat(pmRef.getDate())
                pubDateCache.put(pmid, publicationDates[pmid])
                dateTracker.track(journal.elsevierName, pmRef.getDate(), publicationDates[pmid])
        else:
            debug('No PMID for pii %s, title: %s' % (r.getPii(), r.getTitle()))
                
        if pmid not in publicationDates:
#            debug('   > missing date for pii %s, pmid %s' % (r.getPii(), pmid))
            missed = missed + 1

    debug('-- retrieved %d publication dates from PubMed (%d do not have them yet)' % (len(publicationDates), missed))

    totalCount = 0
    wrongJournalCount = 0
    inMGI = 0
    
    for r in results.getIterator():
        pii = r.getPii()
        totalCount = totalCount + 1

        # Right up front, we can exclude papers from other journals.  (The SciDirect API uses a word
        # search for journal name, so if our desired journal is a contained in of other journal names, we'll
        # get papers back for those too.  Because the journal name is in the initial data packet received,
        # eliminating those up front will prevent subsequent calls to retrieve other data.
        if longName != r.getJournal():
            wrongJournalCount = wrongJournalCount + 1
            if r.getJournal() not in wrongJournals:
                wrongJournals.append(r.getJournal())
            continue
            
        # If we already have the PubMed ID cached, we don't need to go back to SciDirect to retrieve it.
        pmid = None
        if pmidCache.contains(pii):
            pmid = pmidCache.get(pii)
        else:
            pmid = r.getPmid()
            if pmid != 'no PMID':
                pmidCache.put(pii, pmid)

        # skip any papers we already have in the database
        if pubmedWithPDF.contains(pmid):
            inMGI = inMGI + 1
            continue
        
        # If we already have the publication type cached, we don't need to go back to SciDirect to retrieve it.
        # Otherwise, get it.
        pubType = None
        if pubTypeCache.contains(pmid):
            pubType = pubTypeCache.get(pmid)
        else:
            pubType = r.getPubType()
            pubTypeCache.put(pmid, pubType)
        
        try:
            pubDate = None
            if pmid in publicationDates:
                pubDate = publicationDates[pmid]

            # Must ensure that the reference's date is not beyond the stopDate.
            
            if isWithin(pubDate, startDate, stopDate):
                refTypes[pubType] = refTypes.get(pubType, 0) + 1
                
                # write pdf if we have PMID
                if pmid != 'no PMID':
                    numPMIDs += 1 
                    if ACTUALLY_WRITE_PDFS:
                        numPDFs += 1 
                        fname = os.path.join(PDF_OUTPUT_DIR, 'PMID_%s.pdf' % pmid)
                        debug('downloading PMID_%s with pub date %s (between %s and %s)' % (pmid, pubDate, startDate, stopDate))
                        try:
                            with open(fname, 'wb') as f:
                                f.write(r.getPdf())
                            downloaded.append(pmid)
                        except:
                            noPdfs.append(pmid)
                else:
                    noIDs.append(r.getDoi())
            else:
                beyondStop.append(r.getDoi())

        except: # in case we get any exceptions working w/ this r, let's see it
            print("Reference exception\n")
            print(json.dumps(r.getDetails(), sort_keys=True, indent=2))
            raise

    debug('-- examined %d remaining papers' % totalCount)
    debug("-- excluded %d papers already in MGI" % inMGI)
    debug("-- excluded %d papers because publication date is outside the specified dates" % len(beyondStop))
    debug("-- excluded %d papers because of missing PubMed ID" % len(noIDs))
    debug("-- excluded %d papers that were missing their PDF file" % len(noPdfs))
    debug("-- excluded %d papers because they were from the wrong journal" % (wrongJournalCount))
    if wrongJournalCount > 0:
        debug("   > %d other journals: %s" % (len(wrongJournals), ', '.join(wrongJournals)))
    debug("-- %d papers successfully downloaded" % len(downloaded))
    debug("-- summary of matching publication types: %s" % str(refTypes), True)
    
    return 

###--- main program ---###

if __name__ == '__main__':
    startDate, stopDate = parseParameters()
    dateTracker = DateTracker(startDate, stopDate)
    debug('Searching %d journal(s) from %s to %s' % (len(journals), startDate, stopDate), True)

    for journal in journals:
        journalStartTime = time.time()
        results = searchJournal(journal, startDate, stopDate)
        if results.getTotalNumResults() > 0:
            downloadPapers(journal, results, startDate, stopDate)

        elapsed = time.time() - journalStartTime
        debug('finished %s in %0.2f sec' % (journal.elsevierName, elapsed))

    pubDateCache.save()
    debug('-- wrote %d entries to cache file: %s' % (pubDateCache.size(), pubDateCache.getPath()))

    pmidCache.save()
    debug('-- wrote %d entries to cache file: %s' % (pmidCache.size(), pmidCache.getPath()))

    pubTypeCache.save()
    debug('-- wrote %d entries to cache file: %s' % (pubTypeCache.size(), pubTypeCache.getPath()))

    dateTracker.report()

    if DIAG_LOG:
        DIAG_LOG.close()
