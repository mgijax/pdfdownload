# copied from autolittriage product, converted from script to library, updated
# to integrate with routine downloader -- jsb, 10/23/2018

""" Author:  Jim, August 2018, updated Feb 2022
    For specified journals and date range
        get PDFs from PMC Eutils and Open Access (OA) search.

    Output: Status/summary messages to stdout
            Downloaded PDFs, named by PMID_######.pdf
            A "noPdf" file listing PDFs that didn't download correctly to be
                emailed to Nancy for her to manually get the PDFs.

    Jan 2022: Overview of the process, brain dump

    Why is this module called backPopulate.py? This was originally written to
    back populate non-MGI-selected papers from PMC as negative training refs
    to add to the DB. Jon adapted it from that and decided not to rename it.

    Currently,
    Given a list of OA journal names and begin/end dates, this code:
    Searches PMC for matching papers that contain the word "mice".
    For papers that match certain criteria, downloads the PDF from OA.
    Reports to stdout
        a log of its process including any errors it encounters
        a summary of the papers it looked at for each journal
    The criteria to select a paper for download:
        * has its PMID available at PMC
        * has the right publication type (e.g., not editorials, reviews)
        * the paper (PMID) is not already in MGI

    The downloading is complex and somewhat error prone:
        1) the basic PMC search returns an XML document of matching articles
        2) for each matching article,
            parse the XML, get relevant bits (IDs, pub date, type, ...)
            if it meets our criteria, queue it up for PDF download

            Uses Jon's Dispatcher module that queues up a list of Unix
            shell commands and runs a bunch of them up in parallel and
            returns each of the command's retcode, stdout, stderr when they
            are all done. This lets us run a bunch of downloads in parallel.

            To queue it up, we first query OA to find the filename to
            download from the OA FTP site.
            See getPdfUrl() below.

            The actual download command is a shell script: download_pdf.sh
            (See getPdfCmd() below)
            * uses curl to download the FTP file
            * sometimes the FTP file is the PDF we want, sometimes it is a
                gzipped tar file that may contain the PDF
            * if it is the PDF file, download_pdf.sh just renames it
            * if gzipped tar file, download_pdf.sh
                unpacks the tar file,
                calls find_pdf_in_tar.py to decide which PDF in the tar file
                    is likely the article's PDF (there can be multiple PDFs,
                    supplemental data and images are often stored as PDFs in
                    the tar file)
                grabs the PDF and renames it to our filename
            * at each step, it checks for errors and reports all errors to
                stdout to be propogated back to this module's output
        3) what can go wrong:
            * getPdfUrl() can fail to get the FTP filename to download (e.g.,
                OA may not actually have the file yet)
            * curl can fail, sometimes OA FTP just craps out
            * the downloaded gzipped tar file can be mangled and doesn't unpack
            * there may be no PDF file in the tar file
            * If any of these happen, the article gets written to the "noPdf"
                email for Nancy to look at.
            * Often, the above errors are spurious and the PDFs will download
                fine if you run the download again.
            * find_pdf_in_tar.py may choose the wrong PDF (although that won't
                be an error we can catch here. Typically these will be caught
                by littriageload sanity checks)

                If FIND_PDF_LOG is defined in the Unix env,
                    find_pdf_in_tar.py will log a summary of its
                    reasoning to that file for debugging/analysis.

    Aug 2018: Here is what I think I know about PMC and Open Access (OA):
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
        The examples I looked at didn't have the title text.
        Again, I'm not sure which articles have this PMC extracted text.
    * some OA articles also have PDF on the OA FTP site. Need to query the OA
        service to find the location on the FTP site
        https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/
    * some OA articles have the PDF stored directly, some have the PDF within
        a .tgz file (some have no PDF, but presumably XML <body> ?)
"""

import sys
import os
import time
import re
from datetime import date, timedelta
import subprocess
import simpleURLLib as surl
import NCBIutilsLib as eulib    # lib_py_web/NCBIutilsLib.py
import xml.etree.ElementTree as ET
import Dispatcher
import caches

# ------------------------
# global stuff for logging
# ------------------------

DEBUG = False
DIAG_LOG = None     # file pointer for debug file
PDF_LOG_DIR = None          # for output logs

if 'PDFDOWNLOADLOGDIR' in os.environ:
    PDF_LOG_DIR = os.environ['PDFDOWNLOADLOGDIR']
else:
    raise Exception('Must define PDFDOWNLOADLOGDIR')

# -------------------------
# general-purpose functions
# -------------------------

def debug(s, flush = True):
    # If running in DEBUG mode, write s to the DIAG_LOG.
    
    global DIAG_LOG
    
    if DEBUG:
        if not DIAG_LOG:
            DIAG_LOG = open(os.path.join(PDF_LOG_DIR, 'pmc.diag.log'), 'w')
        DIAG_LOG.write('%s\n' % s)
        # if you want to print something that is in bytes, like the xml results, 
        # comment out above and uncomment below
        #DIAG_LOG.write(results.decode('UTF-8'))
        if flush:
            DIAG_LOG.flush()

    return
    
def today():
    # today's date as YYYY/mm/dd
    return time.strftime('%Y/%m/%d', time.localtime())
    
# --------------------------
# Journals/Search params
# --------------------------

# eutils PMC search clause to include only mice papers
MICE_CLAUSE = '(mice[Title] OR mice[Abstract] OR mice[Body - All Words])'

# eutils PMC search clause to restrict PMC search to open access articles
OPEN_ACCESS_CLAUSE = 'open access[filter]'

# defines what config info is expected by this module -- Construct one of these,
# populate it, and pass it into the process() function.
class Config:
    def __init__ (self):
        self.basePath = '.'
        self.journals = []
        self.dateRanges = None
        self.pmcID = None
        self.miceOnly = True
        self.maxFiles = 0
        self.noWrite = False
        self.verbose = True
        self.noPdfFile = None       # path to write a file of IDs with no PDFs
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
    
    def setDateRanges(self, dr):
        # date ranges:  { journal name : 'yyyy/mm/dd:yyyy/mm/dd', ... }
        self.dateRanges = dr
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

def buildJournalSearch(baseQueryString, journals, dateRanges):
    """ return a { journalName : [ query strings ], ... }
        queryStrings = [ queryString, ... ]
        files = [ filenames to read journalNames from]
        journal= overides files, just do this journal
    """
    journalsToSearch = {}
    for journal in journals:
        journalsToSearch[journal.strip()] = [baseQueryString % \
                                                    dateRanges[journal]]
    return journalsToSearch

# --------------------------
# Main routine
# --------------------------
def process(args    # Config object - having params for this function
    ):
    if args.pmcID:		# just get pdf for this article and quit
        url = getPdfUrl(args.pmcID)
        if url != '':
            getOpenAccessPdf(url, args.basePath, 'PMC'+str(args.pmcID)+'.pdf')
        return

    # just one query string per journal for now
    baseQueryString = "%%s[DP] AND %s" % OPEN_ACCESS_CLAUSE

    journalsToSearch = buildJournalSearch(baseQueryString, args.journals, args.dateRanges)
    startTime = time.time()

    if args.miceOnly:		# add mice-only clause to each search
        for j, paramList in journalsToSearch.items():
           journalsToSearch[j] = ["%s AND %s" % (p, MICE_CLAUSE) for p in paramList]
    # Find/write output files & get one (summary) reporter for each
    #   journal/search params
    pr = PMCfileRangler(basePath=args.basePath, verbose=args.verbose, writeFiles=(not args.noWrite))

    reporters = pr.downloadFiles(journalsToSearch, maxFiles=args.maxFiles)

    numPdfs = 0
    progress("\nSummary of Articles By Journal\n\n")
    for r in reporters:
        progress(r.getReport() + '\n')
        numPdfs += r.getNumPdfs()

    progress("Total PDFs Written: %d\n" %  numPdfs)
    progress('Total time: %8.2f seconds\n' % (time.time() - startTime) )

    if args.noPdfFile:
        noPdfWriter = NoPdfWriter(args.noPdfFile, reporters, args.dateRanges)
        noPdfWriter.write()
        count = noPdfWriter.getNumArticles()
        progress('Wrote %d IDs for articles missing PDFs to %s\n' % \
                                                (count, args.noPdfFile))
    return
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

        self.skippedByType = {}         # dict of skipped because wrong type
                                        # {"type name" : [ pmcIDs w/ type] }
        self.nSkippedByType = 0		# num articles skipped by type

        self.skippedNewType = {}	# dict of new article types found
                                        #   that we haven't seen before
                                        # {"new type name" : [ pmcIDs w/ type] }
        self.nSkippedNewType = 0	# num articles w/ new types

        self.noPdf = []			# [PMCarticle's...]
                                        #    w/ no PDF we could download

        self.mgiPubmedIds=[]		# [pmIDs] skipped since in MGI

        self.noPubmedId = []            # [pmcIDs] skipped since they don't have PMIDs

        self.earliestNoPubmedIdArticle = None # earliest article w/ no PMID
    # ---------------------

    def skipWrongType(self, article,):
        """ Record that this article has been skipped because it's not a type
            that we download.
        """
        self.nSkippedByType += 1
        t = article.type
        if t not in self.skippedByType:
            self.skippedByType[t] = []
        self.skippedByType[t].append(article.pmcid)

    def skipNewType(self, article):
        """ Record that we found a new article type that we haven't seen before
            and we are skipping the download for this article
        """
        self.nSkippedNewType += 1
        t = article.type
        if t not in self.skippedNewType:
            self.skippedNewType[t] = []
        self.skippedNewType[t].append(article.pmcid)

    def skipNoPMID(self, article):
        """ Record that we are skipping this because PMC doesn't have its PMID
        """
        self.noPubmedId.append(article.pmcid)
        # remember earliest article w/ no PMID
        if not self.earliestNoPubmedIdArticle or \
            str(article.date) < str(self.earliestNoPubmedIdArticle.date):
            self.earliestNoPubmedIdArticle = article

    def skipInMgi(self, article):
        """ Record that we skipped downloading this PDF because it's in MGI """
        self.mgiPubmedIds.append(article.pmid)

    def gotPdf(self, article):
        """ Record that we got/wrote a PDF file for this article """
        self.nResultsGotPdf += 1

    def gotNoPdf(self, article):
        """ Tried to download PDF for this article, but couldn't get it.
        """
        self.noPdf.append(article)

    def getNumPdfs(self):
        return self.nResultsGotPdf

    def getReport(self):
        """ Return a summary report (string) for this journal """
        output = "Journal: %s\n'%s'\n" % (self.journal, self.searchParams)

        output += "%6d %s articles matched search\n" % (self.totalSearchCount, self.journal[:25], )
        if self.totalSearchCount == 0: return output

        #output += "%6d maxFiles\n" % self.maxFiles
        output += "%6d .pdf files written\n" % self.nResultsGotPdf

        if self.nSkippedByType > 0:
            debug('%s : skipped %d articles because of undesired type' % (self.journal, self.nSkippedByType))
            output += "%6d Articles skipped because of type\n" % self.nSkippedByType
            for t in self.skippedByType.keys():
                output += "\t%6d type: %s, example: PMCID %s\n" % (len(self.skippedByType[t]), t, str(self.skippedByType[t][0]))

        if self.nSkippedNewType > 0:
            debug('%s : skipped %d articles because of new type' % (self.journal, self.nSkippedNewType))
            output += "%6d Articles skipped w/ new types\n" % self.nSkippedNewType
            for t in self.skippedNewType.keys():
                output += "\t%6d with type: %s, example: PMCID %s\n" % (len(self.skippedNewType[t]),t,str(self.skippedNewType[t][0]))

        if len(self.noPubmedId) > 0:
            debug('%s : skipped %d articles since PMC does not have PMID' % (self.journal, len(self.noPubmedId)))
            output += "%6d Articles skipped since PMC does not have PMID:\n" % len(self.noPubmedId)
            output += '\tPMCID ' + ', '.join(map(str, self.noPubmedId)) + '\n'
            output += '\tEarliest article w/o PMID: PMC%s %s\n' % \
                        (str(self.earliestNoPubmedIdArticle.pmcid),
                         str(self.earliestNoPubmedIdArticle.date))

        if len(self.mgiPubmedIds) > 0:
            debug('%s : skipped %d articles since already in MGI' % (self.journal, len(self.mgiPubmedIds)))
            output += "%6d Articles skipped since already in MGI:\n" % len(self.mgiPubmedIds)
            output += '\tPMID ' + ', '.join(map(str, self.mgiPubmedIds)) + '\n'

        if len(self.noPdf) > 0:
            debug('%s : %d articles w/ PDF download problem' % (self.journal, len(self.noPdf)))
            output += "%6d Articles w/ PDF download problem:\n" % len(self.noPdf)
            output += '\tPMID ' + ', '.join(map(str, [a.pmid for a in self.noPdf])) + '\n'
        return output

    def getArticlesWithNoPdfs(self):
        return self.noPdf
# end class PMCsearchReporter ------------------------

class NoPdfWriter (object):
    """
    Formats/writes the report of PDFs that failed to download correctly so
    it can be mailed to Nancy
    """
    def __init__(self, filePath, reporters, dateRanges):
        self.filePath = filePath
        self.reporters = reporters
        self.dateRanges = dateRanges

        self.DMMjournal = "Dis Model Mech"      # journal that doesn't provide
                                                #  PDFs in its download files
        self.hasDMMjournal = self.DMMjournal in self.dateRanges.keys()

        self.prevFailures = self._getPrevFailures(filePath)
        self._computeArticleTableTemplate()

    def _getPrevFailures(self, filePath):
        """
        Read previous report file, if any.
        Return dict {'pmcid': n} where n is the number of download_tries
            made for that pmcid in the previous report file.
        """
        # parsing previous noPDF file
        # regex pattern to match a line containing an article in the file
        articleLineRegEx = str(r'\A\s*' +                # start of line
                           r'(\d+)\s+' +                 # PMCID   gr 1
                           r'(?:\d+|-)\s+' +             # PMID | -
                           r'(?:(?:\d{4}[/]\d{2}[/]\d{2})|-)\s+' + # date | -
                           r'\d+\s+' +                   # Weeks_left
                           r'(\d+)\s+' +                 # download_tries gr 2
                           r'.+\Z' )                     # journal + end
        articleLineRe = re.compile(articleLineRegEx)

        prevFailures = {}
        try:
            fp = open(filePath, 'r')
            progress("Reading previous noPDF file '%s'\n" % filePath)
        except:
            progress("No previous noPDF file '%s'\n" % filePath)
            return prevFailures

        for line in fp.readlines():
            m = articleLineRe.match(line[:-1])
            if m:
                pmcid = m.group(1)
                download_tries = m.group(2)
                #print("got match: %s : %d" % (str(pmcid),int(download_tries)))
                prevFailures[str(pmcid)] = int(download_tries)

        fp.close()
        return prevFailures
        
    def _formatJournalSummary(self):
        """ Return formated summary of journals searched """
        output  = 'Summary of searches by the pdfdownload product '
        output += 'as of: %s. Searching:\n' % today()

        datePlusJournal = lambda x: (x[1],x[0])
        for journal,d in sorted(self.dateRanges.items(), key=datePlusJournal):
            dateRange = self.dateRanges[journal].replace(':', ' to ')
            output += '  %s   %s\n' % (dateRange, journal)

        return output + '\n'

    def _formatInstructions(self):
        """ Return Instructions as a string """
        if self.hasDMMjournal:
            DMMtext = self.DMMjournal + " or "
        else:
            DMMtext = ''
        text = """ Instructions for PDFs that need manual download:
        1. Priority PDFs: %sthose with less than 2 Weeks_Left or more than 1 Download_Tries
        2. Go to Pubmed Central (PMC) at https://www.ncbi.nlm.nih.gov/pmc/
        3. Search by the PMC ID from the report
        4. Use the DOI ID at the top of the PMC record to go to the journal site.
        5. Download the PDF (if it is an option do not choose the PDF + SI).
        6. Put in the neb folder on NewNewcurrent.
        """ % DMMtext
        lines = [x.lstrip() for x in text.splitlines()]
        output = '\n'.join(lines)
        return output + '\n'

    def _collectArticles(self):
        """
        Collect all articles that need manual download.
        Compute 'numWeeks' left on this report for each article.
        Return two lists of PMCarticles w/ '.numWeeks' added to each article:
            those from Dis Model Mech
            and those from all other journals
        """
        self.numArticles = 0        # total num of articles that need download
        articlesDMM = []            # list of articles from Dis Model Mech
        articlesOther = []          # list of articles from other journals
        for reporter in self.reporters:
            journal = reporter.journal
            #debug('journal: %s' % journal)
            startDate = self.dateRanges[journal].split(':')[0]
            startDate = startDate.replace('/', '-')
            startDate = date.fromisoformat(startDate) # for this journal

            for article in reporter.getArticlesWithNoPdfs():
                #debug('article.pmcid: %s' % article.pmcid)
                if not article.pmcid:   # should never happen
                    article.pmcid = '-'
                if not article.pmid:    # shouldn't happen now we only get
                    article.pmid = '-'  #   papers w/ PMIDs
                #debug('article.date: %s' % article.date)
                if not article.date:
                    article.date = '-'
                    article.numWeeks = 0
                else:
                    dateObj = date.fromisoformat(article.date.replace('/','-'))
                    delta = dateObj - startDate
                    article.numWeeks = delta.days // 7

                if journal == self.DMMjournal:
                    articlesDMM.append(article)
                else:
                    articlesOther.append(article)

                self.numArticles = self.numArticles + 1

        return articlesDMM, articlesOther

    def _computeArticleTableTemplate(self):
        """
        Compute self.template, self.hdrLine, self.dashLine
            for formatting the output tables of articles that did not download
        """
        # define titles and col lengths for the output tables
        pmTitle = 'PubMed ID'
        pmcTitle = 'PMC ID'
        dateTitle = 'Pub Date'
        weeksTitle = 'Weeks_Left'
        failuresTitle = "Download_Tries"
        journalTitle = 'Journal'
        maxPmLength = len(pmTitle)      # max width of PubMed ID column
        maxPmcLength = len(pmcTitle)    # max width of PubMed Central ID column
        dateLength = len('2018/11/17')
        weeksLength = len(weeksTitle)
        failuresLength = len(failuresTitle)

        self.weeksLength = weeksLength
        self.failuresLength = failuresLength
        
        for reporter in self.reporters:          # find max length of ID cols
            for article in reporter.getArticlesWithNoPdfs():
                if article.pmid:
                    maxPmLength = max(maxPmLength, len(article.pmid))
                if article.pmcid:
                    maxPmcLength = max(maxPmcLength, len(article.pmcid))
                    
        # like '%-15s %-12s %10s %4s %3s %s\n'
        # (The - ensures left-alignment within the set number of characters.)
        self.template = '%%-%ds %%-%ds %%%ds %%%ds %%%ds %%s\n' % (maxPmcLength, maxPmLength, dateLength, weeksLength, failuresLength)
        self.hdrLine = self.template % (pmcTitle, pmTitle, dateTitle, weeksTitle, failuresTitle, journalTitle)
        self.dashLine = self.template % ('-' * maxPmcLength, '-' * maxPmLength, '-' * dateLength, '-' * weeksLength, '-' * failuresLength, '-' * 15)
        return

    def _formatArticleTable(self, articles, label):
        """ Format a table of articles, return the formatted string
        """
        output = '%s that need manual download (%d total)\n' %  \
                                            (label, len(articles))
        if articles:
            output += self.hdrLine
            output += self.dashLine

            # function to select "numWeeks.journal" fields for sorting
            weeksAndJournal = lambda x: (x.numWeeks, x.journal)

            for article in sorted(articles, key=weeksAndJournal):
                triesCount = self.prevFailures.get(article.pmcid, 0) +1
                tries = str(triesCount).center(self.failuresLength)
                weeks = str(article.numWeeks).center(self.weeksLength)
                output += self.template % (article.pmcid, article.pmid, article.date, weeks, tries, article.journal)
        return output + '\n'

    def write(self):
        """
        Open & write a file containing the report of PDFs that didn't download (as collected in the reporters)
        This file is intended to be emailed to Nancy so she can manually get the papers.
        The report has 4 sections:
        1. Summary of the journals/dates searched at PMC
        2. Instructions for Nancy
        3. Dis Model Mech papers - this journal never has PDFs that
            successfully download.
            (This section is only included if Dis Model Mech is one of the
            journals searched.)
        4. Papers from other journals that did not download successfully
        """
        fp = open(self.filePath, 'w')

        fp.write(self._formatJournalSummary())

        fp.write(self._formatInstructions())

        articlesDMM, articlesOther = self._collectArticles()

        label = "Article PDFs"
        if self.hasDMMjournal:
            label = "%s PDFs" % self.DMMjournal
            fp.write(self._formatArticleTable(articlesDMM, label))
            label = "Other journal PDFs"

        fp.write(self._formatArticleTable(articlesOther, label))
        fp.close()
        return

    def getNumArticles(self):
        return self.numArticles
# end class NoPdfWriter --------------------

class PMCfileRangler (object):
    """ Knows how to query PMC and download PDFs from PMC OA FTP site
    """
    # Article Types we know about, ==True if we want these articles,
    #  ==False if we don't
    # These values are taken from "article-type" attribute of <article>
    #  tag in PMC eutils fetch output
    articleTypes = {'research-article': True,
                    'review-article': True,
                    'other': True,
                    'correction': True,
                    'editorial': False,
                    'article-commentary': False,
                    'brief-report': True,
                    'case-report': True,
                    'letter': True,
                    'discussion': True,
                    'retraction': True,
                    'oration': True,
                    'reply': True,
                    'news': True,
                    'expression-of-concern' : True,
                    'meeting-report': False,
                    'methods-article': False,
                    'addendum': False,
                    'systematic-review': False,
                    }

    def __init__(self, 
                basePath='.',		# base path to write article files files written to basePath/journalName
                urlReader=surl.ThrottledURLReader(seconds=0.2),
                verbose=False,
                writeFiles=True,	# =False to not write any files/dirs
                getPdf=True		# =True to write PDF files for each matching article that has PDF (pmid.pdf)
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
                progress("\nSearching %s\n" % (journal))
                startTime = time.time()
                count, resultsE, results = self._runSearch(journal, searchParams, maxFiles)
                searchEnd = time.time()
                progress('%d results - Search time: %9.2f\n' % (count, searchEnd-startTime))

                self.curReporter = PMCsearchReporter(journal, searchParams, count, maxFiles)
                self.reporters.append(self.curReporter)

                self._processResults(journal, resultsE, results)
                processEnd = time.time()
                progress('Done %s downloads - Process time: %8.2f\n' % (journal, processEnd-searchEnd))

        return self.reporters
    # ---------------------

    def _runSearch(self, journalName, searchParams, maxFiles):
        """ Search PMC for articles from JournalName w/ search Params.
            Return count of articles, ElementTree, and raw result text of PMC search results.
        """

        query = '"%s"[TA]+AND+%s' % (journalName, searchParams,)
        query = query.replace(' ','+')
        
        # send full query to log to aid debugging
        progress("Full query: %s\n" % query.replace('+', ' '))

        # Search PMC for matching articles
        debug('query: $s' % (query)
        debug('%s : searching...' % journalName)
        debug("%s : full query : %s" % (journalName, query.replace('+', ' ')))

        try:
            count, results, webenvURLParams = eulib.getSearchResults("PMC",
                                    query, op='fetch', retmax=maxFiles,
                                    URLReader=self.urlReader, debug=False )
        except Exception as e:
            #text = str(e)
            #progress("eulib.getSearchResults issue/ignore: '%s'\n" % text)
            count = 0
            results = '<data></data>'   # empty data

        debug('%s : received %s results' % (journalName, count))

        #if self.verbose: progress( "'%s': %d PMC articles\n" % (query, count))

        # uncomment to get the xml from each journal - may want to limit the 
        # journal list when debugging
        debug('results: %s' % results)

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
                Skip the article if we don't want it
                Attempt PDF download
        """
        self.dispatcher = Dispatcher.Dispatcher(maxProcesses=5)
        self.cmdIndexes = []
        self.cmds = []
        self.articles = []
        toDownload = 0
        
        progress("Queueing up download commands\n")
        for i, artE in enumerate(resultsE.findall('article')):
            # fill an article record with the fields we care about
            art = PMCarticle()
            art.journal = journalName
            art.type = artE.attrib['article-type']
            #debug('art.type: %s' % art.type)
            artMetaE = artE.find("front/article-meta")
            debug('pmcid: %s' %  artMetaE.find("article-id/[@pub-id-type='pmcaid']").text)
            pubDate = artMetaE.find("pub-date/[@pub-type='epub']")
            if not pubDate:
                pubDate = artMetaE.find('pub-date/[@date-type="pub"]')
                debug('no pubDate try again artMetaE.find(pub-date/[@date-type="pub"]): %s' % pubDate)
            if not pubDate:
                pubDate = artMetaE.find("pub-date")
                debug('no pubDate try again artMetaE.find("pub-date"): %s' % pubDate)
            # 2/15/23 old code:
            #if pubDate:
            #    if (pubDate.find('day') != None):
            #        art.date = '%s/%s/%s' % (pubDate.find('year').text,
            #                        pubDate.find('month').text.rjust(2,'0'),
            #                        pubDate.find('day').text.rjust(2,'0'))
            #    else:
            #        art.date = '%s/%s/01' % (pubDate.find('year').text,
            #                        pubDate.find('month').text.rjust(2,'0'))
            #else:
            #    art.date = '-'

            # 2/15/23 new code WTS2-1122
            if pubDate:
                day = '-'
                month = '-'
                year = '-'
                if (pubDate.find('day') != None):
                    day = pubDate.find('day').text.rjust(2,'0')
                    
                if (pubDate.find('month') != None):
                    month = pubDate.find('month').text.rjust(2,'0')
                if (pubDate.find('year') != None):
                    year = pubDate.find('year').text
                art.date = '%s/%s/%s' % (year, month, day)
            else:
                art.date = '-'
 
            art.pmcid  = artMetaE.find("article-id/[@pub-id-type='pmcaid']").text

            art.pmid   = artMetaE.find("article-id/[@pub-id-type='pmid']")
            if art.pmid != None:
                art.pmid = artMetaE.find("article-id/[@pub-id-type='pmid']").text
            if self._wantArticle(art):  # queue up the download in Dispatcher
                toDownload = toDownload + 1
                if self.getPdf:	self._queuePdfFile(art, artE)

        # Run the Dispatcher, this runs a bunch of downloads concurrently
        progress("Trying to download %d PDFs\n" % toDownload)
        debug('%s : trying to download %d PDFs' % (journalName, toDownload))
        self._runPdfQueue()
        return

    # ---------------------

    def _runPdfQueue(self, ):
        """ Run all the downloads in self.dispatcher
        """
        self.dispatcher.wait()

        for i in range(len(self.cmds)):
            idx = self.cmdIndexes[i]
            article = self.articles[i]
            debug('PMID_%s.pdf' % article.pmid)
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
        """ Queue up a download in self.dispatcher
        """
        ## get the URL to download
        linkUrl = getPdfUrl(article.pmcid)

        if linkUrl == '':
            self.curReporter.gotNoPdf(article)
            if self.verbose: progress('p')
            return

        if not self.writeFiles: return	# don't really output

        # uncomment this to see exactly which PMC IDs will be downloaded
        # debug('Scheduling PMC%s' % str(article.pmcid))

        ## generate desired filename of downloaded PDF
        if article.pmid:
            pdfFilename = "PMID_%s.pdf" % str(article.pmid)
        else:
            pdfFilename = "PMC%s.pdf" % str(article.pmcid)

        ## generate the download command
        cmd = getPdfCmd(linkUrl, self.curOutputDir, pdfFilename)
        #if self.verbose: progress('\n' + cmd + '\n')

        ## queue up the command
        idx = self.dispatcher.schedule(cmd)
        self.cmdIndexes.append(idx)
        self.cmds.append(cmd)
        self.articles.append(article)
        return
    # ---------------------
   
    def _wantArticle(self, article):
        """ Return True if we want this article
        """
        if not article.pmid:                          # no PMID
            self.curReporter.skipNoPMID(article)
            return False

        if self.pubmedWithPDF.contains(article.pmid): # already in MGI
            self.curReporter.skipInMgi(article)
            return False

        if article.type in self.articleTypes:	     # know this type
            if not self.articleTypes[article.type]:  # but don't want it
                self.curReporter.skipWrongType(article)
                return False
        else:	# not seen this type before. Report it and skip
            self.curReporter.skipNewType(article)
            return False

        return True
    # ---------------------

    def _createOutputDir(self, journalName):
        """ create an output directory for this journalName
            Currently, all PDFs for all journals are written to the same place
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
        #progress("Error finding OA link for PMC%s. Code='%s'. Message='%s'\n" % (pmcid, code, msg))
        return ''

    # Get file URL. Use PDF link if it exists, if not assume tgz link exists
    linkE = ele.find('./records/record/link/[@format="pdf"]')
    if linkE == None:		# no direct PDF link
        linkE = ele.find('./records/record/link/[@format="tgz"]')
        # Seems like this could fail, or could find .tgz but no PDF within
    #else: print "PMC%s had direct pdf link" % str(pmcid)

    print(linkE)
    return linkE.attrib['href']
# ---------------------

def getPdfCmd(linkUrl,	# URL to download from
    outputDir,		# directory where to store the file
    fileName,		# file name itself (presumably with .pdf)
    ):
    """ Return Unix command to Download the PDF at url.
        This is a command argv list.
    """
    # set up for Jon's cool download script (uses curl) to get the PDF
    return ["./download_pdf.sh", linkUrl, outputDir, fileName]
# ---------------------

def checkPdfCmd(cmd,	# the command itself (as argv list)
    retcode,
    stdout,
    stderr,
    ):
    """ Check the retcode and stdout, stderr for this command.
        Report if there are any problems
        Return true if all ok.
    """
    if retcode != 0:
        progress("Issue running pdf download\n")
        progress("retcode %d on: '%s'\n" % (retcode, " ".join(cmd) ))
        if stdout[0] == "Error: no PDF found in gzip file\n": 
            progress("stdout from cmd: Issue: no PDF found in gzip file\n")
        elif stdout[0].find('curl did not complete') != -1:
            progress('curl did not complete, gzip file removed')
        else:
            progress("stdout from cmd: '%s'\n" % stdout)
            progress("stderr from cmd: '%s'\n" % stderr)
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
    cmd = getPdfCmd(linkUrl, outputDir, fileName)

    results = subprocess.run(cmd, capture_output=True, text=True)

    return checkPdfCmd(cmd, results.returncode, results.stdout, results.stderr)
# ---------------------

# --------------------------
# helper routines
# --------------------------

def progress(s):
    ''' write some progress info'''
    sys.stdout.write(s)
    sys.stdout.flush()
# ---------------------
