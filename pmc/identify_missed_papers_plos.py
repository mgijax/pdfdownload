#!/usr/bin/env python3

# Name: identify_missed_papers_plos.py
# Purpose: Identify DOI IDs from PLOS that have passed our sixty day window and need manual attention.
#   This includes papers we would normally like to bring in, because they have these attributes:
#   1. title, abstract, or body contain "mice"
#   2. journal is PLOS One, PLOS Genetics, PLOS Biology
#   3. issue and journal are non-null (to avoid uncorrected proofs)
#   4. the DOI ID is not already in MGI
#
# Implementation history
#
# 5/11/2020 - jak
#       TR13204 conversion to python 3.7
# 12/5/17 - sc
#       TR12737 removed PLOS Pathogens

import sys
sys.path.insert(0, '../shared')

USAGE = '''Usage: %s [yyyy-mm-dd] [yyyy-mm-dd]
    The default behavior (no parameters) is to get DOI IDs for the period of
    60 to 120 days preceding today.  If you specify dates, you must specify both.
    The first is the start date (inclusive) and the second is the end date (inclusive).
    That is, searching from 2001-01-01 to 2001-01-03 will return IDs that meet the
    desired criteria, published between 2001-01-01 and 2001-01-03, and that didn't
    make it into MGI.
''' % sys.argv[0]

import os 
import re
import time
#import urllib.request, urllib.parse, urllib.error
import HttpRequestGovernor
import Profiler
import caches

###--- setup ---###

for envVar in [ 'PG_DBSERVER', 'PG_DBNAME', 'MGI_PUBLICUSER', 'MGI_PUBLICPASSWORD', 'WINDOW_SIZE' ]:
    if envVar not in os.environ:
        raise Exception('Missing environment variable: %s' % envVar)

caches.initialize(os.environ['MGI_PUBLICUSER'], os.environ['MGI_PUBLICPASSWORD'],
    os.environ['PG_DBSERVER'], os.environ['PG_DBNAME'])

###--- Globals ---###

profiler = Profiler.Profiler()

# which PLOS journals do we want to search?
journals = [ 'PLOS ONE', 'PLOS Genetics', 'PLOS Biology']

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
    # Purpose: get the start and stop dates for the search
    # Returns: (start date, stop date)
    # Throws: nothing
    # Notes: By default, the stop date is midnight sixty days ago, while the start date is midnight
    #    one hundred twenty days before. 
    
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
        startDate = time.strftime("%Y-%m-%d", time.localtime(time.time() - windowSize * 2 * 24 * 60 * 60))
        stopDate = time.strftime("%Y-%m-%d", time.localtime(time.time() - windowSize * 24 * 60 * 60))

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
    
    startIndex = 0          # start the next set of results at what index?
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
            
    profiler.stamp('Dropped %d DOI IDs already in db' % ct)
    return papers 
    
###--- main program ---###

if __name__ == '__main__':
    startDate, stopDate = getDates()
    papers = filterPapers(getPapers(startDate, stopDate))

    print('-' * 40)
    print('Profiler Report')
    profiler.write()

    print('-' * 40)
    print('PLOS Governor Report')
    for line in governor.getStatistics():
        print(' - %s' % line)

    print('-' * 40)
    print('Missed papers that are outside the PLOS downloader\'s search window: (%d papers)' % len(papers))
    print('(%s)' % ') OR ('.join([x['id'] for x in papers]))

    print('-' * 40)
