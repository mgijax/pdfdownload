# Name: caches.py
# Purpose: contains any caches (database or otherwise) for scripts in the pdfdownload product
# Assumes: importing script has already set PYTHONPATH so we can find pg_db library

import pg_db

###--- globals ---###

INITIALIZED = False

###--- functions ---###

def initialize(dbUser, dbPassword, dbServer, dbDatabase):
    # initialize this module by passing in the db connection info
    global INITIALIZED

    pg_db.set_sqlLogin(dbUser, dbPassword, dbServer, dbDatabase)
    INITIALIZED = True
    return

###--- classes ---###

class IDCache:
    # Is: a cache of IDs
    # Has: a cache of IDs and some convenience methods
    # Does: tests for IDs' existence in the cache; filters lists of IDs based on cache contents
    
    def __init__ (self):
        # basic constructor
        
        if not INITIALIZED:
            raise Exception("Must call caches.initialize() method")
        
        self.cache = set()
        self.populateCache()
        return
    
    def __len__(self):
        # returns number of IDs currently cached
        
        return len(self.cache)

    def __contains__ (self,
        accID           # string; ID to test to see if it's in the cache
        ):
        # returns True if 'accID' is in the set of cached IDs

        return accID in self.cache
    
    def populateCache(self):
        # stub method; to contain details of how this cache is populated
        
        raise Exception("Must implement populateCache() method in subclass")
    
    def excludeCached(self,
        accIDs        # list of strings, each of which is an ID
        ):
        # return a list that contains all IDs from 'accIDs' that are not in the cache

        subset = []
        
        for accID in accIDs:
            if accID not in self.cache:
                subset.append(accID)

        return subset
    
    def contains(self, accID):
        # return True if accID is in the cache, False if not

        return accID in self.cache

class DOICache (IDCache):
    # Is: an IDCache of all DOI IDs that are currently in the database
    
    def populateCache(self):
        cmd = '''
            select doiid
            from bib_citation_cache
            where doiid is not null
            '''

        for row in pg_db.sql(cmd, 'auto'):
            self.cache.add(row['doiid'])
        return
    
class PubMedWithPDF (IDCache):
    # Is: an IDCache of PubMed IDs for which we have PDFs already
    
    def populateCache(self):
        cmd = '''
            select c.pubmedid
            from bib_workflow_data r, bib_citation_cache c
            where r.hasPDF = 1
            and r._Refs_key = c._refs_key
            and c.pubmedid is not null
            '''

        for row in pg_db.sql(cmd, 'auto'):
            self.cache.add(row['pubmedid'])
        return
