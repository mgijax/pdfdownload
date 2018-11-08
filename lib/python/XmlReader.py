# Name: XmlReader.py
# Purpose: parse a string of XML and provide access to its various elements & their attributes.
#    This is a short-term replacement for usage of Python 2.7's xml.etree.ElementTree, but with
#    very limited functionality (so we can run on Python 2.4 for now).
# Functionality Supported:
#    1. Need to be able to parse a string of XML into an element.
#    2. An element must have a tag (name) and can have dictionary of attributes, a list of child elements,
#        and a text string.
#    3. Need a find() method that can find the first instance of a child element with a given tag.
#    4. Need a findall() method that returns a list of all instances of child elements with a given tag.
# Assumptions:
#    1. We can parse the entire XML string at once.  (It all will fit within available memory.)

import re
from fileinput import close

###--- classes ---###

class Element:
    def __init__ (self, tag):
        self.tag = tag.getTagName()
        self.children = []
        self.text = None
        self.attrib = tag.getAttributes()
        return
    
    def addElement(self, element):
        self.children.append(element)
        return
    
    def setText(self, text):
        self.text = text
        return
    
    def setAttribute(self, name, value):
        self.attrib[name] = value
        return
    
    def find(self, tag):
        subset = self.findall(tag)
        if len(subset) > 0:
            return subset[0]
        return None
    
    def findall(self, tag):
        subset = []
        for child in self.children:
            if child.tag == tag:
                subset.append(child)
        return subset

class Tag:
    Open = 'Open'       # opening tag -- expect a close to be forthcoming: "<foo>"
    Close = 'Close'     # to close an already open tag: "</foo>"
    Single = 'Single'   # open & close in a single tag: "<foo/>"

    def __init__ (self, tag):
        self.tagName = None
        self.tagType = None     # Open, Close, or Single
        self.attributes = {}
        
        match = TAG_NAME.match(tag)
        if not match:
            raise Exception('Invalid tag: %s' % tag)

        # identify tag type
        if match.group(1) == '/':
            self.tagType = Tag.Close
        elif tag[-2] == '/':
            self.tagType = Tag.Single
        else:
            self.tagType = Tag.Open

        # identify tag name
        self.tagName = match.group(2)

        # find the rest of the string, containing any attributes
        remainder = tag[match.span()[1]:]
        if remainder[-2:] == '/>':
            remainder = remainder[:-2]
        elif remainder[-1] == '>':
            remainder = remainder[:-1]
        remainder = remainder.strip()

        if remainder:
            self._setAttributes(remainder)
        return
        
    def _setAttributes(self, remainder):
        inName = False
        inValue = False
        openQuote = None
        name = ''
        value = ''
        
        lenRemainder = len(remainder)
        i = 0
        while i < lenRemainder:
            c = remainder[i]
            
            if inName:
                if c == '=':
                    inName = False
                else:
                    name = name + c

            elif inValue:
                if c == openQuote:
                    inValue = False
                    self.attributes[name] = value
                    name = ''
                    value = ''
                else:
                    value = value + c
                    
            elif c.strip() != '':
                if not name:
                    inName = True
                    name = c
                elif (c == SINGLE_QUOTE) or (c == DOUBLE_QUOTE):
                    inValue = True
                    openQuote = c
            
            i = i + 1
        return
    
    def getTagType(self):
        return self.tagType
    
    def getTagName(self):
        return self.tagName
    
    def getAttributes(self):
        return self.attributes

class Stack:
    def __init__ (self):
        self.stack = []
        return
    
    def push(self, item):
        self.stack.append(item)
        return
    
    def pop(self):
        if not self.stack:
            raise Exception('Cannot pop from empty stack')

        item = self.stack[-1]
        self.stack = self.stack[:-1]
        return item
    
    def isEmpty(self):
        return len(self.stack) == 0
    
    def __len__(self):
        return len(self.stack)

###--- constants ---###

SINGLE_QUOTE = "'"
DOUBLE_QUOTE = '"'

###--- standard regular expressions ---###

# group 1 is whether there's a slash after the opening angle bracket
# group 2 is the name of the tag
TAG_NAME = re.compile('[ \t\n]*<([/])?([A-Za-z_0-9\-\.]+)')

###--- functions ---###

def nextTag(s):
    # pull the next tag from the front of XML string 's', returning a tuple with:
    #    (text before the next tag, the next tag, the remainder of the string)
    # Note:  need to intelligently handle quoted strings, as these may contain angle brackets
    #    or nested quotes.  (double quotes can contain single quotes in the string, and vice versa)

    inTag = False                   # True if we're processing a tag
    inQuotedString = False          # True if we're currently in a quoted string within a tag
    openQuote = None                # which type of quote was used to open the current quoted string?
    beforeTag = ''                  # text found before the next tag begins
    tag = ''                        # text of the next tag itself
    lenS = len(s)
    
    i = 0
    while i < lenS:
        c = s[i]
        
        if not inTag:
            if c == '<':
                inTag = True
                tag = c
            else:
                beforeTag = beforeTag + c

        elif inQuotedString:
            if (c == openQuote):
                inQuotedString = False
            tag = tag + c
                
        elif (c == SINGLE_QUOTE) or (c == DOUBLE_QUOTE):
            inQuotedString = True
            openQuote = c
            tag = tag + c
         
        elif c == '>':
            inTag = False
            tag = tag + c
            return beforeTag, tag, s[i+1:]
            
        else:
            tag = tag + c
        
        i = i + 1
     
    return s, '', ''

def fromstring(s):
    # traverse 's' and populate needed Element objects.
    
    allElements = []        # list of all root-level elements
    openElements = Stack()  # has open Elements

    interveningText, tagString, remainder = nextTag(s)

    while (tagString or remainder):
        if interveningText.strip() and not openElements.isEmpty():
            parent = openElements.pop()
            parent.setText(interveningText.strip())
            openElements.push(parent)
            
        # need to skip blank lines and the initial XML version definition line
        if tagString and (not tagString.startswith('<?xml')):

            tag = Tag(tagString)
            if tag.getTagType() == Tag.Open:
                openElements.push(Element(tag))

            elif tag.getTagType() == Tag.Close:
                openElement = openElements.pop()
                if openElement.tag != tag.getTagName():
                    raise Exception('Mismatching open/close tags: (%s, %s)' % (openElement.tag, tag.getTagName()))

                if openElements.isEmpty():
                    return openElement      # is the root

                parent = openElements.pop()
                parent.addElement(openElement)
                openElements.push(parent)
                    
            else:       # Single
                if openElements.isEmpty():
                    raise Exception('Found unexpected empty stack')
                
                parent = openElements.pop()
                parent.addElement(Element(tag))
                openElements.push(parent)
                
        interveningText, tagString, remainder = nextTag(remainder)
        
    raise Exception('Did not find end of XML document properly')

###--- self-test code ---###

failures = 0
def check(condition, errorMessage):
    global failures
    if not condition:
        print errorMessage
        failures = failures + 1
    return

if __name__ == '__main__':
    # example XML doc from Python documentation
    xml = '''<?xml version="1.0"?>
        <data>
            <country name="Liechtenstein">
                <rank>1</rank>
                <year>2008</year>
                <gdppc>141100</gdppc>
                <neighbor name="Austria" direction="E"/>
                <neighbor name="Switzerland" direction="W"/>
            </country>
            <country name="Singapore">
                <rank>4</rank>
                <year>2011</year>
                <gdppc>59900</gdppc>
                <neighbor name="Malaysia" direction="N"/>
            </country>
            <country name="Panama">
                <rank>68</rank>
                <year>2011</year>
                <gdppc>13600</gdppc>
                <neighbor name="Costa Rica" direction="W"/>
                <neighbor name="Colombia" direction="E"/>
            </country>
        </data>'''
    root = fromstring(xml)
    
    check(root.tag == 'data', 'Unrecognized root tag name')
    check(len(root.children) == 3, 'Incorrect number of children')
    check(root.find('country').attrib['name'] == 'Liechtenstein', 'Wrong country name')
    check(root.findall('country')[1].find('rank').text == '4', 'Wrong rank')
    check(root.findall('country')[2].find('neighbor').attrib['name'] == 'Costa Rica', 'Wrong neighbor')
    check(root.find('country').find('neighbor').attrib['direction'] == 'E', 'Wrong direction')
    check(len(root.findall('country')[2].findall('neighbor')) == 2, 'Wrong number of neighbors')

    if failures:
        raise Exception('%d test failures (see above)' % failures)
    else:
        print 'All tests passed'