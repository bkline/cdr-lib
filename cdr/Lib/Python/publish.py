#
# Script for command line and CGI publishing.
#
#$Id: publish.py,v 1.3 2001-10-05 18:50:49 Pzhang Exp $
#$Log: not supported by cvs2svn $
#Revision 1.2  2001/10/05 15:08:01  Pzhang
#Added __invokePracessScript for Bob's Python Script.
#Imported traceback to handle exceptions.
#
#Revision 1.1  2001/10/01 15:07:21  Pzhang
#Initial revision
#
#

from win32com.client import Dispatch
import os, sys, shutil, re, cdr, xml.dom.minidom, copy
import pythoncom, string, time

DEBUG = 0

# This flag controls the print statement through the
#   package. It is critical to set NCGI to 0 in the 
#   CGI script.
NCGI = 1

#-------------------------------------------------------------------
# class: Publish 
#    This class encapsulate the publishing data and methods.
#    There is one publing method, publish(), for command line;
#       Other methods are helpers for CGI script.
#             
# Inputs to the contructor:
#    strCtrlDocId:  a publishing system control document ID in STRING!
#    subsetName:    a publishing system subset name.
#    credential:    a Session ID (name in the session table). 
#    docIds:        (optional) a list of selected CDR document ID
#                       and/or document version.
#    params:        (optional) a list of subset parameters.
#    jobId:         the process job id for a subset publishing.
# Issues:           Passing parameters or using class variables?
#                   Minimal error checking has been done.
#-------------------------------------------------------------------
class Publish:

    SUCCEED = "Success" 
    FAIL = "Failure" 
    WAIT = "Waiting user approval" 
    RUN = "In process" 
    INIT = "Initial"
    READY = "Ready"
    START = "Started"

    FILE = 4
    DOCTYPE = 5
    DOC = 6

    # Many options are not implemented.
    IGNORE = 7
    
    
    # class private variables
    __cdrConn = None
    __procId = 0    # This duplicates self.jobId. 
                    # Keep it for code history or clarity.
    __specs = None
    __docIds = {}   # Dictionary to store non-duplicate docIds
    __userId = 0
    __userName = ""

    # Do nothing but set local variables.
    def __init__(self, strCtrlDocId, subsetName, credential,
                docIds, params, jobId = 0):
        self.strCtrlDocId = strCtrlDocId      
        self.subsetName = subsetName
        self.credential = credential    
        self.docIds = docIds
        self.params = params            
        self.jobId = jobId            
    
    # This is a CGI helper function.
    def getPubSys(self):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()

        # Initialized the list of tuples: (title, id, sysName, desc).
        pickList = []
        tuple = ["", "", "", ""]

        sql = "SELECT title, id, xml FROM document WHERE doc_type = 58"
        rs = self.__execSQL(sql)
        
        while not rs.EOF:
            tuple[0] = rs.Fields("title").Value
            tuple[1] = rs.Fields("id").Value
            docElem = rs.Fields("xml").Value.encode('latin-1')

            docElem = xml.dom.minidom.parseString(docElem).documentElement
            for node in docElem.childNodes:
                if node.nodeType == xml.dom.minidom.Node.ELEMENT_NODE:
                    # SystemName comes first by schema. So tuple[2] will
                    #   be initialized once for all.
                    if node.nodeName == 'SystemName':
                        tuple[2] = ''
                        for n in node.childNodes:
                            if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                tuple[2] = tuple[2] + n.nodeValue
                    if node.nodeName == 'SystemDescription':
                        tuple[3] = ''
                        for n in node.childNodes:
                            if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                tuple[3] = tuple[3] + n.nodeValue

            deep = copy.deepcopy(tuple)
            pickList.append(deep)
    
            rs.MoveNext()

        rs.Close()
        rs = None
        self.__cdrConn = None
    
        return pickList

    # This is a CGI helper function.
    def getPubSubset(self):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()

        # Initialized the list of tuples: (name, desc, sysName).
        pickList = []
        tuple = ["", "", ""]

        sql = "SELECT xml FROM document WHERE id = %s" % self.strCtrlDocId
        rs = self.__execSQL(sql)
        
        while not rs.EOF:
            docElem = rs.Fields("xml").Value.encode('latin-1')

            docElem = xml.dom.minidom.parseString(docElem).documentElement
            for node in docElem.childNodes:
                if node.nodeType == xml.dom.minidom.Node.ELEMENT_NODE:
                    # SystemName comes first by schema. So tuple[2] will
                    #   be initialized once for all.
                    # We may not need this if the next page
                    #   does not show the system name. 
                    if node.nodeName == 'SystemName':
                        tuple[2] = ''
                        for n in node.childNodes:
                            if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                tuple[2] = tuple[2] + n.nodeValue

                    if node.nodeName == 'SystemSubset':
                        tuple[0] = ''
                        tuple[1] = ''
                        for n in node.childNodes:
                            if n.nodeName == 'SubsetName':
                                for m in n.childNodes:                                    
                                    if m.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                        tuple[0] = tuple[0] + m.nodeValue
                            if n.nodeName == 'SubsetDescription':
                                for m in n.childNodes:                                    
                                    if m.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                        tuple[1] = tuple[1] + m.nodeValue

                        deep = copy.deepcopy(tuple)
                        pickList.append(deep)
    
            rs.MoveNext()

        rs.Close()
        rs = None
        self.__cdrConn = None
    
        return pickList

    # This is a CGI helper function.
    # Wanted to return the SQL statement as well, but not done yet.
    # Only returns the parameters so far.
    def getParamSQL(self):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()

        # Initialized the list of tuples: (name, value).
        pickList = []
        tuple = ["", ""]

        sql = "SELECT xml FROM document WHERE id = %s" % self.strCtrlDocId
        rs = self.__execSQL(sql)
        
        while not rs.EOF:
            docElem = rs.Fields("xml").Value.encode('latin-1')
            rs.MoveNext()
        rs.Close()
        rs = None
        self.__cdrConn = None

        return self.__getParameters(self.__getSubSet(docElem))

    # This is a CGI helper function.
    def isPublishable(self, docId):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()
        
        # Get doc_id and doc_version.
        id = self.__getDocId(docId)
        version = self.__getVersion(docId)

        # Query into doc_version table
        sql = "SELECT id FROM doc_version WHERE id = %s AND num = %s " \
                "AND publishable = 'Y' " % (id, version)
        rs = self.__execSQL(sql)
        
        ret = 0
        while not rs.EOF:
            ret = 1
            rs.MoveNext()
        rs.Close()
        rs = None
        self.__cdrConn = None

        return ret

    # This is a CGI helper function. It is the most important function
    #   for publishing CGI, which creates the publishing process.
    # This function returns an error message or a jobId. __procId is
    #   a useless LEGACY variable.
    def getJobId(self):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()
    
        # Get user ID and Name from SessionName in CDR.
        self.__getUser()

        # At most one active publishing process can exist.
        self.__procId = self.__existProcess()
        if self.__procId:                
            self.__cdrConn = None
            return "*Error: there is an active process with ID: %d." % self.__procId    
        else:
            # A row in pub_proc table is created. Rows are also 
            # created in pub_proc_parm and pub_proc_doc tables.
            # A job id is output for user to check status later.
            # The status is initially "Initial", and then "Ready".
            self.__procId = self.__createProcess()
            self.__cdrConn = None
            return self.__procId

    # This is a CGI helper function.
    def getStatus(self, jobId):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()        
        
        sql = """SELECT id, output_dir, CAST(started AS varchar(30)) as started, 
            CAST(completed AS varchar(30)) as completed, status, messages 
            FROM pub_proc 
            WHERE id = %s""" % jobId
        rs = self.__execSQL(sql)

        row = ["id", "output_dir", "started", "completed", 
            "status", "messages"]
        while not rs.EOF:
            row[0] = rs.Fields("id").Value
            row[1] = rs.Fields("output_dir").Value    
            row[2] = rs.Fields("started").Value    
            row[3] = rs.Fields("completed").Value
            row[4] = rs.Fields("status").Value
            row[5] = rs.Fields("messages").Value            
            rs.MoveNext()
        rs.Close()
        rs = None
    
        return row

    # This is the major public entry point to publishing.
    def publish(self):

            # Move the code into getJobId. getJobId sets __procId.
            if not self.jobId:
                newJob = self.getJobId()
                if type("") == type(newJob):
                    sys.exit(1)
            else:
                self.__procId = self.jobId
                
                # New design. Used jobId to reset all other parameters:
                # strCtrlDocId, subsetName, credential, docIds, and params    
                self.__resetParamsByJobId()
            
            # Connect to CDR. Abort when failed. Cannot log status in this case.
            self.__getConn()

            # Get user ID and Name from SessionName in CDR.
            self.__getUser()

            # Get control document from the given sysName.
            docElem = self.__getCtrlDoc()
            if docElem is None:
                msg = "*Error: publishing control document not found."    
                self.__updateStatus(Publish.FAIL, msg)
                sys.exit(1)            

            # Get a node of the given SubSet.
            # Only one subset per publishing?
            subset = self.__getSubSet(docElem)

            # Handle process script. 
            # Exit if there is a process script.
            self.__invokeProcessScript(subset)

            # Get the subset specifications node.                        
            self.__specs = self.__getSpecs(subset)        
            
            # Get the action to check publishing permission.
            action = self.__getAction(subset)
            
            # Don't know the rule to check permission yet?
            permitted = self.__isPermitted(action)
            if not permitted:                
                msg = "*Error: " + self.__userName + " is not permitted to publish."
                self.__updateStatus(Publish.FAIL, msg)
                sys.exit(1)

            # Get the name-value pairs of options.
            options = self.__getOptions(subset)

            # Get the name-value pairs of parameters.
            localParams = self.__getParameters(subset)

            # Get the destination directory.
            dest_base = self.__getDestination(options)
            dest_base += "." + self.__userName + "." + "%d" % time.time() 
            dest = dest_base + "." + "InProcess"

            # Get the destination type.
            destType = self.__getDestinationType(options)
            if destType == Publish.FILE:
                file = self.__getDestinationFile(options)

            # For each spec, extract the associated docIds and filters.
            # Publish them based on various options.
            for spec in self.__specs.childNodes: 

                # nodeName could be "#text" or others. 
                if spec.nodeName != "SubsetSpecification":
                    continue

                # Replace default parameters.
                # A list of tuples: ((n1, v1), (n2, v2),)
                # localParams = self.__getParams(spec)

                # Append docIds from XQL or SQL.
                # A list of docIds: (1234, 5678,)
                # Need help from Mike to clarify???
                localDocIds = self.__getDocIds(spec, localParams)

                # Get the filters node in spec.
                filters = self.__getFilters(spec)

                # Collect document types.
                # A list of document type IDs or Names 
                # A document type name is also a unique NCNAME.
                # Useful only when destType == DOCTYPE.
                docTypes = self.__getDocTypes(localDocIds)

                if destType == Publish.FILE:
                    self.__publishAll(localDocIds, filters, 
                        localParams, dest, file, options) 
                elif destType == Publish.DOCTYPE: 
                    # Remove all files in the dest dir.
                    # No longer needed since it does not exist.
                    # os.path.isdir(dest) and shutil.rmtree(dest)

                    self.__publishType(localDocids, filters,
                        localParams, dest, docTypes, options) 
                elif destType == Publish.DOC:  
                    # Remove all files in the dest dir.
                    # No longer needed since it does not exist.
                    # os.path.isdir(dest) and shutil.rmtree(dest)

                    self.__publishDoc(localDocIds, filters, 
                        localParams, dest, options)

            # We need to check publishing status before finishing.
            status = self.__getStatus()
            if status == Publish.SUCCEED: 
                if destType == Publish.FILE:
                    shutil.copy(dest + "/new/" + file, dest)
                else: # Copy all files from subdir "new" to destination.
                    for file in os.listdir(dest + "/new"):
                        shutil.copy(dest + "/new/" + file, dest)
                # Rename the destination dir to .SUCCEED
                os.rename(dest, dest_base + ".SUCCEED")                
        
                # Update Publishing_Events and 
                #    Published_Documents tables
                #     from Publishing_Process and
                #    Publishing_Process_Documents tables,
                #    respectively.
                self.__updateStatuses()
            elif status == Publish.FAIL: 
                # Rename the destination dir to .FAIL
                os.rename(dest, dest_base + ".FAIL")
            elif status == Publish.WAIT: 
                # Rename the destination dir to .WAIT
                os.rename(dest, dest_base + ".WAIT")            

            # Disconnected from CDR.
            if not self.__cdrConn is None:
                self.__cdrConn.Close()
                self.__cdrConn = None

    # This is the major helper function to reset input parameters:
    #    strCtrlDocId, subsetName, credential, docIds, and params    
    def __resetParamsByJobId(self):

        # Connect to CDR. Abort when failed. Cannot log status in this case.
        self.__getConn()
        
        # reset strCtrlDocId, subsetName
        sql = """SELECT pub_system, pub_subset, usr 
                FROM pub_proc
                WHERE id = %d 
                    AND status = '%s'""" % (self.__procId, Publish.START)
        if NCGI: print sql
        rs = self.__execSQL(sql)        
        rows = 0
        while not rs.EOF:
            rows += 1
            self.strCtrlDocId = str(rs.Fields("pub_system").Value)
            self.subsetName = rs.Fields("pub_subset").Value
            self.__userid = rs.Fields("usr").Value
            rs.MoveNext()
        rs.Close()
        if rows == 0 or rows > 1:
            if NCGI: print "*Error: resetParamsByJobId failed in access to pub_proc:"
            if NCGI: print "      Not a unique record returned."
            sys.exit(1)
        
        # reset docIds. It could be an empty list.
        self.docIds = []
        sql = """SELECT doc_id, doc_version 
                FROM pub_proc_doc 
                WHERE pub_proc = %d """ % self.__procId
        rs = self.__execSQL(sql)        
        while not rs.EOF:
            docId = rs.Fields("doc_id").Value            
            version = rs.Fields("doc_version").Value
            self.docIds.append("%d/%d" % (docId, version))

            # Avoid duplicate docId in pub_proc_doc table.
            self.__docIds[str(docId)] = docId  
        
            rs.MoveNext()
        rs.Close()
    
        # reset params. It could be an empty list.
        self.params = []
        sql = """SELECT parm_name, parm_value 
                FROM pub_proc_parm 
                WHERE pub_proc = %d """ % self.__procId
        rs = self.__execSQL(sql)        
        while not rs.EOF:
            name = rs.Fields("parm_name").Value
            value = rs.Fields("parm_value").Value
            self.params.append("%s %s" % (name, value))
            rs.MoveNext()
        rs.Close()

        # reset credential.            
        sql = """SELECT name, password 
                FROM usr
                WHERE id = %s """ % self.__userid
        rs = self.__execSQL(sql)
        rows = 0
        while not rs.EOF:
            rows += 1
            self.__username = rs.Fields("name").Value
            self.__password = rs.Fields("password").Value
            rs.MoveNext()
        rs.Close()
        if rows == 0 or rows > 1:
            if NCGI: print "*Error: resetParamsByJobId failed in access to usr:"
            if NCGI: print "      Not a unique record returned."
            sys.exit(1)
        self.credential = cdr.login(self.__username, self.__password)    

        # change status??
        # Ready to publish.                    
        sql = "UPDATE pub_proc SET status = '" + Publish.RUN + "' "
        sql += "WHERE id = %d" % self.__procId
        self.__execSQL(sql)

        rs = None
        self.__cdrConn = None

    #----------------------------------------------------------------
    # Set up a connection to CDR. Abort when failed.
    #----------------------------------------------------------------
    def __getConn(self):
        try:
            connStr = "DSN=cdr;UID=CdrPublishing;PWD=***REMOVED***"        
            self.__cdrConn = Dispatch('ADODB.Connection')            
            self.__cdrConn.ConnectionString = connStr
            self.__cdrConn.Open()
        except pythoncom.com_error, (hr, msg, exc, arg):
            self.__cdrConn = None    
            reason = "*Error with connection to CDR."
            if exc is None:
                reason += "Code %d: %s" % (hr, msg)
            else:
                wcode, source, text, helpFile, helpId, scode = exc
                reason += " Src: " + source + ". Msg: " + text
            if NCGI: print reason
            sys.exit(1)

    #----------------------------------------------------------------
    # Get user ID and Name using credential from CDR.
    #----------------------------------------------------------------
    def __getUser(self):
        if NCGI: print "in __getUser\n"   

        sql = "SELECT usr.id as uid, usr.name as uname "
        sql += "FROM session, usr "
        sql += "WHERE session.name = '" + self.credential + "' AND "
        sql += "session.usr = usr.id"
        rs = self.__execSQL(sql)

        while not rs.EOF:
            self.__userId = rs.Fields("uid").Value
            self.__userName = rs.Fields("uname").Value
            rs.MoveNext()
        rs.Close()
        rs = None
        
        if self.__userId == 0 or self.__userName == "":
            if NCGI: print "*Error: __getUser failed to get user id or user name."
            sys.exit(1)    

    #----------------------------------------------------------------
    # Execute the SQL statement using ADODB.
    #----------------------------------------------------------------    
    def __execSQL(self, sql):
        if NCGI: print "in __execSQL\n"  
          
        try:
            (rs, err) = self.__cdrConn.Execute(sql)
        except pythoncom.com_error, (hr, msg, exc, arg):            
            reason = "*Error with executing %s." % sql
            if exc is None:
                reason += " Code %d: %s" % (hr, msg)
            else:
                wcode, source, text, helpFile, helpId, scode = exc
                reason += " Src: " + source + ". Msg: " + text
            #if self.__procId != 0:
                #self.__updateStatus(Publish.FAIL, reason)
            if NCGI: print reason
            rs = None
            self.__cdrConn.Close()
            self.__cdrConn = None
            sys.exit(1)
        return rs;
                
    #----------------------------------------------------------------
    # Return a document for publishingSystem by its name. 
    # The document is either None or starting with <PublishingSystem>.
    #----------------------------------------------------------------
    def __getCtrlDoc(self):
    
        # Don't want to used title to select. New design!
        sql = "SELECT xml FROM document WHERE id = %s" % self.strCtrlDocId
    
        rs = self.__execSQL(sql)

        xml = None
        while not rs.EOF:
            xml = rs.Fields("xml").Value
            rs.MoveNext()
        rs.Close()
        rs = None
        if NCGI and DEBUG: print xml
        if xml == None:
            return None
        return xml.encode('latin-1')
        
        #doc = cdr.getDoc(self.credential, "190931", 'N', 0)
        #return doc

    #----------------------------------------------------------------
    # Return a SubSet node based on subsetName.
    # Don't need to check nodeType since the schema is known
    #    and subsetName is unique.
    # Error checking: node not found.
    #----------------------------------------------------------------
    def __getSubSet(self, docElem):
        if NCGI: print "in __getSubSet"
        pubSys = xml.dom.minidom.parseString(docElem).documentElement
        for node in pubSys.childNodes:
            if node.nodeName == "SystemSubset":
                for n in node.childNodes:
                    if n.nodeName == "SubsetName":
                        for m in n.childNodes:
                            if m.nodeValue == self.subsetName:
                                return node

        # not found
        if NCGI: print docElem
        msg = "Failed in __getSubSet. SubsetName: %s." % self.subsetName
        self.__updateStatus(Publish.FAIL, msg)
        sys.exit(1)

    #----------------------------------------------------------------
    # Return a string for SubsetActionName.
    #----------------------------------------------------------------
    def __getAction(self, subset):
        if NCGI: print "in __getAction\n"
        for node in subset.childNodes:
            if node.nodeName == "SubsetActionName":            
                if NCGI: print node.childNodes[0].nodeValue
                return node.childNodes[0].nodeValue

        return None
        
    #----------------------------------------------------------------
    # Return id if there is a row in the publishing_process table
    #    with status 'active' for the given system and subset.
    #    Active = (In process).
    #----------------------------------------------------------------
    def __existProcess(self):
        if NCGI: print "in __existProcess\n"
        sql = "SELECT id FROM pub_proc WHERE pub_system = "
        sql += self.strCtrlDocId + " AND pub_subset = '" + self.subsetName 
        sql += """' AND status NOT IN ('%s', '%s', '%s')""" % (Publish.SUCCEED, 
                Publish.WAIT, Publish.FAIL)
        rs = self.__execSQL(sql)

        id = 0
        while not rs.EOF:
            id = rs.Fields("id").Value
            rs.MoveNext()
        rs.Close()
        rs = None

        return id

    #----------------------------------------------------------------
    # Create a row the pub_proc table for the given system and subset.
    # The status is from INIT to READY.
    # Also create rows in pub_proc_parm and pub_proc_doc tables.
    # Return id of the newly created row.
    # The id can be used to check status of this process event.
    #----------------------------------------------------------------
    def __createProcess(self):
        if NCGI: print "in __createProcess\n"

        sql = """INSERT INTO pub_proc (pub_system, pub_subset, usr,
            output_dir, started, completed, status, messages) 
            VALUES (%s, '%s', %d, 'temp', GETDATE(), null, '%s', '%s')
            """ % (self.strCtrlDocId, self.subsetName, self.__userId,
                    Publish.INIT, 'This row has just been created.')
        self.__execSQL(sql)

        sql = """SELECT id FROM pub_proc WHERE pub_system = %s AND
            pub_subset = '%s' AND status = '%s'""" % (self.strCtrlDocId,
            self.subsetName, Publish.INIT) 
        rs = self.__execSQL(sql)

        id = 0
        while not rs.EOF:
            id = rs.Fields("id").Value
            rs.MoveNext()
        rs.Close()
        rs = None

        if id != 0:
            # For __insertDoc, we need __procId.
            self.__procId = id

            # Insert rows in pub_proc_parm table
            row = 1
            if self.params:
                for parm in self.params:
                    (name, value) = string.split(parm)
                    sql = """INSERT INTO pub_proc_parm (id, pub_proc, parm_name,
                        parm_value) VALUES (%d, %d, '%s', '%s')
                        """ % (row, id, name, value)
                    self.__execSQL(sql)    
                    row += 1

            # Insert rows in pub_proc_doc table            
            if self.docIds:
                for doc in self.docIds:
                    docId = self.__getDocId(doc)
                    version = self.__getVersion(doc)
                    self.__insertDoc(docId, version)

        # Ready to publish.                    
        sql = """UPDATE pub_proc SET status = '%s' 
                WHERE id = %d""" % (Publish.READY, id)
        self.__execSQL(sql)
        
        return id
    
    #----------------------------------------------------------------
    # Get a list of document IDs, possibly with versions, for publishing.
    # Return a list of docId/version.
    # If a version is not specified, the current publishable version
    #    will be used.
    # Be careful about < and >, &lt;, &gt;
    #----------------------------------------------------------------
    def __getDocIds(self, spec, localParams):
        if NCGI: print "in __getDocIds\n"
        for node in spec.childNodes:
            if node.nodeName == "SubsetSelection":
                for m in node.childNodes:
                    if m.nodeName == "SubsetSQL":
                        sql = ""
                        for n in m.childNodes:
                            if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                                if NCGI: print n.nodeValue
                                sql += n.nodeValue                            
                        sql = self.__repParams(sql, localParams)
                        return self.__getIds(sql)                                    
                    if m.nodeName == "SubsetXQL":
                        if NCGI: print m.childNodes[0].nodeValue
                    elif m.nodeName == "UserSelect":
                        if NCGI: print m.childNodes[0].nodeValue
    
    #----------------------------------------------------------------
    # Replace ?Name? with values in the parameter list.
    #----------------------------------------------------------------    
    def __repParams(self, str, params):
        if NCGI: print "in __repParams\n"
        ret = str    
        for p in params:
            expr = re.compile("\?" + p[0] + "\?")
            ret = expr.sub(p[1], ret)    
    
        if NCGI: print ret
        return ret
                
    #----------------------------------------------------------------
    # Execute the SQL statement using ADODB.
    #----------------------------------------------------------------    
    def __getIds(self, sql):
        if NCGI: print "in __getIds\n"    
        ids = self.docIds
        rs = self.__execSQL(sql)
        while not rs.EOF:
            id = "%s" % rs.Fields("id").Value
            ids.append(id)
            rs.MoveNext()
        rs.Close()
        rs = None
    
        if NCGI and DEBUG: print ids
        return ids

    #----------------------------------------------------------------
    # Get a list of document type for publishing. This is used
    # when DestinationType is DocType and when checking permission.
    #----------------------------------------------------------------
    def __getDocTypes(self, localDocIds):
        if NCGI: print "in __getDocTypes\n"

    #----------------------------------------------------------------
    # Check to see if a user is allowed to publish this set 
    #    of documents. 
    # Return false if not allowed for any document in the set.
    # The permission depends on user group and document type.
    # credential is used.
    #----------------------------------------------------------------
    def __isPermitted(self, action):
        if NCGI: print "in __isPermitted\n"
	return 1


    #----------------------------------------------------------------
    # Get a list of options from the subset.
    # The options specify what to do about publishing results or
    #     processing errors.
    # Minimal error checking is done on < and >.
    #----------------------------------------------------------------
    def __getOptions(self, subset):
        if NCGI: print "in __getOptions\n"
        pairs = []
        pair = ["", ""]
        for node in subset.childNodes:
            if node.nodeName == "SubsetOptions":
                for n in node.childNodes:
                    if n.nodeName == "SubsetOption":
                        for m in n.childNodes:
                            if m.nodeName == "OptionName":
                                pair[0] = m.childNodes[0].nodeValue
                            elif m.nodeName == "OptionValue":
                                pair[1] = m.childNodes[0].nodeValue
                        deep = copy.deepcopy(pair)
                        pairs.append(deep)
                if NCGI: print pairs
                return pairs

        if self.__specs is not None:
            msg = "*Error: no options for a subset specification."
            self.__updateStatus(Publish.FAIL, msg)
            sys.exit(1)

    #----------------------------------------------------------------
    # Get the filters node from the subset specification.
    # The filters are then sequentially applied to the documents 
    #    in the subset.
    #----------------------------------------------------------------
    def __getFilters(self, spec):
        if NCGI: print "in __getFilters\n"
        for node in spec.childNodes:
            if node.nodeName == "SubsetFilters":
                return node
        if NCGI: print "*Error: no filters for a subset specification."

    #----------------------------------------------------------------
    # Get a list of subset parameters from the control document.
    # The list will be used by the same subset.
    # Replacing parameters from argv, params.
    #----------------------------------------------------------------
    def __getParameters(self, subset):
        if NCGI: print "in __getParameters\n"
        pairs = []
        pair = ["", ""]
        for node in subset.childNodes:
            if node.nodeName == "SubsetParameters":
                for n in node.childNodes:
                    if n.nodeName == "SubsetParameter":
                        for m in n.childNodes:
                            if m.nodeName == "ParmName":
                                pair[0] = m.childNodes[0].nodeValue
                            elif m.nodeName == "ParmValue":
                                pair[1] = m.childNodes[0].nodeValue
                        deep = copy.deepcopy(pair)
                        pairs.append(deep)
                if NCGI: print pairs
                return pairs

        return None

    #----------------------------------------------------------------
    # Get warnings or errors from response
    #----------------------------------------------------------------
    def __getWarningOrError(self, document, options):
        if NCGI: print "in __getWarningOrEorror\n"
        return Publish.IGNORE

    #----------------------------------------------------------------
    # Ask user what to do with warnings and errors.
    #----------------------------------------------------------------
    def __getAnswer(self, errCode):
        if NCGI: print "in __getAnswer\n"

    #----------------------------------------------------------------
    # Get the destination directory where the filtered documents will
    #     be stored.
    #----------------------------------------------------------------
    def __getDestination(self, options):
        if NCGI: print "in __getDestination\n"
        for opt in options:
            if opt[0] == "Destination":
                dest = opt[1].encode('latin-1')
                
                # Update the pub_proc table for destination.
                sql = """UPDATE pub_proc SET output_dir = '%s'
                        WHERE id = %d""" % (dest, self.__procId)
                self.__execSQL(sql)
                
                return dest
        
        if self.__specs is not None:
            msg = "*Error: no Destination for the subset options."
            self.__updateStatus(Publish.FAIL, msg)
            sys.exit(1)

    #----------------------------------------------------------------
    # Get the destination type. The type determines how to store the
    #    results: a single file for all documents, a single file
    #     for each document type, or a single file for each document.
    # Minimal error checking is done.
    #----------------------------------------------------------------
    def __getDestinationType(self, options):
        if NCGI: print "in __getDestinationType\n"
        for opt in options:
            if opt[0] == "DestinationType":
                if opt[1] == "File":
                    return Publish.FILE
                elif opt[1] == "Doc":
                    return Publish.DOC
                else:
                    return Publish.DOCTYPE

        if self.__specs is not None:
            msg = "*Error: no DestinationType for the subset options."
            self.__updateStatus(Publish.FAIL, msg)
            sys.exit(1)            

    #----------------------------------------------------------------
    # Get the destination file. A fileName for all documents.
    # Minimal error checking is done.
    #----------------------------------------------------------------
    def __getDestinationFile(self, options):
        if NCGI: print "in __getDestinationFile\n"
        for opt in options:
            if opt[0] == "DestinationFileName":
                return opt[1]

        if self.__specs is not None:
            msg = "*Error: no DestinationFile for the subset options."
            self.__updateStatus(Publish.FAIL, msg)
            sys.exit(1)

    #----------------------------------------------------------------
    # Get the subset specifications node.
    #----------------------------------------------------------------
    def __getSpecs(self, subset):
        if NCGI: print "in __getSpecs\n"
        for node in subset.childNodes:
            if node.nodeName == "SubsetSpecifications":
                return node

        return None

    #----------------------------------------------------------------
    # Get the list of subset specifications filter Ids. 
    #----------------------------------------------------------------
    def __getFilterId(self, filter):
        if NCGI: print "in __getFilterId\n"
        for node in filter.childNodes:
            if node.nodeName == "SubsetFilterId":
                return node.childNodes[0].nodeValue
            elif node.nodeName == "SubsetFilterName":
                return node.childNodes[0].nodeValue

        if NCGI: print "*Error: no filter Id or Name for a filter."

    #----------------------------------------------------------------
    # Get the list of subset specifications filter parameters. 
    #----------------------------------------------------------------
    def __getParams(self, filter):
        if NCGI: print "in __getParams\n"
        pairs = []
        pair = ["", ""]
        for node in filter.childNodes:
            if node.nodeName == "SubsetFilterParm":
                for m in node.childNodes:
                    if m.nodeName == "ParmName":
                        pair[0] = m.childNodes[0].nodeValue
                    elif m.nodeName == "ParmValue":
                        pair[1] = m.childNodes[0].nodeValue            
                deep = copy.deepcopy(pair)
                pairs.append(deep)
        if NCGI: print pairs
        return pairs

    #----------------------------------------------------------------
    # Publish the whole subset in a single file. The file with name
    #     fileName is replaced.
    # Parameter "credential" is needed only if methods in cdr.py 
    #    are used.
    #----------------------------------------------------------------
    def __publishAll(self, localDocIds, filters,
                localParams, dest, fileName, options): 
        
            pubDoc = ""
            if NCGI: print localDocIds
            for doc in localDocIds:    
            
                # doc = docId/version format?
                docId = self.__getDocId(doc)
                version = self.__getVersion(doc)

                # Insert a row into publishing_process_documents
                # table.
                self.__insertDoc(docId, version)
                
                # Get the document with the appropriate version.
                # This needs to be detailed! Lock?
                document = cdr.getDoc(self.credential, docId, 
                        'N', version)
                
                # Apply filters sequentially to each document.
                # Mike said that this would be done by one call!
                for filter in filters.childNodes:
                    
                    # There are nodes like "#text"
                    if filter.nodeName != "SubsetFilter":
                        continue
                    
                    # Get ID/Name and Parameters.
                    filterId = self.__getFilterId(filter)
                    filterParam = self.__getParams(filter)

                    # How to pass filter parameters along?
                    # New API from CDR server?    
                    if NCGI and DEBUG: print document                    
                    document = cdr.filterDoc(self.credential, filterId, 
                        docId) 
                    # , document)
                    if NCGI: print docId
                    if NCGI: print filterId    
                        

                    # Abort On Error?
                    # Where to get the returned warnings or errors?
                    # From Response element in document?
                    errCode = self.__getWarningOrError(document,
                        options)

                    # If there are warnings or errors, do something 
                    # about it.
                    if errCode == Publish.IGNORE: # Warning with No
                        self.__deleteDoc(docId, version)
                        continue
                    elif errCode == ASK:
                        self.__updateStatus(WAIT)
                        answer = self.__getAnswer(errCode, options)
                        self.__updateStatus(RUN)
                        if answer == NO:
                            self.__deleteDoc(docId, version)
                            continue            
                    elif errCode == ABORT:
                        self.__deleteDoc(docId, version)
                        self.__updateStatus(FAIL)
                        sys.exit(1)

                # Merge all documents into one.
                # How to do this exactly? Just concatenate them?
                pubDoc += document[0]
        
            # Save the file in the "new" subdirectory.
            self.__saveDoc(pubDoc, dest + "/new", fileName)
                
    #----------------------------------------------------------------
    # Publish each type of documents in a single file with the 
    #    document type name being the file name. All files in the 
    #     destination directory are deleted before adding the 
    #    new files.
    #----------------------------------------------------------------
    def __publishType(self, loclDocIds, filters, 
            loclaParams, dest, docTypes, options):
        # Similar to publishAll(), but have to loop through all
        #     different docTypes.
        if NCGI: print "in __publishType\n"         

    #----------------------------------------------------------------
    # Publish each document in a file with the document ID being 
    #    the file name. All files in the destination directory 
    #     are deleted before adding the new files.
    #----------------------------------------------------------------
    def __publishDoc(self, localDocIds, filters,
            localParams, dest, options): 
        if NCGI: print "in __publishDoc\n"

        msg = "Successfully published all documents: " 
        if NCGI: print localDocIds
        for doc in localDocIds:    
        
            # doc = docId/version format?
            docId = self.__getDocId(doc)
            version = self.__getVersion(doc)

            # Don't publish a document more than once.
            if NCGI: print docId
            if NCGI: print version            
            if self.__docIds.has_key(docId):
                if NCGI: print "Duplicate docId: %s" % docId
                continue
            self.__docIds[docId] = docId
            
            # Prepare the message to be logged.
            msg += "%s, " % doc            

            # Insert a row into pub_proc_doc table.
            self.__insertDoc(docId, version)                
        
            # Apply filters sequentially to each document.
            # Simply call cdr.filterDoc which accepts a list of filterIds.
            filterIds = []
            for filter in filters.childNodes:
                    
                # There are nodes like "#text"
                if filter.nodeName != "SubsetFilter":
                    continue
                    
                # Get ID/Name and Parameters.
                filterIds.append(self.__getFilterId(filter))
                filterParam = self.__getParams(filter)

            if NCGI: print filterIds
            pubDoc = cdr.filterDoc(self.credential, filterIds, docId) 

            # Detect error here!
            # updateStatus(WARNING, pubDoc[1])

            # Save the file in the "new" subdirectory.
            self.__saveDoc(pubDoc[0], dest + "/new", docId)
            if NCGI: print pubDoc[1]        
        
        self.__updateStatus(Publish.SUCCEED, msg)

    #----------------------------------------------------------------
    # Get the document ID from ID/Version string 123456/2.5.
    # Wrong docId will be caught by cdr.getDoc.
    #----------------------------------------------------------------
    def __getDocId(self, doc):
        if NCGI: print "in __getDocId\n"
        expr = re.compile("[\sCDR]*(\d+)", re.DOTALL)
        id = expr.search(doc)
        if id: 
            return id.group(1)
        else:
            if NCGI: print "*Error: bad docId format - " + doc
            sys.exit(1)

    #----------------------------------------------------------------
    # Get the version from ID/Version string 123456/2.5.
    # Error in format has been caught by __getDocId.
    # Wrong version will be caught by cdr.getDoc.
    #----------------------------------------------------------------
    def __getVersion(self, doc):
        if NCGI: print "in __getVersion\n"
        expr = re.compile("[\sCDR]*\d+/(.*)", re.DOTALL)
        id = expr.search(doc)
        if id and id.group(1) != "":
            return id.group(1)
        else:
            return 1        

    #----------------------------------------------------------------
    # Update the publishing_process table. 
    #----------------------------------------------------------------
    def __updateStatus(self, status, errMsg):
        if NCGI: print "in __updateStatus\n"   
          
        sql = "UPDATE pub_proc SET status = '" + status + "', messages = '" 
        sql += errMsg + "' WHERE id = " + "%d" % self.__procId
        #self.__execSQL(sql)
        # What if update failed?
        self.__cdrConn.Execute(sql)

        if status == Publish.SUCCEED:
            sql = "UPDATE pub_proc SET completed = GETDATE() "
            sql += "WHERE id = " + "%d" % self.__procId
            #self.__execSQL(sql)
            # What if update failed?    
            self.__cdrConn.Execute(sql)        

        # sql += " DECLARE @ptrval varbinary(16) "
        # sql += " SELECT @ptrval = textptr(messages) FROM pub_proc "
        # sql += " WRITETEXT pub_proc.messages @ptrval '" + errMsg + "'"
    
    #----------------------------------------------------------------
    # Update the publishing_events, published_documents tables from
    #     publishing_process and publishing_process_documents tables. 
    #----------------------------------------------------------------
    def __updateStatuses(self): 
        if NCGI: print "in __updateStatuses\n"

        # Copy a row with procId to insert into pub_event.        
        sql = "INSERT INTO pub_event SELECT p.pub_system, p.pub_subset, "
        sql += "p.usr, p.started, p.completed FROM pub_proc p WHERE p.id "
        sql += " = %d" % self.__procId
        self.__execSQL(sql)

        # Get id from pub_event.
        sql = "SELECT e.id AS eid FROM pub_event e WHERE EXISTS (SELECT * "
        sql += "FROM pub_proc p WHERE p.pub_system = e.pub_system AND "
        sql += "p.pub_subset = e.pub_subset AND p.usr = e.usr AND "
        sql += "p.started = e.started AND "
        sql += "p.id = %d" % self.__procId + ")"
        rs = self.__execSQL(sql)

        id = 0
        while not rs.EOF:
            id = rs.Fields("eid").Value
            rs.MoveNext()
        rs.Close()
        rs = None

        if id == 0:
            msg = "*Error: fetching id from pub_event in __updateStatuses failed."
            self.__updateStatus(Publish.FAIL, msg)
            sys.exit(1)
        
        # We can now update published_doc table. 
        sql = "INSERT INTO published_doc SELECT '" + "%d" % id + "', p.doc_id, p.doc_version "
        sql += "FROM pub_proc_doc p "
        sql += "WHERE p.pub_proc = %d" % self.__procId
        self.__execSQL(sql)

    #----------------------------------------------------------------
    # Return the status field from the publishing_process table. 
    #----------------------------------------------------------------
    def __getStatus(self): 
        if NCGI: print "in __getStatus\n"
        sql = "SELECT status FROM pub_proc "
        sql += "WHERE id = " + "%d" % self.__procId 
        rs = self.__execSQL(sql)

        status = None
        while not rs.EOF:
            status = rs.Fields("status").Value
            rs.MoveNext()
        rs.Close()
        rs = None
    
        if NCGI: print status
        return status

    #----------------------------------------------------------------
    # Delete a row from publishing_process_documents table.
    #----------------------------------------------------------------
    def __deleteDoc(self, docId, version):
        if NCGI: print "in __deleteDoc\n"
        sql = """DELETE FROM pub_proc_doc WHERE id = %d AND doc_id = %s
                AND doc_version = %s""" % (self.__procId, doc_id, version)
        self.__execSQL(sql)

    #----------------------------------------------------------------
    # Insert a row into pub_proc_doc table. 
    #----------------------------------------------------------------
    def __insertDoc(self, docId, version):
        if NCGI: print "in __insertDoc\n"
        sql = """INSERT INTO pub_proc_doc (pub_proc, doc_id, doc_version)
                VALUES (%d, %s, %s)""" % (self.__procId, docId, version)
        self.__execSQL(sql)

    #----------------------------------------------------------------
    # Save the document in the temporary subdirectory.
    #----------------------------------------------------------------
    def __saveDoc(self, document, dir, fileName):
        if not os.path.isdir(dir):
            os.makedirs(dir)
        fileObj = open(dir + "/" + fileName, 'w')
        fileObj.write(document)

    #----------------------------------------------------------------
    # Handle process script. This is specific for Bob's Python script.
    # If this subset does not contain process script, simply return.
    # The cmd string should be determined by options in the control
    #   document, not hard-coded unless we agree that all the process
    #	script will only accept JobId as its only argument.
    #----------------------------------------------------------------
    def __invokeProcessScript(self, subset):
        if NCGI: print "in __invokeProcessScript\n"
        scriptName = ""
        for node in subset.childNodes:
            # The 'choice' in schema requires one and only
            #   one element in this subset. 
            # Second 'if' is not needed. Leave it there for safety
            #   or for future schema updates.
            if node.nodeName == "SubsetSpecifications":
                return 
            if node.nodeName == "ProcessScript":
                for n in node.childNodes:
                    if n.nodeType == xml.dom.minidom.Node.TEXT_NODE:
                        scriptName += n.nodeValue
        # Is the location of the script always in cdr.SCRIPTS?
        scriptName = cdr.SCRIPTS + "/" + scriptName
        if not os.path.isfile(scriptName):
            if NCGI: print scriptName + " not found!"
            sys.exit(1)
        cmd = scriptName + " %d" % self.__procId
        if NCGI: print "'" + cmd + "' is running!"
        os.system(cmd)
        sys.exit(0)

# Accept one argument which is the __procId. ctrlDoc (title) will
#    not be used to select control document in new design.
def main():    
    
    # Prove we've been here.
    
    if NCGI: 
        f = open("d:/cdr/log/publish.log", "a")
        os.dup2(f.fileno(), 1)
        print "=====Job started at: %s" % time.ctime(time.time())

    try:    
        # Make sure we have the process JobId
        if len(sys.argv) < 2: 
            if NCGI: print "*Error: Usage: pubmod.py jobId."
            sys.exit(1)
       
        p = Publish("Fake", "Fake", "Fake", [], [], string.atoi(sys.argv[1]))
        p.publish() 

    except:        
        if NCGI: 
            import traceback
            os.dup2(f.fileno(), 2)
            traceback.print_tb(sys.exc_traceback)  
            os.dup2(f.fileno(), 1)     

    if NCGI: 
        print "=====Job ended at: %s" % time.ctime(time.time())
        f.close()           

# No longer useful with the new design. Leave it here for reference.
def main_old():    
    # Parse the command line arguments and hand them in to class Publish.
    if len(sys.argv) < 1:
        if NCGI:
            print "*Error: Usage: publish.py args. args is a string of arguments separated by \\n."
        sys.exit(1)
    else:
        args = sys.argv[1]        #How to make sys.stdin.readlines() work? Don't bother.    
    
    if NCGI: print args        
    #args = decodeUrl(args) Use urllib.unquote_plus when needed
    if NCGI: print args

    arglist = string.split(args, "::")
    argc = len(arglist)
    if argc < 5:
        if NCGI:
            print "*Error: there is only %d lines of arguments. It should be at least 5." % argc
        sys.exit(1)        
        
    expr = re.compile(r"\[Control\]::(.*)", re.DOTALL)
    value = expr.search(args)
    if not value:
        if NCGI:
            print "*Error: there is no [Control], XML for control information."
        sys.exit(1)
    ctrlDoc = value.group(1)
    if NCGI: print ctrlDoc

    params = []
    expr = re.compile(r"\[Parameters\]::(.*?)::\[", re.DOTALL)
    value = expr.search(args)
    if value:
        pairs = value.group(1)
        params = string.split(pairs, "::")
        if NCGI: print params
    
    docIds = []
    expr = re.compile(r"\[Documents\]::(.*?)::\[", re.DOTALL)
    value = expr.search(args)
    if value:
        docs = value.group(1)
        docIds = string.split(docs, "::")
        if NCGI: print docIds

    jobId = None
    expr = re.compile(r"\[JobId\]::(.*?)::", re.DOTALL)
    value = expr.search(args)
    if value:
        jobId = value.group(1)
        if NCGI: print jobId        

    system = arglist[2]
    subset = arglist[3]
    #user = arglist[4]
    credential = arglist[4]    #cdr.login(user, "***REDACTED***")

    p = Publish(system, subset, credential, docIds, params, ctrlDoc, jobId)
    p.publish()    


if __name__ == "__main__":
    main()
