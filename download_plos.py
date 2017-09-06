#!/usr/local/bin/python

# Name: download_plos.py
# Purpose: Download PDFs from PLOS for the preceding sixty days.  This includes papers where:
#   1. title, abstract, or body contain "mice"
#   2. journal is PLOS One, PLOS Genetics, PLOS Biology, or PLOS Pathogens
#   3. issue and journal are non-null (to avoid uncorrected proofs)
#   4. the DOI ID is not already in MGI
# Notes: Destination folder of PDFs is pulled from configuration.  There is some lag time
#    between when papers are published and when they are available for download, and that
#    lag appears to be non-standard, so we allow a two month cushion in hopes to catch
#    all relevant papers eventually.

import sys
sys.path.insert(0, '/usr/local/mgi/live/lib/python')

USAGE = '''Usage: %s [yyyy-mm-dd] [yyyy-mm-dd]
    The default behavior (no parameters) is to get files for the sixty days
    preceding today.  If you specify dates, you must specify both.  The first
    is the start date (inclusive) and the second is the end date (exclusive).
    That is, searching from 2001-01-01 to 2001-01-03 will return papers with
    a publication date of 2001-01-01 and 2001-01-02.
''' % sys.argv[0]

import os 
import re
import time
import urllib
import Dispatcher
import HttpRequestGovernor
import Profiler
import PubMedCentralAgent
import caches

###--- setup ---###

for envVar in [ 'PG_DBSERVER', 'PG_DBNAME', 'MGI_PUBLICUSER', 'MGI_PUBLICPASSWORD', 'PDFDIR', 'WINDOW_SIZE' ]:
    if envVar not in os.environ:
        raise Exception('Missing environment variable: %s' % envVar)

caches.initialize(os.environ['MGI_PUBLICUSER'], os.environ['MGI_PUBLICPASSWORD'],
    os.environ['PG_DBSERVER'], os.environ['PG_DBNAME'])

###--- Globals ---###

profiler = Profiler.Profiler()

# which PLOS journals do we want to search?
journals = [ 'PLOS ONE', 'PLOS Genetics', 'PLOS Biology', 'PLOS Pathogens']

# URL for contacting PLOS to find articles (plug in journal name, start date, end date, start row, and 
# max number of rows to return)
baseUrl = 'http://api.plos.org/search?q=journal:"%s" AND (abstract:"mice" OR body:"mice" OR title:"mice") ' + \
    'AND publication_date:[%sT00:00:00Z TO %sT00:00:00Z] AND issue:[* TO *] AND volume:[* TO *]' + \
    '&fl=id,journal,title,volume,issue,publication_date&wt=json&start=%d&rows=%d'

# handles timing issues for PLOS requests, so we can stay within their usage caps
governor = HttpRequestGovernor.HttpRequestGovernor()

# number of days to look back to try to find articles (due to delay in transfer from PLOS to PubMed Central)
windowSize = int(os.environ['WINDOW_SIZE'])

###--- functions ---###

def bailout (error, showUsage = False):
    # Purpose: exit the script, giving an error message, and (optionally) showing the usage statement
    
    if showUsage:
        sys.stderr.write(USAGE)
    sys.stderr.write('Error: %s\n' % error)
    sys.exit(1)
    
def getDates():
    # Purpose: get the start and stop dates for the download
    # Returns: (start date, stop date)
    # Throws: nothing
    # Notes: The stop date is midnight today, while the start date is midnight 'windowSize' days before.
    #    This will not get papers for today, but for the 'windowSize' days preceding today.
    
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

    profiler.stamp('dates: %s to %s' % (startDate, stopDate))
    return (startDate, stopDate)

def getUrl(journal, startDate, stopDate, startIndex, rowCount):
    # Purpose: get a properly encoded version of 'baseUrl', filling in the given parameters
    # Returns: string URL
    # Throws: nothing
    
    url = baseUrl % (journal, startDate, stopDate, startIndex, rowCount)
    
    # I don't use urllib.quote() here, because I don't want the whole string to have useful
    # bits (like = or &) replaced.
    return url.replace(' ', '%20').replace('[', '%5b').replace(']', '%5d')

def getPapersForJournal(journal, startDate, stopDate):
    # Purpose: get the papers for 'journal' published between the two dates
    # Returns: list of dictionaries, each of which represents a single paper
    # Throws: Exception if there are problems with retrieving the data from PLOS

    global governor
    
    startIndex = 1          # start the next set of results at what index?
    rowCount = 100          # max number of rows returned for each iteration
    totalCount = 9999       # number of matching records (just start big, then adjust)
    
    docs = []               # list of dictionaries, each representing a single paper
    
    while (startIndex <= totalCount):
        resultString = governor.get(getUrl(journal, startDate, stopDate, startIndex, rowCount))

        # This is less than ideal, from a security perspective.  We ought to be using the json module for
        # decoding this string, but that's not available until Python 2.7.  Since we know the data source,
        # and it's not arbitrary user-entered data, it's probably okay for now.
        results = eval(resultString)
        
        totalCount = results['response']['numFound']
        docs = docs + results['response']['docs']
        
        startIndex = startIndex + rowCount
        
    profiler.stamp('%d papers from %s' % (len(docs), journal))
    return docs

def getPapers(startDate, stopDate):
    # Purpose: get the papers for all the monitored journals published between the two dates
    # Returns: list of dictionaries, each of which represents a single paper
    # Throws: Exception if there are problems with retrieving the data from PLOS

    papers = []
    for journal in journals:
        papers = papers + getPapersForJournal(journal, startDate, stopDate)
        
    profiler.stamp('%d papers in all' % len(papers))
    return papers

def reportMissing(map, missingType):
    # Purpose: report any keys of 'map' that have None associated as a value
    
    keys = map.keys()
    keys.sort()
    
    ct = 0      # count of missing items
    
    for key in keys:
        if not map[key]:
            print 'Missing %s for %s' % (missingType, key)
            del map[key]
            ct = ct + 1

    profiler.stamp('%d missing %ss' % (ct, missingType))
    return
    
def getPMCIDs(papers):
    # Purpose: get a list of the PMC IDs that correspond to the given set of 'papers'
    # Returns: list of strings (PMC IDs)
    # Throws: Exception if there are problems retrieving the IDs from PubMed Central
    
    doiIDs = map(lambda x: x['id'], papers)
    idConverter = PubMedCentralAgent.IDConverterAgent()
    pmcIDs = idConverter.getPMCIDs(doiIDs)

    reportMissing(pmcIDs, 'PMC ID')
    profiler.stamp('Got %d PMC IDs' % len(pmcIDs))
    return pmcIDs.values()

def getUrls(pmcIDs):
    # Purpose: get a list of the URLs needed to download PDFs for the papers identified
    #    by their PMC IDs
    # Returns: list of strings (URLs)
    # Throws: Exception if there are problems returning the URLs from PubMed Central
    
    pdfLookup = PubMedCentralAgent.PDFLookupAgent()
    urls = pdfLookup.getUrls(pmcIDs)
    
    reportMissing(urls, 'URL')
    profiler.stamp('Got %d URLs' % len(urls))
    return urls.values()

def downloadUrls(urls):
    # Purpose: download the PDF files identified by 'urls'
    # Returns: nothing
    # Throws: Exception if there are problems returning the URLs from PubMed Central

    dispatcher = Dispatcher.Dispatcher()
    ids = []
    for url in urls:
        ids.append(dispatcher.schedule([ './download_pdf.sh', url, os.environ['PDFDIR'] ]))

    dispatcher.wait()
    profiler.stamp('Finished downloading %d files' % len(urls))
    return

def filterPapers(papers):
    # Purpose: eliminate from 'papers' any that are already in the database (based on DOI ID)
    # Returns: list of dictionaries (subset of 'papers')
    # Throws: Exception if there are problems reading cache of IDs from database
    
    doiCache = caches.DOICache()
    profiler.stamp('Cached %d DOI IDs from db' % len(doiCache))

    ct = 0              # count of papers already in database
    i = len(papers)
    while i > 0:
        i = i - 1
        if papers[i]['id'] in doiCache:
            del papers[i]
            ct = ct + 1
            
    profiler.stamp('Skipped %d papers already in db' % ct)
    return papers 
    
###--- main program ---###

if __name__ == '__main__':
    startDate, stopDate = getDates()
    papers = filterPapers(getPapers(startDate, stopDate))
    pmcIDs = getPMCIDs(papers)
    urls = getUrls(pmcIDs)
    downloadUrls(urls)
    print '-' * 40
    print 'Profiler Report'
    profiler.write()
    print '-' * 40
    print 'PLOS Governor Report'
    for line in governor.getStatistics():
        print line
