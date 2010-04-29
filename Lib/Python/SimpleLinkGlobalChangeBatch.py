#----------------------------------------------------------------------
# Batch portion of GlobalChangeSimpleLink.py
#
# $Id$
#
# $Log: not supported by cvs2svn $
# Revision 1.1  2009/07/08 03:04:55  ameyer
# Initial version.
#
#----------------------------------------------------------------------
import sys, socket, cgi, re, cdr, cdrdb, cdrcgi, cdrbatch, ModifyDocs

LF       = cdr.DEFAULT_LOGDIR + "/GlobalChange.log"
JOB_NAME = "SimpleLinkGlobalChangeBatch"

def fatal(msg, jobObj=None):
    """
    Log error message, abort job if possible, exit.

    Pass:
        Error message.
        Job object to abort, or None if not loaded.
    """
    # Identify the message
    msg = "%s: %s" % (JOB_NAME, msg)

    cdr.logwrite(msg, LF)
    if jobObj:
        jobObj.fail(msg)
    sys.exit(1)


def getConn():
    """
    Return a read-only connection to the database.
    Simple wrapper to catch and display exceptions.
    """
    try:
        conn = cdrdb.connect()
    except cdrdb.Error, info:
        fatal("Database error connecting: '%s'" % str(info))

    return conn


class SimpleLinkVars:
    """
    One instance of this class is created to hold all state variables
    maintained in the HTML forms.
    """

    # All the fields we recognize
    fieldList = ("srcDocTypeName", "srcFieldName",
                 "oldLinkRefIdStr", "oldLinkRefName",
                 "newLinkRefIdStr", "newLinkRefName",
                 "doRefs", "doHrefs", "emailList",
                 "runMode", "approved")

    def __init__(self, jobObj=None):
        """
        Read all of the variables stored in the CGI request object.

        Pass:
            jobObj - cdrbatch.CdrBatch object.
                If present, this class is being instantiated in a batch job.
                If None, this class is being instatiated by a CGI program
        """
        self.__batchJobObj = jobObj
        self.__cgi = True
        if self.__batchJobObj:
            self.__cgi = False

        # Variables originally from CGI forms
        # Dictionary of name (from fieldList) / value pairs
        self.vars = {}

        # If we're running in batch mode, get the variables from the
        #   batch job database tables
        if self.__batchJobObj:
            self.batchArgsToLinkVars()

        else:
            # We running as part of a CGI program, get vars from web form
            self.__fields = cgi.FieldStorage()
            for varName in SimpleLinkVars.fieldList:
                self.vars[varName] = self.__fields.getfirst(varName, None)

            # Doc ID fields have to be normalized to full form
            for varName in ("oldLinkRefIdStr", "newLinkRefIdStr"):
                if self.vars[varName]:
                    try:
                        self.vars[varName] = cdr.exNormalize(
                                                self.getVar(varName))[0]
                    except:
                        self.error("Can't convert %s to a valid CDR Doc ID" %
                                     self.vars[varName])
            # CDR Session
            self.session = cdrcgi.getSession(self.__fields) or ""

            # User command/request
            self.request = cdrcgi.getRequest(self.__fields) or None

    def error(self, errMsg):
        """
        Output error information to log or to user.

        Pass:
            errMsg - Error message.
        """
        if self.__cgi:
            cdrcgi.bail(errMsg)

        else:
            # Write to log and exit
            fatal(errMsg, self.__batchJobObj)
            sys.exit(1)


    def getVar(self, varName):
        """
        Return a variable value.

        Pass:
            Name of form variable to fetch.

        Return:
            Value.
        """
        if not self.vars.has_key(varName):
            cdr.logwrite("Internal Error: getVar('%s') unknown" % varName,
                          stackTrace=True)
            self.error("Internal Error: getVar('%s') unknown" % varName)

        return self.vars[varName]


    def showProgress(self):
        """
        Generate HTML to show what we've found so far

        Return:
            String of HTML.
            Empty string if no progress so far.
        """
        # If we've got anywhere at all, we must have a document type
        if not self.getVar("srcDocTypeName"):
            return ""

        html = u"""
<h3>Changing simple links for ...</h3>
<table>
""" + self.addProgress('Document type', self.getVar('srcDocTypeName'))

        if self.getVar('srcFieldName'):
            html += self.addProgress('Element', self.getVar('srcFieldName'))

        if self.getVar('oldLinkRefIdStr'):
            docIdStr = cdr.exNormalize(self.getVar('oldLinkRefIdStr'))[0]
            docData  = cdr.getAllDocsRow(docIdStr)
            docTitle = docData["title"]
            html += self.addProgress('Old link',
                                     "%s / %s" % (docIdStr, docTitle))

        if self.getVar('newLinkRefIdStr'):
            docIdStr = cdr.exNormalize(self.getVar('newLinkRefIdStr'))[0]
            docData  = cdr.getAllDocsRow(docIdStr)
            docTitle = docData["title"]
            html += self.addProgress('New link',
                                     "%s / %s" % (docIdStr, docTitle))

        if self.getVar('doRefs'):
            html += self.addProgress('Change cdr:refs', 'Yes')
        if self.getVar('doHrefs'):
            html += self.addProgress('Change cdr:hrefs', 'Yes')

        if self.getVar("emailList"):
            html += self.addProgress('Email results to',
                                      self.getVar("emailList"))

        if self.getVar('runMode'):
            html += self.addProgress('Run mode', self.getVar('runMode'))

        html += "</table>\n<hr />\n"

        return html

    def addProgress(self, prompt, value):
        """
        Construct one row of the showProgress table.

        Pass:
            prompt - Label for row.
            value  - Value for label.

        Return:
            HTML marked up string.
        """
        return u" <tr><td align='right'>%s: </td><td>%s</td></tr>\n" % \
                 (prompt, value)

    def saveContext(self, alreadyDone=None):
        """
        Generate HTML to save the state in hidden form variables.
        Only called when running in CGI mode.

        Pass:
            alreadyDone - Names that are already in the form.
                          If prompting for something, don't save that here.
        Return:
            String of HTML for embedding in the form to send to the client.
        """
        html = ""
        for varName in SimpleLinkVars.fieldList:
            if not alreadyDone or not varName in alreadyDone:
                varValue = ""
                if self.getVar(varName):
                    varValue = " value='%s'" % self.getVar(varName)
                html += " <input type='hidden' name='%s'%s />\n" % (
                        varName, varValue)

        # Add session
        if self.session:
            html += " <input type='hidden' name='%s' value='%s' />" % (
                    cdrcgi.SESSION, self.session)

        return html

    def linkVarsToBatchArgs(self):
        """
        Create a data structure suitable for use in passing arguments
        to a cdrbatch.CdrBatch job constructor.  Loads all the context
        variables into it.

        Return:
            Sequence of name/value pairs, not a dictionary.
        """
        argSeq = []
        for varName in SimpleLinkVars.fieldList:
            # None is an illegal batch job arg value, use "" instead
            varValue = ""
            if self.getVar(varName):
                varValue = self.getVar(varName)
            argSeq.append((varName, varValue))

        # Add session
        if self.session:
            argSeq.append(("session", self.session))

        return argSeq


    def batchArgsToLinkVars(self):
        """
        The reverse of linkVarsToBatchArgs()

        Loads self.vars from a batch job object.
        """
        batchArgs = self.__batchJobObj.getArgs()
        for varName in batchArgs.keys():
            self.vars[varName] = batchArgs[varName]
        if self.getVar("session"):
            self.session = self.getVar("session")


    def sendPage(self, formContent, subBanner=None, haveVars=None,
                 buttons='default'):
        """
        Fill in all the constant parts required to send data to the browser
        client.

        Only called when running in CGI mode.

        Pass:
            formContent - The part that is unique to this page.  We put
                          wrappers around it here.
            subBanner   - Under banner header.
            haveVars    - Container of form variable names included in
                          formContent.  See saveContext().
            buttons     - Buttons for banner header, default=Next/Cancel

        Return:
            No return.  Exits to the browser.
        """
        # Sanity check
        if not self.__cgi:
            self.error("SimpleLinkVars.sendPage() invoked in non-CGI context")

        # Control width of select boxes
        # Fixed header values
        if buttons == 'default':
            buttons = ('Next', 'Cancel')
        title   = "CDR Global Change Simple Links"
        script  = "GlobalChangeSimpleLink.py"
        if not subBanner:
            subBanner = title

        # Create an overall header using the common header code
        html = cdrcgi.header (title, title, subBanner, script, buttons)

        # Add progress/status report
        html += self.showProgress()

        # Add form contents
        html += formContent

        # Add session and state variables
        html += self.saveContext(alreadyDone=haveVars)

        # Form termination
        html += "\n</form>\n</body>\n</html>\n"

        cdrcgi.sendPage (html)

    def chkSrcDocType(self):
        """
        Determine the source document type.
        If there's a type name but no ID, resolve it.
        If there's no name, ask the user for it.
        """
        # Do we already have everything we need?
        if self.getVar("srcDocTypeName"):
            return

        # Query to find doctypes with defined links
        qry = """
SELECT DISTINCT t.name, t.name
  FROM doc_type t
  JOIN link_xml x
    ON x.doc_type = t.id
 ORDER BY t.name
"""

        # Ask user for a document type

        # Generate a picklist for these
        pattern = "<option value='%s'>%s&nbsp;</option>"
        pickList = cdrcgi.generateHtmlPicklist(getConn(), "srcDocTypeName",
                          qry, pattern, selAttrs="size='10'")


        # Present it to the user
        html = """
<p>Select the name of the document type containing links to be globally
changed and click "Next".</p>
""" + pickList
        self.sendPage(html, "Select document type",
                      haveVars=("srcDocTypeName",))


    def chkSrcElement(self):
        """
        Determine the source element containing the link cdr:ref.
        Logic is similar to chkSrcDocType.
        """
        if self.getVar("srcFieldName"):
            return

        qry = """
SELECT DISTINCT x.element, x.element
  FROM link_xml x
  JOIN doc_type t
    ON x.doc_type = t.id
 WHERE t.name = '%s'
 ORDER BY x.element
 """ % self.getVar("srcDocTypeName")

        pattern = "<option value='%s'>%s&nbsp;</option>"
        pickList = cdrcgi.generateHtmlPicklist(getConn(), "srcFieldName",
                          qry, pattern, selAttrs="size='10'")
        html = """
<p>Select the name of the XML element containing links to be globally
changed and click "Next".</p>
""" + pickList
        self.sendPage(html, "Select document type", haveVars=("srcFieldName",))


    def chkLinkRef(self, refType):
        """
        Identifiy a specific link-to document ID.  The logic is the same
        for both the old and new references.  Only the user prompt and
        the form variable names change.

        Pass:
            refType - "old" or "new".
        """
        # Differences between the two types
        if refType == "old":
            refIdVar = "oldLinkRefIdStr"
            refName  = "oldLinkRefName"
            prompt   = "old (existing)"
            noteMsg  = """
<p>If you enter a trailing fragment id, e.g., "#F1", only links
with that ID will be changed.  Otherwise no links with trailing
fragments will be changed, e.g. if all actual links include "#F1"
but you enter a plain CDR ID without "#F1", no links will be
found or changed.</p>
"""
        else:
            refIdVar = "newLinkRefIdStr"
            refName  = "newLinkRefName"
            prompt   = "new (replacement)"
            noteMsg  = """
<p>If you enter a trailing fragment ID, all new links will have that
fragment ID.  Otherwise no new links will have trailing fragment IDs.</p>
"""

        # If user entered both an ID and a string, warn him
        # We must know that we're processing real input, not saved input
        #   from a previous screen, e.g., checking old ref when new is entered
        if self.__fields.getvalue("linkPhase") == refType:
            # cdrcgi.bail(u"refIdVar=%s *refIdVar=%s refName=%s *refName=%s" %
            #     (refIdVar, self.getVar(refIdVar), refName,
            #      self.getVar(refName).decode("utf-8")))
            if self.getVar(refIdVar) and self.getVar(refName):
                cdrcgi.bail("Please enter either an id OR a string, not both.")

        # If we have neither an ID nor a title, prompt for them
        if not self.getVar(refIdVar) and not self.getVar(refName):
            html = """
<p>Enter the CDR ID or leading characters of the title string for the
%s linked document and click "Next".</p>
<table>
 <tr><td align='right'>Linked document CDR ID: </td>
     <td><input type='text' name='%s' size='20' /></tr>
 <tr><td colspan='2' align='center'>OR</td</tr>
 <tr><td align='right'>Leading chars from the title: </td>
     <td><input type='text' name='%s' size='40' /></tr>
</table>
<input type='hidden' name='linkPhase' value='%s' />
%s
""" % (prompt, refIdVar, refName, refType, noteMsg)
            self.sendPage(html, "Enter link value",
                          haveVars=(refIdVar, refName))

        # If no doc ID supplied, display some matching titles in a picklist
        if self.getVar(refIdVar) is None:
            qry = """
SELECT TOP 100 d.id, SUBSTRING(d.title, 1, 120)
  FROM document d
  JOIN doc_type t
    ON d.doc_type = t.id
 WHERE t.id = %d
   AND d.title LIKE '%s%%'
 ORDER BY title
""" % (self.getLinkTargDocType(), self.getVar(refName))

            pattern = "<option value='%s'>%s&nbsp;</option>"
            pickList = cdrcgi.generateHtmlPicklist(getConn(), refIdVar, qry,
                              pattern, selAttrs="size='10'")

            # If we got here, we have a name/title, disambiguate it
            html = """
<p>Select the document that matches the displayed %s linked document
title.</p>
""" % prompt
            html += pickList
            self.sendPage(html, "Select %s linked document" % prompt,
                          haveVars=(refIdVar,))

        # If we got here, we have a CDR ID, but no title
        refIdStr = self.getVar(refIdVar)
        try:
            refIdNum = cdr.exNormalize(refIdStr)[1]
        except:
            self.error("Unable to convert '%s' into a CDR Document ID" %
                         refIdStr)

        qry = """
SELECT title, doc_type
  FROM document
 WHERE id = %d
""" % refIdNum
        try:
            conn   = cdrdb.connect()
            cursor = conn.cursor()
            cursor.execute(qry)
            row = cursor.fetchone()
            cursor.close()
        except cdrdb.Error, info:
            self.error("Database error fetching link title & doc_type: '%s'" %
                        str(info))

        if not row:
            self.error("I cannot find any document matching CDR ID=%s" %
                        self.getVar(refIdVar))

        if not row[1]:
            self.error("Internal error, no title found for CDR ID=%d" %
                        self.getVar(refIdVar))

        if row[1] != self.getLinkTargDocType():
            self.error("Document %s is of the wrong type for this link" %
                         self.getVar(refIdVar))

        # Save the title
        self.vars[refName] = row[0]


    def chkRefTypes(self):
        """
        Determine whether we're going to modify cdr:ref values, cdr:href
        values, or both.
        """
        # Do we already know?
        if self.getVar("doRefs") or self.getVar("doHrefs"):
            return

        html = u"""
<p>Check 'cdr:ref' to modify cdr:ref links and/or<br />
Check 'cdr:href' to modify cdr:href links
Then click "Next".</p>
<p> Reference types to modify:
    <input type='checkbox' name='doRefs' value='Yes'>cdr:refs</input>
    <input type='checkbox' name='doHrefs' value='Yes'>cdr:hrefs</input>
</p>
"""
        self.sendPage(html, "Select 'refs' and/or 'hrefs' to modify",
                      haveVars=("doRefs", "doHrefs"))


    def chkEmailList(self):
        """
        Determine email addresses to notify when the batch job completes.
        """
        # Do we already have them?
        if self.getVar("emailList"):
            return

        html = u"""
<p>Enter one or more email address, separated by spaces, to be notified
when the global change batch job completes, then click "Next".</p>
</p>
<p>Email addresses: <input type='text' name='emailList' size='80' /></p>
"""
        self.sendPage(html, "Enter email notification addresses",
                      haveVars=("emailList",))


    def chkRunMode(self):
        """
        Determine whether we're going to run in test mode or live mode.
        """
        # Do we already have a run mode?
        if self.getVar("runMode"):
            return

        html = u"""
<p>Select 'Live' to modify data in the database, or 'Test' to make
no changes to live data - just produce a Global Change test report.
Then click 'Next'.</p>
<p> Run mode:
    <input type='radio' name='runMode' value='Live'>Live</input>
    <input type='radio' name='runMode' value='Test'>Test</input>
</p>
"""
        self.sendPage(html, "Select 'live' or 'test' mode",
                      haveVars=("runMode",))


    def getLinkTargDocType(self):
        """
        Check the link tables to find the document type that is
        expected as the target of the source link.

        Return
            Document type ID from doc_type table.
        """
        # Query the database
        qry = """
SELECT targ.target_doc_type
  FROM link_target targ
  JOIN link_xml lxml
    ON lxml.link_id = targ.source_link_type
  JOIN doc_type doct
    ON lxml.doc_type = doct.id
 WHERE doct.name = '%s'
   AND lxml.element = '%s'
""" % (self.getVar("srcDocTypeName"), self.getVar("srcFieldName"))

        try:
            conn   = cdrdb.connect()
            cursor = conn.cursor()
            cursor.execute(qry)
            row = cursor.fetchone()
            cursor.close()
        except cdrdb.Error, info:
            self.error("Database error fetching link doc_type: '%s'" %
                        str(info))

        # It must exist
        if not row[0]:
            self.error("Could not find a target document type for this link"
                        + " - can't happen!")

        # Return document type id that is the valid target for this link
        return row[0]

    def makeSelectionQuery(self, findWhat, matchWhat):
        """
        Create an SQL query string to find all documents in the database
        that will be processed by the global change.

        Used to produce a query for display of what will be done, and
        for selecting IDs for the actual global change.

        Pass:
            findWhat  - "id" = Find all doc ids matching old link.
                        "idTitle" = Find ids and titles.
                        "count" = Find count only.
            matchWhat - "fullIdStr" - Match full id, e.g., "CDR0000012345#F1"
                        "intIdOnly" - Match just the integer part, e.g., 12345

        Return:
            SQL query string.
        """
        # SQL for what to fetch
        orderBy = "ORDER BY d.id"
        selector = ""
        if findWhat == "id":
            selector = "DISTINCT d.id"
        elif findWhat == "idTitle":
            selector = "DISTINCT d.id, d.title"
        elif findWhat == "count":
            selector = "COUNT(DISTINCT d.id)"
            orderBy  = ""
        else:
            self.error("Error, bad findWhat = '%s'" % findWhat)

        # Search for cdr:ref and/or cdr:href
        whereClause = "WHERE (q.path like '/%s/%%%s/@cdr:" % (
                    self.getVar("srcDocTypeName"), self.getVar("srcFieldName"))
        if self.getVar('doRefs') == "Yes":
            whereClause += "ref'"
            if self.getVar('doHrefs') == "Yes":
                whereClause += "\n    OR q.path like '/%s/%%%s/@cdr:href'" % (
                    self.getVar("srcDocTypeName"), self.getVar("srcFieldName"))
        else:
            whereClause += "href'"
        whereClause += ')'

        # Match the specific ID string, or any matching CDR doc ID
        if matchWhat == "fullIdStr":
            matcher = "q.value = '%s'" % self.getVar('oldLinkRefIdStr')
        elif matchWhat == "intIdOnly":
            matcher = "q.int_val = %d" % cdr.exNormalize(
                                       self.getVar('oldLinkRefIdStr'))[1]

        # Construct query path using what we have
        qry = """
SELECT %s
  FROM document d
  JOIN query_term q
    ON q.doc_id = d.id
 %s
   AND %s
 %s
""" % (selector, whereClause, matcher, orderBy)
        # DEBUG
        cdr.logwrite(qry)

        return qry


    def showWhatWillChange(self):
        """
        Produce an HTML table showing what will change.

        Return:
            String of HTML.
        """
        # Has user already seen and approved the changes?
        if self.getVar("approved"):
            return

        qry = self.makeSelectionQuery(findWhat="idTitle", matchWhat="fullIdStr")
        try:
            conn   = cdrdb.connect()
            cursor = conn.cursor()
            cursor.execute(qry)
            rows = cursor.fetchall()
        except cdrdb.Error, info:
            self.error("Database error fetching titles to change: %s"
                         % str(info))

        docCount = len(rows)

        # If we're only getting docs with fragment ids, get count of all
        #   docs regardless of fragment.  It may be useful to the user.
        (idFull, idNum, idFrag) = cdr.exNormalize(
                                      self.getVar("oldLinkRefIdStr"))
        if idFrag:
            qry = self.makeSelectionQuery(findWhat="count",
                                          matchWhat="intIdOnly")
            try:
                cursor.execute(qry)
                row = cursor.fetchone()
            except cdrdb.Error, info:
                self.error("Database error fetching plain ID count: %s"
                            % str(info))
            plainRefCount = row[0]
        cursor.close()

        if docCount:
            html = "<h3>The following %d documents will be changed:</h3>\n" % \
                    docCount

            # Include extra info if user has specified a fragment id
            if idFrag:
                if docCount != plainRefCount:
                    html += "<p>(If no old link fragment ID were specified, " \
                            "the count would be %d.)</p>" % plainRefCount
                else:
                    html += "<p>(If no old link fragment ID were specified, " \
                            "the count would still be the same.)</p>"

            html += cdrcgi.tabularize(rows, "align='center' border='1'") + \
                   "<p>Click 'Submit' to start the global change, or " + \
                   "'Cancel' to cancel it.</p>\n"

            # If submitted, this variable will move us on
            html+="<input type='hidden' name='approved' value='approved' />\n"

            self.sendPage(html, "Ready to submit global change",
                          buttons=("Submit", "Cancel"))
        else:
            self.error("No documents found matching the old link criteria")


class SimpleLinkTransform:
    """
    Callback functions for ModifyDocs.
    """
    def __init__(self, linkVars):
        """
        Construct the transform.

        Pass:
            linkVars - All context from user selections.
        """
        # Make context available to get IDs.
        self.linkVars = linkVars

        # Use this variable to to get access to ModifyDocs logging
        self.job = None

        # Store error messages here
        self.errMsgs = []

        # Find error messages using this pattern
        self.errPat = re.compile(r"<message>([^<]*)</message>")

        # Create filter templates for the object(s) to be changed.
        refTemplate  = ""
        hrefTemplate = ""
        if self.linkVars.getVar("doRefs") == "Yes":
            refTemplate = self.makeRefTemplate("ref")
        if self.linkVars.getVar("doHrefs") == "Yes":
            refTemplate = self.makeRefTemplate("href")

        # Create the transform using the data in the context
        self.transform = """\
<?xml version='1.0' encoding='UTF-8'?>

<xsl:transform  version = '1.0'
                xmlns:xsl = 'http://www.w3.org/1999/XSL/Transform'
                xmlns:cdr = 'cips.nci.nih.gov/cdr'>
 <xsl:output    method = 'xml'/>

 <!-- ==================================================================
 Copy almost everything straight through.
 ======================================================================= -->
 <xsl:template             match = '@*|node()|comment()|
                                    processing-instruction()'>
  <xsl:copy>
   <xsl:apply-templates   select = '@*|node()|comment()|text()|
                                    processing-instruction()'/>
  </xsl:copy>
 </xsl:template>

%s
%s

</xsl:transform>
""" % (refTemplate, hrefTemplate)
        # DEBUG
        # cdr.logwrite("\n%s\n" % self.transform)


    def makeRefTemplate(self, refType):
        """
        Create an xsl:template for the element we need to change.

        Pass:
            refType - "ref" or "href" for handling cdr:ref or cdr:href.
        """
        refField = self.linkVars.getVar("srcFieldName")
        oldValue = self.linkVars.getVar("oldLinkRefIdStr")
        newValue = self.linkVars.getVar("newLinkRefIdStr")

        template = """
 <!-- Node of interest -->
 <xsl:template             match = '//%s/@cdr:%s'>
   <xsl:attribute           name = 'cdr:%s'>
     <xsl:choose>
       <!-- If we have the old link, convert it to the new link -->
       <xsl:when            test = '. = "%s"'>
         <xsl:value-of    select = '"%s"'/>
       </xsl:when>
       <!-- Else this is some other cdr:(h)ref, leave it alone -->
       <xsl:otherwise>
         <xsl:value-of    select = '.'/>
       </xsl:otherwise>
     </xsl:choose>
   </xsl:attribute>
 </xsl:template>
""" % (refField, refType, refType, oldValue, newValue)
        template = template.encode("utf-8")

        return template


    def getDocIds(self):
        """
        ModifyDocs callback to (re)retrieve the document IDs to change.
        """
        qry = self.linkVars.makeSelectionQuery(findWhat="id",
                                               matchWhat="fullIdStr")
        try:
            conn   = cdrdb.connect()
            cursor = conn.cursor()
            cursor.execute(qry)
            rows = cursor.fetchall()
            cursor.close()
        except cdrdb.Error, info:
            cdrcgi.bail("Database error fetching docIds to change: %s"
                         % str(info))

        # DEBUG
        # cdr.logwrite("getDocIds qry=\n%s\ncount = %d" % (qry, len(rows)))

        # Return IDs
        return [row[0] for row in rows]


    def run(self, docObj):
        """
        ModifyDocs callback to transform one document.
        """
        # Get the xml for the document
        # docXml = docObj.xml.decode("utf-8")
        docXml = docObj.xml

        # Filter it
        response = cdr.filterDoc('guest', self.transform, doc=docXml,
                                  inline=True)

        # Error check
        if type(response) in (type(""), type(u"")):
            raise Exception("Failure in filtering doc: %s: %s" %
                             (docObj.id, response))

        # Warning check
        if len(response) > 1 and response[1]:
            errList = self.errPat.findall(response[1])
            for msg in errList:
                fullErrMsg = "  %s: %s" % (docObj.id, msg)

                # Write message to ModifyDocs log file
                self.job.log(fullErrMsg)

                # And save it here for display in CGI program
                self.errMsgs.append(fullErrMsg)

        # return filtered doc
        return response[0]


#----------------------------------------------------------------------
# Main
#----------------------------------------------------------------------
if __name__ == "__main__":

    # Find batch job that started this
    if len(sys.argv) != 2:
        fatal("Started without job parameter")
    try:
        batchJobId = int(sys.argv[1])
    except ValueError:
        fatal("Passed bad job ID: %s" % sys.argv[1])
    try:
        jobObj = cdrbatch.CdrBatch(jobId=batchJobId)
    except cdrbatch.BatchException, info:
        fatal("Unable to load batch job: %s" % info)

    # Construct global change specific the objects we need
    linkVars   = SimpleLinkVars(jobObj)
    filtTrans  = SimpleLinkTransform(linkVars)

    # Construct the ModifyDocs job
    userId, pw = cdr.idSessionUser(linkVars.session, linkVars.session)
    testMode   = True
    if linkVars.getVar("runMode") == "Live":
        testMode = False
    modifyJob  = ModifyDocs.Job(userId, pw, filtTrans, filtTrans,
                    "GlobalChangeSimpleLink of %s to %s in %s/%s" %
                        (linkVars.getVar("oldLinkRefIdStr"),
                         linkVars.getVar("newLinkRefIdStr"),
                         linkVars.getVar("srcDocTypeName"),
                         linkVars.getVar("srcFieldName")),
                    testMode=testMode, validate=True)

    # DEBUG
    ModifyDocs.setMaxErrors(5)

    # Debug
    # modifyJob.setMaxDocs(1)

    # Run the job
    try:
        modifyJob.run()
    except Exception, info:
        # Report to global change log file and fail job
        msg = "%s failed: %s" % (JOB_NAME, str(info))
        cdr.logwrite(msg, LF)
        jobObj.fail(msg)

    # Successful completion
    try:
        jobObj.setStatus(cdrbatch.ST_COMPLETED)
    except cdrbatch.BatchException, info:
        msg = "%s: Unable to set completion status: %s" % (JOB_NAME, str(info))

    # Results
    if modifyJob.getCountDocsProcessed():

        resultHtml = """
<table border="2">
%s
</table>
""" % modifyJob.getSummary(markup=True)
    else:
        resultHtml = ""

    # Send email
    html = """
<html><head><title>Global change report</title></head>
<body>
<h2>Final report on global change</h2>
<p>The global change to replace %s with % s in %s / %s is complete.
If it was run in test mode, please check the output in the Global Change
Results page.</p>
<center>
<h3>Summary</h3>
%s
</center>
</body></html>
""" % (linkVars.getVar("oldLinkRefIdStr"), linkVars.getVar("newLinkRefIdStr"),
       linkVars.getVar("srcDocTypeName"), linkVars.getVar("srcFieldName"),
       resultHtml)

    # Convert email string to a list
    emailList = linkVars.getVar("emailList").split()

    resp = cdr.sendMail ("cdr@%s.nci.nih.gov" % socket.gethostname(),
                         emailList,
                         subject="Final report on global change",
                         body=html,
                         html=1)
    cdr.logwrite("%s: Sent mail, response=%s" % (JOB_NAME, resp))

    # We're done
