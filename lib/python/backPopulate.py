# copied from autolittriage product, converted from script to library, updated
# to integrate with routine downloader -- jsb, 10/23/2018

""" Author:  Jim, August 2018
    For specified journals, and other params (volume, issue, date range)
	get PDFs from PMC Eutils and Open Access (OA) search.
    Populate output directories with PDFs

    Output: Status/summary messages to stdout
	    Populate output directories, one subdir for each journal processed.

    Here is what I think I know about PMC and Open Access (OA):
    * When you search PMC via eutils, get list of matching articles (XML).
    * Basic structure of article XML:
	* <front> meta-data, journal, vol, issue, IDs, article-title, abstract
	* <body> - optional. seems to be the marked up text of the article.
	    * various markups: figure, caption, section/section title...
	* <back> - optional. references, acknowledgements, ...
    * So in theory, if <body> exists, can get our extracted text from it + front
	I have a method for this below, but it needs more work, and I'm
	not sure it is the right way to go.
	This seems like it would be formatted/flow differently from our PDF
	extractor.  (although if we only look at title + abstract + figure text,
	this might be ok)
	So I think we should get PDFs so we can run them through our normal 
	    text extractor.
    * It may be that only OA articles have a <body>, I can't quite tell
    * I also looked at the bulk download of PMC extracted text.
	ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_bulk/
	The examples I looked at didn't have the title text. Although again,
	if we pull title + abstract from db/pubmed and fig text from downloaded
	files, this might be fine.
	Again, I'm not sure which articles have this PMC extracted text.
    * some OA articles also have PDF on the OA FTP site. Need to query the OA
	service to find the location on the FTP site
	https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/
    * some OA articles have the PDF stored directly, some have the PDF within
	a .tgz file (some have no PDF, but presumably XML <body> ?)

    * So Current Goal: for matching articles that are not in MGD already,
		    get PDF files, if any, and XML files, if they have <body>
"""

import sys
import os
import time
import simpleURLLib as surl
import NCBIutilsLib as eulib
#import xml.etree.ElementTree as ET        replaced by XmlReader until Python 2.7
import XmlReader as ET
import runCommand
import Dispatcher
import caches

# --------------------------
# Journals/Search params
# --------------------------

# eutils PMC search clause to include only mice papers
MICE_CLAUSE = '(mice[Title] OR mice[Abstract] OR mice[Body - All Words])'

# eutils PMC search clause to restrict PMC search to open access articles
OPEN_ACCESS_CLAUSE = 'open access[filter]'

# Volumes earlier than 2016 should be up to date
DEFAULT_DATERANGE = '2010/01/01:2016/12/31'

# defines what config info is expected by this module -- Construct one of these,
# populate it, and pass it into the process() function.
class Config:
    def __init__ (self):
        self.basePath = '.'
        self.journals = []
        self.dateRange = DEFAULT_DATERANGE
        self.pmcID = None
        self.miceOnly = True
        self.maxFiles = 0
        self.noWrite = False
        self.verbose = True
        self.noPdfFile = None       # path to which to write a file of IDs with no PDFs
        return
    
    def setNoPdfFile(self, noPdfFile):
        self.noPdfFile = noPdfFile
        return

    def setBasePath(self, bp):
        # Dir to write to. Files are written to dir/journal.
        self.basePath = bp
        return
    
    def setJournals(self, journals):
	    # files with journal names
        self.journals = journals
        return
    
    def setDateRange(self, dr):
        # date range:  yyyy/mm/dd:yyyy/mm/dd
        self.dateRange = dr
        return
    
    def setPmcID(self, pmcID):
        # Skip journal search, just get PDF for pmcID (no 'PMC').
        self.pmcID = pmcID
        return
    
    def setNonMice(self, nonMice):
        # include non-mice papers in searches (True) or not (False)
        self.miceOnly = not nonMice
        return
    
    def setMaxFiles(self, maxFiles):
        # max num of articles to download.
        self.maxFiles = maxFiles
        return
    
    def setNoWrite(self, noWrite):
        # don't write any files or directories.
        self.noWrite = noWrite
        return
    
    def setVerbose(self, verbose):
	    # print more messages
        self.verbose = verbose
        return
    
# --------------------------

def buildJournalSearch(queryStrings, journals):
    """ return a { journalName : [ query strings ], ... }
	queryStrings = [ queryString, ... ]
	files = [ filenames to read journalNames from]
	journal= overides files, just do this journal
    """
    journalsToSearch = {}
    for journal in journals:
		journalsToSearch[journal.strip()] = queryStrings
    return journalsToSearch

# --------------------------
# Main routine
# --------------------------
def process(
    args    # Config object - having params for this function
    ):

    if args.pmcID:		# just get pdf for this article and quit
        url = getPdfUrl(args.pmcID)
        if url != '':
	        getOpenAccessPdf(url, args.basePath, 'PMC'+str(args.pmcID)+'.pdf')
        return

    # just one query string per journal for now
    queryStrings = [ "%s[DP] AND %s" % (args.dateRange, OPEN_ACCESS_CLAUSE) ]

    journalsToSearch = buildJournalSearch(queryStrings, args.journals)
    startTime = time.time()

    if args.miceOnly:		# add mice-only clause to each search
        for j, paramList in journalsToSearch.items():
	           journalsToSearch[j] = [ "%s AND %s" % (p, MICE_CLAUSE) for p in paramList ]

    # Find/write output files & get one (summary) reporter for each
    #   journal/search params
    pr = PMCfileRangler(basePath=args.basePath, 
			    verbose=args.verbose, writeFiles=(not args.noWrite))

    reporters = pr.downloadFiles(journalsToSearch, maxFiles=args.maxFiles)

    numPdfs = 0
    print
    for r in reporters:
	print r.getReport()
	numPdfs += r.getNumMatching()

    print "Total PDFs Written: %d" %  numPdfs
    progress( 'Total time: %8.2f seconds\n' % (time.time() - startTime) )

    if args.noPdfFile:
    #    try:
        count = writeNoPdfFile(args.noPdfFile, reporters)
        progress('Wrote %d IDs for articles missing PDFs to %s\n' % (count, args.noPdfFile))
    #    except Exception, e:
    #        raise Exception('Downloaded PDFs, but could not write list of missing PDFs to: %s (%s)' % (args.noPdfFile, e))
    return

def today():
    # today's date as YYYY/mm/dd
    return time.strftime('%Y/%m/%d', time.localtime())
    
def writeNoPdfFile(filePath, reporters):
    # open & write a file to 'filePath' containing the IDs for any articles where PDFs were missing
    # (as collected in the reporters)
    
    pmTitle = 'PubMed ID'
    pmcTitle = 'PMC ID'
    dateTitle = 'Pub Date'
    maxPmLength = len(pmTitle)      # max width of PubMed ID column
    maxPmcLength = len(pmcTitle)    # max width of PubMed Central ID column
    dateLength = len('2018/11/17')
    
    for reporter in reporters:
        for (pmid, pmcid, date) in reporter.getIdsWithNoPdfs():
            if pmid:
                maxPmLength = max(maxPmLength, len(pmid))
            if pmcid:
                maxPmcLength = max(maxPmcLength, len(pmcid))
                
    # like '%-15s %-12s %s\n'
    # (The - ensures left-alignment within the set number of characters.)
    template = '%%-%ds %%-%ds %%s\n' % (maxPmcLength, maxPmLength)

    fp = open(filePath, 'w')
    fp.write('IDs for records with missing PDFs, found by pdfdownload product\n')
    fp.write('As of: %s\n\n' % today())
    
    fp.write(template % (pmcTitle, pmTitle, dateTitle))
    fp.write(template % ('-' * maxPmcLength, '-' * maxPmLength, '-' * dateLength))
    
    ct = 0
    for reporter in reporters:
        for (pmid, pmcid, date) in reporter.getIdsWithNoPdfs():
            if not pmid:
                pmid = '-'
            if not pmcid:
                pmcid = '-'
            if not date:
                date = '-'
                
            fp.write(template % (pmcid, pmid, date))
            ct = ct + 1
            
    fp.close()
    return ct

# --------------------------
# Classes
# --------------------------

class PMCarticle (object):
    """ PMC article record
    """
    pass
# --------------------------

class PMCsearchReporter (object):
    """ Class that keeps track of counts/stats for a given journal and search
    """
    def __init__(self,
	journal,		# the journal...
	searchParams,		# ... and search Params to report on
	count,			# num of articles matched by this search
	maxFiles=0,		# max files from search to process, 0=all
	):
	self.journal = journal
	self.searchParams = searchParams
	self.totalSearchCount = count
	self.maxFiles = maxFiles

	self.nResultsProcessed = 0	
	self.nResultsGotPdf = 0		# num PDF files written

	self.skippedArticles = {}	# dict of skipped because wrong type
					# {"new type name" : [ pmIDs w/ type] }
	self.nSkipped = 0		# num articles skipped

	self.newTypes = {}		# dict of article types found
					#   that we haven't seen before
					# {"new type name" : [ pmIDs w/ type] }
	self.nWithNewTypes = 0		# num articles w/ new types

	self.noPdf = []			# [(pmID, pmcID, pub date), ...] w/ no PDF we could find
	self.mgiPubmedIds=[]		# [pmIDs] skipped since in MGI
	self.noPubmedIds=[]		# [pmcIDs] skipped since no PMID
    # ---------------------

    def skipArticle(self, article,):
	""" Record that this article has been skipped because of its type
	"""
	self.nSkipped += 1
	t = article.type
	if not self.skippedArticles.has_key(t):
	    self.skippedArticles[t] = []
	self.skippedArticles[t].append(article.pmid)

    def newType(self, article):
	""" Record that we found a new article type that we haven't seen before
	"""
	self.nWithNewTypes += 1
	t = article.type
	if not self.newTypes.has_key(t):
	    self.newTypes[t] = []
	self.newTypes[t].append(article.pmid)

    def gotPdf(self, article):
	""" Record that we got/wrote a PDF file for this article """
	self.nResultsGotPdf += 1

    def gotNoPdf(self, article):
	""" couldn't get PDF url for this article """
	self.noPdf.append((article.pmid, article.pmcid, article.date))

    def gotNoPmid(self, article):
	""" couldn't get PMID for this article """
	self.noPubmedIds.append(article.pmcid)

    def skipInMgi(self, article):
	""" no <body> tag for this article - hence, no text """
	self.mgiPubmedIds.append(article.pmid)

    def getNumMatching(self):
	tot = self.totalSearchCount - self.nSkipped -self.nWithNewTypes \
	    - len(self.mgiPubmedIds) - len(self.noPdf) - len(self.noPubmedIds)
	return tot

    def getReport(self):
	# for now
	output = "Journal: %s\n'%s'\n" % (self.journal, self.searchParams)

	output += "%6d %s articles matched search:\n" % \
			    (self.totalSearchCount, self.journal[:25], )
	if self.totalSearchCount == 0: return output

	output += "%6d maxFiles\n" % self.maxFiles
	output += "%6d .pdf files written\n" % self.nResultsGotPdf

	if self.nSkipped > 0:
	    output += "%6d Articles skipped because of type\n" % self.nSkipped
	    for t in self.skippedArticles.keys():
		output += "\t%6d type: %s\n" % (len(self.skippedArticles[t]), t)

	if self.nWithNewTypes > 0:
	    output += "%6d Articles w/ new types\n" % self.nWithNewTypes
	    for t in self.newTypes.keys():
		output += "\t%6d with type: %s, example: %s\n" % \
			( len(self.newTypes[t]), t, str(self.newTypes[t][0]) )

	if len(self.noPubmedIds) > 0:
	    output += "%6d Articles skipped since no PMID:\n" % \
					    len(self.noPubmedIds)
	    output += '\tPMC'+', '.join(map(str, self.noPubmedIds)) + '\n'

	if len(self.mgiPubmedIds) > 0:
	    output += "%6d Articles skipped since in MGI:\n" % \
							len(self.mgiPubmedIds)
	    output += '\tPMID'+', '.join(map(str, self.mgiPubmedIds)) + '\n'

	if len(self.noPdf) > 0:
	    output += "%6d Articles w/ no PDFs:\n" % len(self.noPdf)
	    output += '\tPMID' + ', '.join( map(str, map(lambda x: x[0], self.noPdf)) ) + '\n'

	return output

    def getIdsWithNoPdfs(self):
        return self.noPdf
    
    def getReportHeader(self):
	# for now
	return ''
# end class PMCsearchReporter ------------------------

class PMCfileRangler (object):
    """ Knows how to query PMC and download PDFs from PMC OA FTP site
	Stores files in directories named by journal name.
    """
    # Article Types we know about, ==True if we want these articles,
    #  ==False if we don't
    # These values are taken from "article-type" attribute of <article>
    #  tag in PMC eutils fetch output
    articleTypes = {'research-article': True,
			'review-article': False,
			'other': False,
			'correction': False,
			'editorial': False,
			'article-commentary': False,
			'brief-report': False,
			'case-report': False,
			'letter': False,
			'discussion': False,
			'retraction': False,
			'oration': False,
			'reply': False,
			'news': False,
			}

    def __init__(self, 
		basePath='.',		# base path to write article files
					# files written to basePath/journalName
		urlReader=surl.ThrottledURLReader(seconds=0.2),
		verbose=False,
		writeFiles=True,	# =False to not write any files/dirs
		getPdf=True		# =True to write PDF files for each
					#   matching article that has PDF
					#   (pmid.pdf)
		):
        self.basePath = basePath
        self.urlReader = urlReader
        self.verbose = verbose
        self.writeFiles = writeFiles
        self.getPdf = getPdf
        self.pubmedWithPDF = caches.PubMedWithPDF()
        self.journalSummary = {}
        self.curOutputDir = ''
        self.reporters = []
        self.curReporter = None		# current reporter (for journal/search)

    # ---------------------

    def downloadFiles(self,
		    journalSearch,	# {journalname: [search params]}
					#   search param is PMC query string,
					#   typically specifying vol/issue
					#   or date range
		    maxFiles=0,		# max number of matching files to
		    			#  actually download and store. 0=all
		    ):
	""" Search all the journals and all their search params.
	    Saving files as we go.
	    Return a list of PMCsearchReporters, one for each journal/params
		combination.
	"""
	for journal in sorted(journalSearch.keys()):
	    self._createOutputDir(journal)

	    for searchParams in journalSearch[journal]:
		progress("Searching %s %s..." % (journal, searchParams[:25]))
		startTime = time.time()
		count, resultsE, results = self._runSearch(journal,
						    searchParams, maxFiles)
		searchEnd = time.time()
		progress('%d results.\n - Search time: %9.2f\n' % \
				    (count, searchEnd-startTime))

		self.curReporter = PMCsearchReporter(journal, searchParams,
							    count, maxFiles)
		self.reporters.append(self.curReporter)

		self._processResults(journal, resultsE, results)
		processEnd = time.time()
		progress(' - Process time: %8.2f\n' % (processEnd-searchEnd))

	return self.reporters
    # ---------------------

    def _runSearch(self, journalName, searchParams, maxFiles):
	""" Search PMC for articles from JournalName w/ search Params.
	    Return count of articles, ElementTree, and raw result text
		of PMC search results.
	"""
	query = '"%s"[TA]+AND+%s' % (journalName, searchParams,)
	query = query.replace(' ','+')

	# Search PMC for matching articles
	count, results, webenvURLParams = eulib.getSearchResults("PMC",
				    query, op='fetch', retmax=maxFiles,
				    URLReader=self.urlReader, debug=False )
	# JIM: check for and do something about errors and empty search rslts?
	#  (zero seems to work ok as is)

	#if self.verbose: progress( "'%s': %d PMC articles\n" % (query, count))

	resultsE = ET.fromstring(results)
	return count, resultsE, results
    # ---------------------

    def _processResults(self,
			journalName,
			resultsE,	# ElementTree of results
			results,	# raw return from eutils search
			):
	""" Process the results of the search.
	    For each article in the results, 
		parse the XML and pull out relevant bits.
		Skip the article if it not of the right type.
		Write out the requested files (xml, text, pdf)
	"""
	self.dispatcher = Dispatcher.Dispatcher(maxProcesses=5)
	self.cmdIndexes = []
	self.cmds = []
	self.articles = []
	
	for i, artE in enumerate(resultsE.findall('article')):
		# fill an article record with the fields we care about
		art = PMCarticle()
		art.journal = journalName
		art.type = artE.attrib['article-type']

		artMetaE = artE.find("front/article-meta")

		pubDate = artMetaE.find("pub-date/[@pub-type='epub']")
		if not pubDate:
			pubDate = artMetaE.find("pub-date")
		if pubDate:
			art.date = '%s/%s/%s' % (pubDate.find('year').text,
				pubDate.find('month').text,
				pubDate.find('day').text)
		else:
			art.date = '-'
		
		art.pmcid  = artMetaE.find("article-id/[@pub-id-type='pmc']").text
		art.pmid   = artMetaE.find("article-id/[@pub-id-type='pmid']")
		if art.pmid == None:
			#print "Cannot find PMID for PMC %s, skipping" % str(art.pmcid)
			self.curReporter.gotNoPmid(art)
			continue
		art.pmid   = artMetaE.find("article-id/[@pub-id-type='pmid']").text
		if not self._wantArticle(art): continue
		
		# write files
		if self.getPdf:	self._queuePdfFile(art, artE)

	# To use dispatcher, would need to save PDF requests and submit them
	#  to a batch PDF method
	self._runPdfQueue()
	return

    # ---------------------

    def _runPdfQueue(self, ):
	""" would be nice to factor out into a separate class
	"""
	self.dispatcher.wait()

	for i in range(len(self.cmds)):
	    idx = self.cmdIndexes[i]
	    article = self.articles[i]
	    gotFile = checkPdfCmd( self.cmds[i],
				    self.dispatcher.getReturnCode(idx),
				    self.dispatcher.getStdout(idx),
				    self.dispatcher.getStderr(idx), )
	    if gotFile:
		self.curReporter.gotPdf(article)
		if self.verbose: progress('P')	# output progress P
	    else:
		self.curReporter.gotNoPdf(article)
		if self.verbose: progress('p')
	return
    # ---------------------

    def _queuePdfFile(self, article, artE):

	linkUrl = getPdfUrl(article.pmcid)	# this is slow!

	if linkUrl == '':
	    self.curReporter.gotNoPdf(article)
	    if self.verbose: progress('p')
	    return

	if not self.writeFiles: return	# don't really output

	cmd = getPdfCmd( linkUrl, self.curOutputDir, 
				    'PMC' + str(article.pmcid) + '.pdf')

	#if self.verbose: progress('\n' + cmd + '\n')

	idx = self.dispatcher.schedule(cmd)
	self.cmdIndexes.append(idx)
	self.cmds.append(cmd)
	self.articles.append(article)
	return
    # ---------------------
   
    def _wantArticle(self, article):
	""" Return True if we want this article (for now, we want its type)
	    Need to add check for already in MGD.
	"""
	if self.pubmedWithPDF.contains(article.pmid):
	    self.curReporter.skipInMgi(article)
	    return False

	if self.articleTypes.has_key(article.type):	# know this type
	    if not self.articleTypes[article.type]:	# but don't want it
		self.curReporter.skipArticle(article)
		return False
	else:	# not seen this before. Report so we can decide if we want it
	    self.curReporter.newType(article)
	    return False
	return True
    # ---------------------

    def _createOutputDir(self, journalName):
	""" create an output directory for this journalName
	"""
        self.curOutputDir = self.basePath

	if not self.writeFiles: return
	
        if not os.path.exists(self.curOutputDir):
            os.makedirs(self.curOutputDir)
    # ---------------------
# --------------------------

def getPdfUrl(pmcid):
    """ Return the Open Access URL (str) to the pdf or gzipped tar file
	containing pdf for the given pmcid.
	Return '' if there is no such file
    """
    # Can add "format=pdf" to oa search
    # Not sure if this means "has a free standing PDF" or "has a PDF either
    #  free standing or within a .tgz"
    # Should we only get articles that have PDFs?

    # get FTP file location on OA FTP site
    baseUrl = 'https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC%s'
    url = baseUrl % str(pmcid)
    out = surl.readURL(url)	 # no throttle req't for OA, so no throttle 
    #out = self.urlReader.readURL(url)
    ele = ET.fromstring(out)

    errorE = ele.find('./error')
    if errorE != None:
	code = errorE.attrib['code']
	msg = errorE.text
	print "Error finding OA link for PMC%s. Code='%s'. Message='%s'" \
					    % (pmcid, code, msg)
	return ''

    # Get file URL. Use PDF link if it exists, if not assume tgz link exists
    linkE = ele.find('./records/record/link/[@format="pdf"]')
    if linkE == None:		# no direct PDF link
	linkE = ele.find('./records/record/link/[@format="tgz"]')
	# Seems like this could fail, or could find .tgz but no PDF within
    #else: print "PMC%s had direct pdf link" % str(pmcid)

    return linkE.attrib['href']
# ---------------------

def getPdfCmd(linkUrl,	# URL to download from
    outputDir,			# directory where to store the file
    fileName,			# file name itself (presumably with .pdf)
    ):
    """ Return Unix command to Download the PDF at url.
    """
    # set up for Jon's cool download script (modified a bit) to get the PDF
    cmd = "./download_pdf.sh %s %s %s" % (linkUrl, outputDir, fileName)
    return cmd
# ---------------------

def checkPdfCmd(cmd,	# the command itself
    retcode,
    stdout,
    stderr,
    ):
    """ Check the retcode and stdout, stderr for this command.
	Report if there are any problems
	Return true if all ok.
    """
    if retcode != 0:
	print "Error on pdf download"
	print "retcode %d on: '%s'" % (retcode, cmd)
	if stdout[0] == "Error: no PDF found in gzip file\n":
	    print "stdout from cmd: Error: no PDF found in gzip file"
	else:
	    print "stdout from cmd: '%s'" % stdout
	    print "stderr from cmd: '%s'" % stderr
	return False
    return True
# ---------------------

def getOpenAccessPdf(linkUrl,   # URL to download from
    outputDir,                  # directory where to store the file
    fileName,                   # file name itself (presumably with .pdf)
    ):
    """ Download the PDF at url.
        Return True if we got the file ok, False, ow.
    """
    # set up for Jon's cool download script (modified a bit) to get the PDF
    cmd = getPdfCmd(linkUrl, outputDir, fileName)

    stdout, stderr, retcode = runCommand.runCommand(cmd) # uses curl

    return checkPdfCmd(cmd, retcode, stdout, stderr)
# ---------------------

# --------------------------
# helper routines
# --------------------------

def progress(s):
    ''' write some progress info'''
    sys.stdout.write(s)
    sys.stdout.flush()
# ---------------------
