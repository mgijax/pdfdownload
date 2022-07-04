# Name: mapping_cache.py
# Purpose: stores as a temp file a cache of key/value pairs, reads temp file to recreate, etc.
# Notes:
#    1. Used in download_elsevier_papers.py to store already-retrieved publication dates for
#    each PubMed ID, saving re-requests in future runs.
#    2. By default, stores files in the /tmp directory, but can be configured to use a different
#    directory for better persistence.
#    3. Assumes that keys and values are simple text strings (not python objects).

import os

###--- Constants ---###

DEFAULT_DIR = '/tmp'        # By default, store in temp directory.  Data will go away on server restart.

class MapCache:
    def __init__ (self,
        filename,           # string; name of the file
        directory = None,   # string; path to the file (defaults to DEFAULT_DIR)
        replace = False     # boolean; ignore the existing file and replace it (True) or not (False)?
        ):
        # constructor
        
        if (directory == None):
            self.path = os.path.join(DEFAULT_DIR, filename)
        elif os.path.exists(directory):
            self.path = os.path.join(directory, filename)
        else:
            raise Exception('Unknown directory in mapping_cache: %s' % directory)
        
        self.contents = {}
        if (not replace) and (os.path.exists(self.path)):
            self._load()
        return 
    
    ###--- private methods ---###
    
    def _findDelimiter(self):
        # Identify a minimal-length delimiter to use between keys and values in the output file.
        # Delimiter will be a string that does not appear in any keys or values.
        
        chars = ' ,.;:-_=+[]{}|!@#$%^&*()0123456789abcdefghijklmnoprstuvwxyz'
        strings = list(self.contents.keys()) + list(self.contents.values())
        delim = ''
        match = True
        print('strings these are a list of keys and values from the cache: %s' % strings)
        # Until we find a delimiter that matches nothing in 'strings', keep going.
        while match:

            # Go through the set of characters, adding each one in sequence to the current 'delim' to see
            # if we can find a string with not matches in 'strings' (to use for our delimiter).
            for c in chars:
                match = False                   # assume it doesn't match
                trial = delim + c               # add to the current delimiter value
                for s in strings:
                    if s.find(trial) >= 0:      # If this 'trial' was found in 's', go back and try another character.
                        match = True
                        break

                # If the current 'trial' was not found in any of the 'strings', that can be our delimiter.
                if not match:
                    return trial
                
            # We got through the set of 'chars' without finding a delimiter, so just grab the last character,
            # add it on, and start a new round where we'll add other characters to it.
            if match:
                delim = delim + chars[-1]

        # Really, we shouldn't get here as we should return from within the loop.  So this is just in case.
        return delim
    
    def _load(self):
        # Read the data for this mapping from the data file, and populate this mapping accordingly.  See
        # file format near the save() method.
        self.contents = {}
        fp = open(self.path, 'r')
        lines = fp.readlines()
        fp.close()
        
        if len(lines) == 0:
            return 
        
        delimiter = lines[0][:-1]        # pick up from first line, minus the line break character
        for line in lines[1:]:
            if line:
                columns = line[:-1].split(delimiter)
                if len(columns) > 1:
                    self.contents[columns[0]] = columns[1]
        return 
    
    ###--- public methods ---###
    
    def put(self, key, value):
        # add the given 'value' for the given 'key'
        self.contents[key] = value
        return
    
    def get(self, key):
        # get the value corresponding to the given 'key', or None if undefined
        if key in self.contents:
            return self.contents[key]
        return None
    
    def size(self):
        # get count of entries in this cache
        return len(self.contents)

    def getPath(self):
        # get full path to the saved version of this cache
        return self.path
    
    def contains(self, key):
        # returns True if this cache contains the given 'key', False if not
        return key in self.contents

    # File format for _load() and save():
    # 1. Top line of the file contains the delimiter used between key and value for subsequent lines.
    # 2. The delimiter is chosen to be one or more characters that do not appear in any of the keys or values.
    # 3. Lines after the first each contain one key/value pair, separated by the delimiter from line one.
    
    def save(self):
        # Write out a file for this mapping, using the format described above.
        delimiter = self._findDelimiter()
        fp = open(self.path, 'w')
        fp.write('%s\n' % delimiter)
        for key in self.contents.keys():
            fp.write('%s%s%s\n' % (key, delimiter, self.contents.get(key)))
        fp.close()
        return
    
