#!/usr/bin/env python3

"""
These are tests for SciDirectLib.py

Usage:   python test_SciDirectLib.py [-v]
"""
import sys
import unittest
import os
import os.path
import json
import requests
import SciDirectLib as sdl

## Initialize Elsevier API client
apikey = os.environ['ELSEVIER_APIKEY']
insttoken = os.environ['ELSEVIER_INSTTOKEN']
elsClient = sdl.ElsClient(apikey, inst_token=insttoken)

######################################

class ElsClient_tests(unittest.TestCase):
    def test_execGetRequest_badContentType(self):
        url = sdl.url_base + 'content/article/pii/'
        self.assertRaises(ValueError, elsClient.execGetRequest, url,
                                                            contentType='foo')
    def test_execGetRequest_getarticle(self):
        pii = 'S0021925821005226'
        doi = '10.1016/j.jbc.2021.100733'
        url = sdl.url_base + 'content/article/pii/' + str(pii)
        ref = elsClient.execGetRequest(url)['full-text-retrieval-response']
        #print(ref.keys())
        #print(json.dumps(ref['coredata'], sort_keys=True, indent="  "))
        self.assertEqual(ref['coredata']['prism:doi'], doi)

        status = elsClient.getRequestStatus()
        self.assertEqual(status['status_code'], 200)
        self.assertEqual(status['status_msg'], 'json data retrieved')
    
    def test_execGetRequest_getpdf(self):
        pii = 'S0021925821005226'
        url = sdl.url_base + 'content/article/pii/' + str(pii)
        pdf = elsClient.execGetRequest(url, contentType='pdf')
        #fp = open(pii + '.pdf', 'wb')
        #fp.write(pdf)
        #fp.close()
        self.assertEqual(pdf[:8], b'%PDF-1.7')
        self.assertEqual(len(pdf), 5111458) # fails if publisher updates the pdf

    def test_execGetRequest_httperror(self):
        url = sdl.url_base + 'content/article/pii/' + 'foo'
        self.assertRaises(requests.HTTPError, elsClient.execGetRequest, url)

    def test_execPutRequest(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : {   'sortBy' :'date',
                                    'offset' : 0,
                                    'show'   : 5
                                }
                 }
        url = sdl.url_base + 'content/search/sciencedirect'
        r = elsClient.execPutRequest(url, json.dumps(query))
        self.assertEqual(len(r['results']), 5)

# end class ElsClient_tests ######################################

class SciDirectSearch_tests(unittest.TestCase):

    def test_basicSearch(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : {   'sortBy' :'date',
                                    'offset' : 0,
                                    'show'   : 5
                                }
                 }
        sds = sdl.SciDirectSearch(elsClient, query, getAll=False)
        sds.execute()
        self.assertGreaterEqual(sds.getTotalNumResults(), 131)
        self.assertEqual(sds.getNumResults(), 5)
        self.assertEqual(len(sds.getResults()), 5)
        self.assertEqual(sds.getElsClient(), elsClient)
        self.assertEqual(sds.getQuery(), query)

    def test_emptySearch(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice AND football',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : { 'sortBy': 'date' }
                 }
        sds = sdl.SciDirectSearch(elsClient, query, getAll=False, maxResults=5)
        sds.execute()
        self.assertEqual(sds.getNumResults(), 0)
        self.assertEqual(sds.getTotalNumResults(), 0)

    def test_getAll(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : {   'sortBy' :'date',
                                    'offset' : 0,
                                    'show'   : 5
                                }
                 }
        sds = sdl.SciDirectSearch(elsClient, query, getAll=True,)
        sds.execute()
        self.assertGreaterEqual(sds.getTotalNumResults(), 131)
        self.assertEqual(sds.getNumResults(), sds.getTotalNumResults())
        self.assertEqual(len(sds.getResults()), sds.getNumResults())

    def test_getAllmax100(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : {   'sortBy' :'date',
                                    'offset' : 0,
                                    'show'   : 5
                                }
                 }
        sds = sdl.SciDirectSearch(elsClient, query, getAll=True,
                                                maxResults=100, increment=50)
        sds.execute()
        self.assertGreaterEqual(sds.getTotalNumResults(), 131)
        self.assertEqual(sds.getNumResults(), 100)
        self.assertEqual(len(sds.getResults()), sds.getNumResults())

    def test_iterator(self):
        query = {'pub'        : 'Bone',
                 'qs'         : 'mice AND "odontoblast differentiation"',
                 'loadedAfter': '2021-01-05T00:00:00Z',
                 'display'    : { 'sortBy': 'date' }
                 }
        sds = sdl.SciDirectSearch(elsClient, query, getAll=False,)
        sds.execute()
        piis = [r.getPii() for r in sds.getIterator()] # list of pii's in rslts
        self.assertTrue("S8756328221001630" in piis)

# end class SciDirecSearch_tests ######################################

class SciDirectReference_tests(unittest.TestCase):
    ref1Data = {      # taken from SciDirect search results. PMID 33417945
        "authors": [
          {
            "name": "Hongqiao Zhang",
            "order": 1
          },
          {
            "name": "Todd E. Morgan",
            "order": 2
          },
          {
            "name": "Henry Jay Forman",
            "order": 3
          }
        ],
        "doi": "10.1016/j.abb.2020.108749",
        "loadDate": "2021-01-05T00:00:00.000Z",
        "openAccess": False,
        "pages": {
          "first": "108749"
        },
        "pii": "S0003986120307578",
        "publicationDate": "2021-03-15",
        "sourceTitle": "Archives of Biochemistry and Biophysics",
        "title": "Age-related alteration in HNE elimination enzymes",
        "uri": "https://www.sciencedirect.com/science/article/pii/S0003986120307578?dgcid=api_sd_search-api-endpoint",
        "volumeIssue": "Volume 699"
        }

    def test_constructor_getters(self):
        r1 = sdl.SciDirectReference(elsClient, self.ref1Data) 
        self.assertEqual("S0003986120307578", r1.getPii())
        self.assertEqual("10.1016/j.abb.2020.108749", r1.getDoi())
        self.assertEqual("Archives of Biochemistry and Biophysics", r1.getJournal())
        self.assertEqual("Age-related alteration in HNE elimination enzymes", r1.getTitle())
        self.assertEqual("2021-01-05T00:00:00.000Z", r1.getLoadDate())
        self.assertEqual("2021-03-15", r1.getPublicationDate())
        self.assertEqual(self.ref1Data, r1.getSearchResultsFields())
        self.assertEqual(elsClient, r1.getElsClient())

    def test_fetching_details(self):
        r1 = sdl.SciDirectReference(elsClient, self.ref1Data) 
        #print(json.dumps(r1.getDetails(), sort_keys=True, indent="  "))
        self.assertEqual("33417945", r1.getPmid())
        self.assertEqual("rev", r1.getPubType())
        self.assertEqual("699", r1.getVolume())
        self.assertTrue('coredata' in r1.getDetails().keys())

    def test_fetching_pdf(self):
        r1 = sdl.SciDirectReference(elsClient, self.ref1Data) 
        self.assertEqual(b'%PDF-1.7', r1.getPdf()[:8])
        self.assertEqual(1173669, len(r1.getPdf()))
        #fp = open(r1.getPii() + '.pdf', 'wb')
        #fp.write(r1.getPdf())
        #fp.close()

# end class SciDirectReference_tests ######################################

if __name__ == '__main__':
    unittest.main()
