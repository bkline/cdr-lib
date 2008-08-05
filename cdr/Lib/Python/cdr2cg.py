#----------------------------------------------------------------------
#
# $Id: cdr2cg.py,v 1.25 2008-08-05 14:49:02 venglisc Exp $
#
# Support routines for SOAP communication with Cancer.Gov's GateKeeper.
#
# $Log: not supported by cvs2svn $
# Revision 1.24  2008/06/03 21:14:49  bkline
# Cleaned up code to extract error information from the Err elements
# returned in CDR server responses.  Replaced StandardError exceptions
# with Exception objects, as StandardError will be removed from the
# exception heirarchy at some point.
#
# Revision 1.23  2007/04/12 20:03:53  venglisc
# Modified name for MFP to Interim-Export.
#
# Revision 1.22  2007/01/11 16:39:48  bkline
# Made sure that when the module's host attribute is modified by outside
# code the new value is used instead of the original value.
#
# Revision 1.21  2006/06/14 12:50:36  bkline
# Chen changed the interface to send back n/m as docCount element,
# where n is the total number of packets received, and m is the
# highest document sequence number received.  Modified the parser
# to extract these numbers when present in the PubEventResponse.
#
# Revision 1.20  2006/06/08 14:08:45  bkline
# Modifications to support enhancements to GateKeeper for more frequent
# publishing.
#
# Revision 1.19  2005/12/02 22:43:51  venglisc
# Added FRANCK as a valid host to be able to send data from FRANCK to the
# Cancer.gov TEST4 server.
#
# Revision 1.18  2005/03/09 16:04:51  bkline
# Switch CG development server from dev1 to test4 (per Olga Rosenbaum).
#
# Revision 1.17  2004/12/23 01:36:28  bkline
# Juggled some servers at the request of Cancer.gov (Chen Ling).
#
# Revision 1.16  2003/03/25 19:00:24  pzhang
# Used physical path for PDQDTD.
#
# Revision 1.15  2003/02/14 20:04:47  pzhang
# Dropped DocType and added description at prolog level.
#
# Revision 1.14  2002/11/14 20:22:07  pzhang
# Added version infor for CG team.
#
# Revision 1.13  2002/11/01 19:16:05  pzhang
# Used binary write in log.
#
# Revision 1.12  2002/10/23 20:44:20  pzhang
# Used a single GateKeeper with 3 different sources: Development,
#     Staging, and Production.
#
# Revision 1.11  2002/10/16 16:34:02  pzhang
# Made GateKeeper hostname depend on localhost.
#
# Revision 1.10  2002/10/03 16:04:59  pzhang
# Logged HTTP error in log file and StandardError.
#
# Revision 1.9  2002/09/30 19:29:53  pzhang
# Accepted docType and docId for command line testing.
#
# Revision 1.8  2002/09/13 16:51:40  pzhang
# Changed PDQDTD to point to MAHLER.
#
# Revision 1.7  2002/08/22 12:40:25  bkline
# Added publish preview.
#
# Revision 1.6  2002/07/25 20:56:01  pzhang
# Split docTemplate into docTemplateHead and docTemplateTail
# and encoded them to UTF-8.
#
# Revision 1.5  2002/07/23 15:02:25  pzhang
# Added PDQDTD string for PDQ.dtd location.
#
# Revision 1.4  2002/06/13 19:20:16  bkline
# Made some logging conditional.
#
# Revision 1.3  2002/05/14 12:56:05  bkline
# Added PUBTYPES dictionary.  Added code to retry request a few times if
# the SOAP server drops the connection unexpectedly.
#
# Revision 1.2  2002/05/09 14:06:08  bkline
# Added removeDocuments() convenience function.
#
# Revision 1.1  2002/05/09 12:51:50  bkline
# Module for communicating with Cancer.Gov SOAP server (GateKeeper).
#
#----------------------------------------------------------------------
import httplib, re, sys, time, xml.dom.minidom, socket, string

#----------------------------------------------------------------------
# Module data.
#----------------------------------------------------------------------
debuglevel          = 0
localhost           = socket.gethostname()
source              = "CDR Staging"
host                = "gatekeeper.cancer.gov"
testhost            = "test4.cancer.gov"
if string.upper(localhost) == "BACH":
    source = "CDR Production"
elif string.upper(localhost) == "MAHLER":
    source = "CDR Development"
    host   = testhost
elif string.upper(localhost) == "FRANCK":
    source = "CDR Testing"
    host   = testhost
port                = 80
soapNamespace       = "http://schemas.xmlsoap.org/soap/envelope/"
application         = "/GateKeeper/GateKeeper.asmx"
headers             = {
    'Content-type': 'text/xml; charset="utf-8"',
    'SOAPAction'  : 'http://gatekeeper.cancer.gov/Request'
}

#----------------------------------------------------------------------
# Module data used by publishing.py and cdrpub.py.
#----------------------------------------------------------------------
PUBTYPES = {
    'Full Load'       : 'Send all documents to Cancer.gov',
    'Export'          : 'Send specified documents to Cancer.gov',
    'Interim (Export)': 'Send daily update to Cancer.gov',
    'Remove'          : 'Delete documents from Cancer.gov',
    'Hotfix (Remove)' : 'Delete individual documents from Cancer.gov',
    'Hotfix (Export)' : 'Send individual documents to Cancer.gov'
}
PDQDTD = "d:\\cdr\licensee\\pdqCG.dtd"

#----------------------------------------------------------------------
# XML wrappers.
#----------------------------------------------------------------------
requestWrapper      = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="%s"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" 
               xmlns:xsd="http://www.w3.org/2001/XMLSchema">
 <soap:Body>
%s
 </soap:Body>
</soap:Envelope>"""

initRequestTemplate = """\
  <Request xmlns="http://gatekeeper.cancer.gov">
   <source>%s</source>  
   <requestID>Initiate Request</requestID>
   <message>
    <PubEvent>
     <pubType>%s</pubType>
     <description>%s</description>
     <lastJobID>%s</lastJobID>
    </PubEvent>
   </message>
  </Request>"""

dataPrologTemplate = """\
  <Request xmlns="http://gatekeeper.cancer.gov">
   <source>%s</source>   
   <requestID>%s</requestID>
   <message>
    <PubEvent>
     <pubType>%s</pubType>     
     <description>%s</description>
     <lastJobID>%s</lastJobID>
     <docCount>%s</docCount>
    </PubEvent>
   </message>
  </Request>"""

jobCompleteTemplate = """\
  <Request xmlns="http://gatekeeper.cancer.gov">
   <source>%s</source>   
   <requestID>%s</requestID>
   <message>
    <PubEvent>
     <pubType>%s</pubType>     
     <docCount>complete</docCount>
    </PubEvent>
   </message>
  </Request>"""

docTemplateHead= """\
  <Request xmlns="http://gatekeeper.cancer.gov">
   <source>%s</source>   
   <requestID>%s</requestID>
   <message>
    <PubData>
     <docNum>%s</docNum>
     <transactionType>%s</transactionType>
     <CDRDoc Type="%s" ID="CDR%010d" Version="%d">"""

docTemplateTail = """\
     </CDRDoc>
    </PubData>
   </message>
  </Request>"""

pubPreviewTemplate = """
  <ReturnXML xmlns="http://gatekeeper.cancer.gov/CDRPreview/">
   <content>%s</content>
   <template_type>%s</template_type>
  </ReturnXML>
"""

class Fault:
    """
    Holds detailed information about a SOAP failure.

    Public attributes:

        faultcode
            indicates the general nature of the problem, such as
            whether it originates on the client or the server

        faultstring
            description of the problem, possibly including a stack
            trace from the SOAP server
    """

    def __init__(self, node):
        faultCodeElem     = getChildElement(node, "faultcode", True)
        faultStringElem   = getChildElement(node, "faultstring", True)
        self.faultcode    = getTextContent(faultCodeElem)
        self.faultstring  = getTextContent(faultStringElem)
    def __repr__(self):
        return (u"Fault (faultcode: %s, faultstring: %s)" %
                (self.faultcode, self.faultstring))

class PubEventResponse:
    """
    Holds detailed information from a response to a request initiation
    or data prolog message.
    
    Public attributes:

        pubType
            One of Hotfix, Export, Remove, or Full Load; echoed
            from request

        lastJobId
            ID of last job of this type successfully processed by
            Cancer.Gov

        docCount
            echoed from request (data prolog message only)
    """

    def __init__(self, node):
        pubTypeElem        = getChildElement(node, "pubType", True)
        lastJobIdElem      = getChildElement(node, "lastJobID")
        nextJobIdElem      = getChildElement(node, "nextJobID")
        docCountElem       = getChildElement(node, "docCount")
        self.pubType       = getTextContent(pubTypeElem)
        self.highestDocNum = None
        self.totalPackets  = None
        if lastJobIdElem is not None:
            lastJobText = getTextContent(lastJobIdElem)
            try:
                self.lastJobId = int(lastJobText)
            except:
                self.lastJobId = lastJobText
        else:
            self.lastJobId = None
        if nextJobIdElem is not None:
            nextJobText = getTextContent(nextJobIdElem)
            try:
                self.nextJobId = int(nextJobText)
            except:
                self.nextJobId = nextJobText
        else:
            self.nextJobId = None
        if docCountElem is not None:
            docCountText = getTextContent(docCountElem)
            try:
                self.docCount = int(docCountText)
            except:
                self.docCount = docCountText
                try:
                    totalPackets, highestDocNum = docCountText.split(u'/')
                    self.totalPackets = int(totalPackets)
                    self.highestDocNum = int(highestDocNum)
                except:
                    pass
        else:
            self.docCount = None
    def __repr__(self):
        return (u"PubEventResponse "
                u"(pubType: %s, lastJobId: %s, nextJobId: %s, docCount: %s, "
                u"totalPackets: %s, highestDocNum: %s)"""
                % (self.pubType, self.lastJobId, self.nextJobId,
                   self.docCount, self.totalPackets, self.highestDocNum))

class PubDataResponse:
    """
    Holds detailed information from a response to a data transfer
    request.

    Public attributes:

        docNum
            echoed from request
    """

    def __init__(self, node):
        child = getChildElement(node, "docNum", True)
        self.docNum = int(getTextContent(child))
    def __repr__(self):
        return u"PubDataResponse (docNum: %d)" % self.docNum

class HttpError(Exception):
    def __init__(self, xmlString):
        self.xmlString = xmlString
        bodyElem   = extractBodyElement(xmlString)
        faultElem  = bodyElem and getChildElement(bodyElem, "Fault") or None
        self.fault = faultElem and Fault(faultElem) or None
    def __repr__(self):
        if not self.fault:
            return self.xmlString
        return u"""\
HttpError (faultcode: %s, faultstring: %s)""" % (self.fault.faultcode,
                                                self.fault.faultstring)

class Response:
    """
    Encapsulates the Cancer.Gov GateKeeper response to a SOAP request.

    Public attributes:

        type
            OK, Not Ready, or Error

        message
            e.g., Ready to Accept Data, Invalid Request, Bad lastJobID,
            etc.

        details
            PubEventResponse for request initiation and data prolog
            exchanges; PubDataResponse for document transfers

        fault
            SOAP fault object containing faultcode and faultstring
            members in the case of a SOAP failure
    """
    
    def __init__(self, xmlString, publishing = True):

        """Extract the values from the server's XML response string."""

        self.xmlString   = xmlString
        self.bodyElem    = extractBodyElement(xmlString)
        self.faultElem   = getChildElement(self.bodyElem, "Fault")
        self.fault       = self.faultElem and Fault(self.faultElem) or None
        self.publishing  = publishing
        if publishing:
            respElem         = extractResponseElement(self.bodyElem)
            respTypeElem     = getChildElement(respElem, "ResponseType", 1)
            respMsgElem      = getChildElement(respElem, "ResponseMessage", 1)
            peResponseElem   = getChildElement(respElem, "PubEventResponse")
            pdResponseElem   = getChildElement(respElem, "PubDataResponse")
            self.type        = getTextContent(respTypeElem)
            self.message     = getTextContent(respMsgElem)
            if peResponseElem:
                self.details = PubEventResponse(peResponseElem)
            elif pdResponseElem:
                self.details = PubDataResponse(pdResponseElem)
            else:
                self.details = None
        else:
            self.xmlResult   = extractXmlResult(self.bodyElem)
    def __repr__(self):
        pieces = [u"cdr2cg.Response "]
        if self.publishing:
            pieces.append(u"(type: %s, message: %s, details: %s" %
                          (self.type, self.message, self.details))
        else:
            pieces.append(u"(publish preview document")
        if self.fault:
            pieces.append(u", fault: %s" % self.fault)
        pieces.append(u")")
        return u"".join(pieces)

def getTextContent(node):
    text = ''
    for n in node.childNodes:
        if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
            text = text + n.nodeValue
    return text

def getChildElement(parent, name, required = False):
    child = None
    for node in parent.childNodes:
        if node.nodeType == node.ELEMENT_NODE and node.localName == name:
            child = node
            break
    if required and not child:
        raise Exception("Response missing required %s element" % name)
    return child

def extractResponseElement(bodyNode):
    requestResponse = getChildElement(bodyNode,        "RequestResponse", 1)
    requestResult   = getChildElement(requestResponse, "RequestResult",   1)
    response        = getChildElement(requestResult,   "Response",        1)
    return response

def extractBodyElement(xmlString):
    dom     = xml.dom.minidom.parseString(xmlString)
    docElem = dom.documentElement
    body    = getChildElement(docElem, "Body", True)
    return body

# For publish preview.
def extractXmlResult(bodyNode):
    xmlResponse = getChildElement(bodyNode, "ReturnXMLResponse")
    if xmlResponse:
        xmlResult = getChildElement(xmlResponse, "ReturnXMLResult")
        if xmlResult:
            xmlString = getTextContent(xmlResult)
            return xmlString.replace("<![CDATA[", "").replace( "]]>", "")
    return None

def logString(type, str):
    if debuglevel:
        open("d:/cdr/log/cdr2cg.log", "ab").write("==== %s %s ====\n%s\n" % 
            (time.ctime(), type, re.sub("\r", "", str)))

def sendRequest(body, app = application, host = host, headers = headers):

    # At one time it was tricky finding out where the requests were going.
    logString("REQUEST", "sending request to %s" % host)
    
    # Defensive programming.
    tries = 3
    response = None
    while tries:
        try:

            # Set up the connection and the request.
            conn    = httplib.HTTPConnection(host, port)
            request = requestWrapper % (soapNamespace, body)
            logString("REQUEST", request)

            # Submit the request and get the headers for the response.
            conn.request("POST", app, request, headers)
            response = conn.getresponse()
            #sys.stderr.write("got response from socket %s\n" % repr(conn.sock))

            # Skip past any "Continue" responses.
            while response.status == 100:
                response.msg = None
                response.begin()

            # We can stop trying now, we got it.
            tries = 0
        except:
            if debuglevel:
                sys.stderr.write("caught http exception; trying again...\n")
            logString("RETRY", "%d retries left" % tries)
            if not tries:
                raise
            time.sleep(.5)
            tries -= 1

    # Check for failure.
    if not response:
        raise Exception("tried to connect 3 times unsuccessfully")
    
    if response.status != 200:
        resp = response.read()
        logString("HTTP ERROR", resp)
        resp = "(occurred at %s) (%s)" % (time.ctime(), resp)
        raise Exception("HTTP error: %d (%s) %s" % (response.status,
                                                    response.reason,
                                                    resp))

    # Get the response payload and return it.
    data = response.read()
    logString("RESPONSE", data)
    return data

def initiateRequest(jobDesc, pubType, lastJobId):
    xmlString = sendRequest(initRequestTemplate % (source,
                                                   pubType,
                                                   jobDesc,
                                                   lastJobId),
                            host = host)
    return Response(xmlString)
    
def sendDataProlog(jobDesc, jobId, pubType, lastJobId, docCount):
    xmlString = sendRequest(dataPrologTemplate % (source,
                                                  jobId,
                                                  pubType,
                                                  jobDesc,
                                                  lastJobId,
                                                  docCount),
                            host = host)
    return Response(xmlString)

def sendDocument(jobId, docNum, transType, docType, docId, docVer, doc = ""): 
    
    # The mixed UTF-8 and ASCII string is disallowed by python.
    req = docTemplateHead % (source, jobId, docNum, transType, 
                             docType, docId, docVer)    
    req = req.encode('utf-8') + doc   
    req += docTemplateTail.encode('utf-8') 
   
    xmlString = sendRequest(req, host = host)
   
    return Response(xmlString)

def sendJobComplete(jobId, pubType):
    response = sendRequest(jobCompleteTemplate % (source, jobId, pubType),
                           host = host)
    return Response(response)

def pubPreview(xml, typ):
    req = pubPreviewTemplate % (xml, typ)
    xmlString = sendRequest(
        req, 
        app     = '/CDRPreview/WSProtocol.asmx',
        host    = host,
        headers = { 'Content-type': 'text/xml; charset="utf-8"',
                    'SOAPAction'  :
                    'http://gatekeeper.cancer.gov/CDRPreview/ReturnXML' })
    return Response(xmlString, 0)

#----------------------------------------------------------------------
# Take it out for a test spin.
#----------------------------------------------------------------------
if __name__ == "__main__":

    # Set the command-line arguments.
    jobId     = 4
    lastJobId = 3
    if len(sys.argv) > 1: jobId = int(sys.argv[1])
    if len(sys.argv) > 2: lastJobId = int(sys.argv[2])
    if len(sys.argv) > 3: docType = sys.argv[3]
    if len(sys.argv) > 4: docId = int(sys.argv[4])
    sys.stderr.write("job ID %d\n" % jobId)
    sys.stderr.write("last job ID %d\n" % lastJobId)
    debuglevel = 1

    # See if the GateKeeper is awake.
    sys.stderr.write("initiating request ...\n")
    response = initiateRequest("Command-line testing.", "Export", lastJobId)
    if response.type != "OK":
        print "%s: %s" % (response.type, response.message)
        if response.fault:
            print "%s: %s" % (response.fault.faultcode,
                              response.fault.faultstring)
        elif response.details:
            print "Last job ID from server: %d" % response.details.lastJobId
        # sys.exit(1)

    # Prepare the server for a batch of documents.
    sys.stderr.write("sending data prolog ...\n")
    response = sendDataProlog("Command-line testing.", jobId, "Export", 
                              response.details.lastJobId, 1)
    if response.type != "OK":
        print "%s: %s" % (response.type, response.message)
        # sys.exit(1)

    # Send the first document.
    sys.stderr.write("sending first document ...\n")
    response = sendDocument(jobId, 1, "Export", docType, docId, 1,
                            open("CDR%d.xml" % docId).read())
    if response.type != "OK":
        print "%s: %s" % (response.type, response.message)
        sys.exit(1)
