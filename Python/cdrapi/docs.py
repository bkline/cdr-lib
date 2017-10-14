"""
Manage CDR documents
"""

from builtins import int
import datetime
import re
import threading
import time
import urllib.parse
import dateutil.parser
from lxml import etree
from cdrapi import db
from cdrapi.db import Query
from cdrapi.settings import Tier


try:
    basestring
except:
    basestring = unicode = str

class Doc(object):
    """
    Information about an XML document in the CDR repository

    All of the attributes for the object are implemented as properties,
    fetched as needed to optimize away potentially expensive unnecessary
    processing.

    Read-only attributes:
      session - object representing the CDR session for which the
                document information was collected
      id - primary key in the `all_docs` database table for the document
      cdr_id - standard string representation for the document's id
      version - optional integer represent version requested for the doc
      last_version - integer for the most recently created version
      last_version_date - when the last version was created
      last_publishable_version - integer for most recent pub version
      checked_out_by - string for account holding lock on the document
      last_saved - when the document was most recently saved
      has_unversioned changes - True if the all_docs table was updated
                                more recently than the doc's latest version
      creator - name of account which first created this document
      created - date/time the document was originally created
      modifier - name of account which most recently updated the doc
      modified - when the document was most recently updated
      active_status - 'A' if the document is active; 'I' if inactive
      publishable - True iff the object's version is marked publishable
      ready_for_review - True if the document has be marked review ready
      title - string for the title of this version of the document
      val_status - 'V' (valid), 'I' (invalid), or 'U' (unvalidated)
      val_date - when the version's validation status was last determined
      comment - description of this version of the document
      denormalized_xml - xml with links resolved

    Read/write attributes:
      xml - unicode string for the serialized DOM for the document
      blob - bytes for a BLOB associated with the document (optional)
      doctype - string representing the type of the document (e.g., Term)
    """

    NS = "cips.nci.nih.gov/cdr"
    NSMAP = {"cdr": NS}
    CDR_REF = "{" + Doc.NS + "}ref"
    NOT_VERSIONED = "document not versioned"
    NO_PUBLISHABLE_VERSIONS = "no publishable version found"

    def __init__(self, session, **opts):
        """
        Capture the session and options passed by the caller

        Required positional argument:
          session - `Session` object for which `Doc` object is made

        Optional keyword arguments
          id - optional unique identifier for existing CDR document
          xml - serialized tree for the XML document
          blob - binary large object (BLOB) for the document
          version - legal values are:
            "Current" for current working copy of document
            "LastVersion" or "last" for most recent version of docuement
            "LastPublishableVersion" or "lastp" for latest publishable ver
            "Before YYYY-MM-DD" to get latest version before date
            "Label ..." to get version with specified label
            version number integer
            default is current working copy of document from all_docs table
        """

        self.__session = session
        self.__opts = opts

    @property
    def session(self):
        """
        `Session` for which this `Doc` object was requested
        """

        return self.__session

    @property
    def id(self):
        """
        Unique integer identifier for the CDR document
        """

        if hasattr(self, "_id"):
            return self._id
        return self._id = self.extract_id(self.__opts.get("id"))

    @staticmethod
    def extract_id(arg):
        if isinstance(arg, int):
            return arg
        return int(re.sub(r"[^\d]", "", str(arg).split("#")[0]))

    @property
    def cdr_id(self):
        """
        Canonical string form for the CDR document ID (CDR9999999999)
        """

        return "CDR{:010}".format(self.id) if self.id else None

    @property
    def version(self):
        """
        Integer for specific version of None for all_docs row
        """

        if hasattr(self, "_version"):
            return self._version
        if not self.id:
            return self._version = None
        version = self.__opts.get("version")
        if not version:
            return self._version = None
        if isinstance(version, int):
            return self._version = (version if version > 0 else None)
        try:
            version = version.lower()
        except:
            raise Exception("invalid version {!r}".format(version))
        if version == "current":
            return self._version = None
        if version in ("last", "lastversion"):
            version = self.last_version
            if not version:
                raise Exception(self.NOT_VERSIONED)
            return self._version = version
        if version.startswith("lastp"):
            version = self.last_publishable_version
            if not version:
                raise Exception(self.NO_PUBLISHABLE_VERSIONS)
            return self._version = version
        if version.startswith("before "):
            tokens = version.split(" ", 1)
            if len(tokens) != 2:
                raise Exception("missing date for version specifier")
            return self._version = self.__get_version_before(tokens[1])
        if version.startswith("label "):
            tokens = version.split(" ", 1)
            if len(tokens) != 2:
                raise Exception("missing token for version specifier")
            return self._version = self.__get_labeled_version(label)
        try:
            return self._version = int(version)
        except:
            raise Exception("invalid version spec {}".format(version))

    @property
    def xml(self):
        """
        Unicode string for the serialized DOM for this version of the doc
        """

        if hasattr(self, "_xml"):
            return self._xml
        self._xml = self.__opts.get("xml")
        if self._xml:
            if not isinstance(self._xml, unicode):
                self._xml = self._xml.decode("utf-8")
        elif self.id:
            if self.version:
                query = Query("doc_version", "xml")
                query.where(query.Condition("num", self.version))
            else:
                query = Query("document", "xml")
            query.where(query.Condition("id", self.id))
            row = query.execute(self.session.cursor).fetchone()
            if not row:
                raise Exception("no xml found")
            self._xml = row[0]
        return self._xml

    @xml.setter
    def xml(self, value):
        """
        Assign a new value to the `xml` property, coercing to Unicode

        Invalidate any parse trees or version numbers.

        Pass:
          value - new property value
        """

        self._xml = value
        if self._xml and not isinstance(self._xml, unicode):
            self._xml = self._xml.decode("utf-8")
        self._root = self._version = self._denormalized_xml = None

    @property
    def root(self):
        """
        Parsed tree for the document's XML
        """

        if hasattr(self, "_root"):
            return self._root
        return self._root = etree.fromstring(self.xml.encode("utf-8"))

    def has_blob(self):
        """
        Determine whether the document has a BLOB for this version

        Avoid fetching the bytes for the BLOB if it hasn't already been
        done; just get the primary key for the BLOB.
        """

        if hasattr(self, "_blob"):
            return self._blob is not None
        if not self.id:
            return False
        if hasattr(self, "_blob_id"):
            return True if self._blob_id else False
        table = "version_blob_usage" if self.version else "doc_blob_usage"
        query = Query(table, "blob_id")
        query.where(query.Condition("doc_id", self.id))
        if self.version:
            query.where(query.Condition("doc_version", self.version))
        row = query.execute(self.session.cursor).fetchone()
        self._blob_id = row[0] if row else None
        return True if self._blob_id else False

    @property
    def blob(self):
        """
        Bytes for BLOB associated with this version of the document
        """

        if hasattr(self, "_blob"):
            return self._blob
        if "blob" in self.__opts:
            return self._blob = self.__opts["blob"]
        if not self.has_blob():
            return self._blob = None
        query = Query("doc_blob", "data")
        query.where(query.Condition("id", self._blob_id))
        row = query.execute(self.session.cursor).fetchone()
        if not row:
            raise Exception("no blob found")
        return self._blob = row[0]

    @blob.setter
    def blob(self, value): self._blob = value

    @property
    def doctype(self):
        """
        String representing the type of the document (e.g., 'Summary')

        We have to be careful to look in the row for the version if
        the object represents a specific version, because the document
        type can change from one version to the next.
        """

        if hasattr(self, "_doctype"):
            return self._doctype
        if "doctype" in self.__opts:
            return self._doctype = self.__opts["doctype"]
        if not self.id:
            return self._doctype = None
        table = "doc_version" if self.version else "document"
        query = Query("doc_type t", "t.name")
        query.join(table + " d", "d.doc_type = t.id")
        query.where(query.Condition("d.id", self.id))
        if self.version:
            query.where(query.Condition("d.num" self.version))
        row = query.execute(self.session.cursor).fetchone()
        if not row:
            what = "version" if self.version else "document"
            raise Exception(what + " not found")
        return self._doctype = row[0]

    @doctype.setter
    def doctype(self, value): self._doctype = value

    @property
    def last_version(self):
        """
        Integer for the most recently saved version, if any; else None
        """

        if hasattr(self, "_last_version"):
            return self._last_version
        if not self.id:
            return self._last_version = None
        query = Query("doc_version", "MAX(num)")
        query.where(query.Condition("id", self.id))
        row = query.execute(self.session.cursor).fetchone()
        return self._last_version = (row[0] if row else None)

    @property
    def last_version_date(self):
        """
        Date/time when the last version was created, if any; else None
        """

        if hasattr(self, "_last_version_date"):
            return self._last_version_date
        if not self.last_version:
            return self._last_version_date = None
        query = Query("doc_version", "dt")
        query.where(query.Condition("id", self.id))
        query.where(query.Condition("num", self.last_version))
        row = query.execute(self.session.cursor).fetchone()
        return self._last_version_date = row[0]

    @property
    def last_publishable_version(self):
        """
        Integer for the most recently created publishable version, if any
        """

        if not self.id:
            return None
        query = Query("doc_version", "MAX(num)")
        query.where(query.Condition("id", self.id))
        query.where("publishable = 'Y'")
        row = query.execute(self.session.cursor).fetchone()
        return row[0] if row else None

    def __get_version_before(self, before, publishable=None):
        """
        Find the latest version created before the specified date/time

        Pass:
          before - string or `datetime` object
          publishable - if True only look for publishable versions;
                        if False only look for unpublishable versions;
                        otherwise ignore the `publishable` column

        Return:
          integer for the version found (or None)
        """

        if isinstance(before, (datetime.date, datetime.datetime)):
            when = before
        else:
            try:
                when = dateutil.parser.parse(before)
            except:
                raise Exception("unrecognized date/time format")
        query = Query("doc_version", "MAX(num)")
        query.where(query.Condition("id", self.id))
        query.where(query.Condition("dt", when, "<"))
        if publishable is True:
            query.where("publishable = 'Y'")
        elif publishable is False:
            query.where("publishable = 'N'")
        row = query.execute(self.session.cursor).fetchone()
        if not row:
            raise Exception("no version before {}".format(when))
        return row[0]

    def __get_labeled_version(label):
        """
        Find the version for this document with the specified label

        This feature has never been used in all the years the CDR
        has been in existence, but CIAT has requested that we preserve
        the functionality.
        """

        query = Query("doc_version v", "MAX(v.num)")
        query.join("doc_version_label d", "d.document = v.id")
        query.join("version_label l", "l.id = d.label")
        query.where(query.Condition("v.id", self.id))
        query.where(query.Condition("l.name", label))
        row = query.execute(self.session.cursor).fetchone()
        if not row:
            raise Exception("no version labeled {}".format(label))
        return row[0]

    @property
    def checked_out_by(self):
        """
        String for the name of the account holding a lock on the document

        Return None if the document is unlocked.
        """

        query = Query("usr u", "u.name")
        query.join("checkout c", "c.usr = u.id")
        query.where(query.Condition("c.id", self.id))
        query.where("c.dt_in IS NULL")
        row = query.execute(self.session.cursor).fetchone()
        return row[0] if row else None

    @property
    def last_saved(self):
        """
        Return the last time the document was saved

        Includes document creation or modification, with or without
        versioning.
        """

        if hasattr(self, "_last_saved"):
            return self._last_saved
        return self._last_saved = (self._modified or self._added)

    def has_unversioned_changes(self):
        """
        Determine if the document has saved after the last version
        """

        if not self.last_version_date:
            return False
        return self.last_version_date < self.last_saved

    def unlock(**opts):
        """
        if the document is not checked out:
            throw an exception
        if the document is checked out by another account:
            if the force flag is not set:
                throw an exception
            if the user is not allowed to perform a force unlock:
                throw an exception
        update the checkout table, optionally changing the comment column
        if the document has unversioned changes the caller want to preserve:
            create a new version (including blob if present)
        otherwise, if the force flag is set:
            add an UNLOCK row to the audit_trail table
        """

    def lock(**opts):
        """
        Add a row to the `checkout` table for this document
        """

        if not session.can_do("MODIFY DOCUMENT", self.doctype):
            raise Exception("User not authorized to modify document")
        query = Query("checkout", "usr", "dt_out")
        query.where(query.Condition("id", self.id))
        query.where("dt_in IS NULL")
        row = query.execute(self.session.cursor).fetchone()
        if row:
            user_id, checked_out = row
            if user_id == self.user_id:
                return
            if opts.get("force"):
                if not self.session.can_do("FORCE CHECKOUT", self.doctype):
                    raise Exception("User not authorized to force checkout")
                self.unlock(abandon=True, force=True)

    def legacy_doc(self, **opts):
        """
        Create a DOM tree matching what the original `cdr.Doc` object uses

        Pass:
          get_xml - if True, include the CdrDocXml element
          get_blob - if True, include the CdrDocBlob element if there is
                     a BLOB for this version of the document
        """

        cdr_doc = etree.Element("CdrDoc")
        cdr_doc.set("Type", self.doctype)
        cdr_doc.set("Id", self.cdr_id)
        cdr_doc.append(self.legacy_doc_ctl(**opts))
        if opts.get("get_xml"):
            xml = self.xml
            if opts.get("denormalize"):
                xml = self.denormalize(xml)
            etree.SubElement(cdr_doc, "CdrDocXml").text = etree.CDATA(xml)
        if opts.get("get_blob") and self.has_blob:
            blob = etree.SubElement(cdr_doc, "CdrDocBlob" encoding="base64")
            blob.text = base64.encodestring(self.blob).decode("ascii")
        return cdr_doc

    @property
    def denormalized_xml(self, xml):
        """
        TODO: implement me when we have filtering
        """
        if hasattr(self, "_denormalized_xml"):
            if self._denormalized_xml is not None:
                return self._denormalized_xml

    def legacy_doc_control(self, **opts):
        """
        Create a CdrDocCtl DOM tree

        Used for assembling part of a CdrDoc DOM tree for the CdrGetDoc
        command. Also used independently of a CdrDoc document, and with
        additional child elements, for filtering callbacks.

        Pass:
          filtering - if True, include extra Create, Modify, and FirstPub
                      blocks; if False, mark all children as read-only

        Return:
          `etree.Element` object with nested children
        """

        filtering = opts.get("filtering", False)
        modified = self.make_xml_date_string(self.modified)
        val_date = self.make_xml_date_string(self.val_date)
        doc_control = etree.Element("CdrDocCtl")
        control_info = [
            ("DocTitle", self.title),
            ("DocActiveStatus", self.active_status),
            ("DocValStatus", self.val_status),
            ("DocValDate", val_date),
            ("DocVersion", self.version),
            ("DocModified", modified),
            ("DocModifier", self.modifier),
            ("DocComment", self.comment),
            ("ReadyForReview", self.ready_for_review),
        ]
        for tag, value in control_info:
            if value:
                child = etree.SubElement(doc_control, tag)
                child.text = str(value)
                if not filtering:
                    child.set("readonly", "yes")
                if tag == "DocVersion":
                    child.set("Publishable", "Y" if self.publishable else "N")
        if filtering:
            created = self.make_xml_date_string(self.created)
            first_pub = self.make_xml_date_string(self.first_pub)
            wrapper = etree.SubElement(doc_control, "Create")
            etree.SubElement(wrapper, "Date").text = created
            etree.SubElement(wrapper, "User").text = self.creator
            wrapper = etree.SubElement(doc_control, "Modify")
            etree.SubElement(wrapper, "Date").text = modified
            etree.SubElement(wrapper, "User").text = self.modifier
            if first_pub:
                wrapper = etree.SubElement(doc_control, "FirstPub")
                etree.SubElement(wrapper, "Date").text = first_pub
        return doc_control

    @staticmethod
    def make_xml_date_string(value):
        """
        Convert date or date/time value to XML standard format

        Pass:
          string or datetime.date object or datetime.datetime object or None

        Return:
          if just a date, return YYYY-MM-DD; if a date/time, return
          YYYY-MM-DDTHH:MM:SS; otherwise None
        """

        if not value:
            return None
        return str(value)[:19].replace(" ", "T")

    @property
    def creator(self):
        """
        Name of account which first created this document
        """

        if not hasattr(self, "_creator"):
            self.__fetch_creation_info()
        return self._creator

    @property
    def created(self):
        """
        Date/time the document was originally created
        """

        if not hasattr(self, "_created"):
            self.__fetch_creation_info()
        return self._created

    @property
    def modifier(self):
        """
        Name of account which most recently updated the document

        None if the document has not been updated since being created.
        """

        if not hasattr(self, "_modifier"):
            self.__fetch_modification_info()
        return self._modifier

    @property
    def modified(self):
        """
        Date/time the document was most recently updated (if ever)
        """

        if not hasattr(self, "_modified"):
            self.__fetch_modification_info()
        return self._modified

    def __fetch_creation_info(self):
        """
        Get the account name and date/time for the document's creation
        """

        self._creator = self._created = None
        if self.id:
            query = Query("audit_trail t", "t.dt", "u.name")
            query.join("usr u", "u.id = t.usr")
            query.join("action a", "a.id = t.action")
            query.where(query.Condition("t.document", self.id))
            query.where("a.name = 'ADD DOCUMENT'")
            row = query.execute(self.session.cursor).fetchone()
            if row:
                self._created, self._creator = row

    def __fetch_modification_info(self):
        """
        Get the user and time the document was last modified
        """

        self._modifier = self._modified = None
        if self.id:
            query = Query("audit_trail t", "t.dt", "u.name").limit(1)
            query.join("usr u", "u.id = t.usr")
            query.join("action a", "a.id = t.action")
            query.where(query.Condition("t.document", self.id))
            query.where("a.name = 'MODIFY DOCUMENT'")
            row = query.order("t.dt").execute(self.session.cursor).fetchone()
            if row:
                self._modified, self._modifier = row

    @property
    def active_status(self):
        """
        'A' if the document is active; 'I' if inactive ("blocked")
        """

        if not hasattr(self, "_active_status"):
            if not self.id:
                return self._active_status = None
            query = Query("document", "active_status", "first_pub")
            query.where(query.Condition("id", self.id))
            row = query.execute(self.session.cursor).fetchone()
            self._active_status, self._first_pub = row
        return self._active_status

    @property
    def first_pub(self):
        """
        Date/time the document was first published if known
        """

        if not hasattr(self, "_first_pub"):
            if not self.id:
                return self._first_pub = None
            query = Query("document", "active_status", "first_pub")
            query.where(query.Condition("id", self.id))
            row = query.execute(self.session.cursor).fetchone()
            self._active_status, self._first_pub = row
        return self._first_pub

    @property
    def publishable(self):
        """
        True if this is a numbered publishable version; else False
        """

        if not hasattr(self, "_publishable"):
            if not self.id or not self.version:
                return self._publishable = None
            query = Query("doc_version", "publishable")
            query.where(query.Condition("id", self.id))
            query.where(query.Condition("num", self.version))
            row = query.execute(self.session.cursor).fetchone()
            if not row:
                return self._publishable = None
            self._publishable = row[0] == "Y"
        return self._publishable

    @property
    def ready_for_review(self):
        """
        True if this is a new document which is ready for review
        """

        if not hasattr(self, "_ready_for_review"):
            query = Query("ready_for_review", "doc_id")
            query.where(query.Condition("doc_id", self.id))
            row = query.execute(self.session.cursor).fetchone()
            self._ready_for_review = True if row else False
        return self._ready_for_review

    @property
    def title(self):
        """
        String for the title of this version of the document
        """

        if not hasattr(self, "_title"):
            self.__fetch_common_properties()
        return self._title

    @property
    def val_status(self):
        """
        'V' (valid), 'I' (invalid), or 'Y' (unvalidated)
        """

        if not hasattr(self, "_val_status"):
            self.__fetch_common_properties()
        return self._val_status

    @property
    def val_date(self):
        """
        Date/time this version of the document was last validated
        """

        if not hasattr(self, "_val_date"):
            self.__fetch_common_properties()
        return self._val_date

    @property
    def comment(self):
        """
        String describing this version of the document
        """

        if not hasattr(self, "_comment"):
            self.__fetch_common_properties()
        return self._comment

    def __fetch_common_properties(self):
        """
        Fetch and cache values from a single table

        If any of these values are retrieved, we might as well grab them
        all, to save multiple queries to the same table.
        """

        self._title = self._val_status = self._val_date = self._comment = None
        if self.id:
            table = "doc_version" if self.version else "document"
            query = Query(table, "title", "val_status", "val_date", "comment")
            query.where(query.Condition("id", self.id))
            if self.version:
                query.where(query.Condition("num", self.version))
            row = query.execute(self.session.cursor).fetchone()
            self._title row[0]
            self._val_status = row[1]
            self._val_date = row[2]
            self._comnment = row[3]

    def filter(self, *filters, **opts):
        """
        Apply one or more filters to the XML for the document

        Positional arguments:
          filters - each positional argument represents a named
                    filter ("name:..."), a named filter set ("set:...")
                    or a filter's document ID

        Optional keyword arguments:
          parms - dictionary of parameters to be passed to the filtering
                  engine (parameter values indexed by parameter names)
          output - if False, only return the warning and error messages
          version - which versions of the filters to use ("last" or "lastp"
                    or a version number), a specific version number only
                    makes sense in the case of a request involving a
                    single filter, and is probably a mistake in most cases
          date - if specified, only use filters earlier than this date/time;
                 can be used in combination with `version` (for example,
                 to use the latest publishable versions created before
                 a publishing job started)
          filter - used to pass in the XML for an in-memory filter
                   instead of using filters pulled from the repository
                   (cannot be used in combination with positional
                   filter arguments)
        """

        filters = self.__assemble_filters(*filters, **opts)
        parms = opts.get("parms") or {}
        doc = self.root
        messages = []
        parser = self.Parser()
        Resolver.local.docs.append(self)
        try:
            for f in self.filters:
                result = self.__apply_filter(f, doc, parser, **parms)
                doc = result.doc
                for entry in result.error_log:
                    messages.append(entry.message)
            if opts.get("output", True):
                return self.FilterResult(doc, messages=messages)
            return messages
        finally:
            Resolver.local.docs.pop()

    def __apply_filter(self, filter_xml, doc, parser, **parms):
        transform = etree.XSLT(etree.fromstring(filter_xml, parser))
        return self.FilterResult(xml, error_log = transform.error_log)

    @staticmethod
    def get_text(node, default=None):
        """
        Assemble the concatenated text nodes for an element of the document.

        Note that the call to node.itertext() must include the wildcard
        string argument to specify that we want to avoid recursing into
        nodes which are not elements. Otherwise we will get the content
        of processing instructions, and how ugly would that be?!?

        Pass:
            node - element node from an XML document parsed by the lxml package
            default - what to return if the node is None

        Return:
            default if node is None; otherwise concatenated string node
            descendants
        """

        if node is None:
            return default
        return "".join(node.itertext("*"))

    @staticmethod
    def qname(ns, local):
        return "{{{}}}{}".format(ns, local)

    @staticmethod
    def id_from_title(title, cursor=None):
        title = title.replace("@@SLASH@@", "/").replace("+", " ")
        query = db.Query("document", "id")
        query.where(query.Condition("title", title))
        rows = query.execute(cursor).fetchall()
        if len(rows) > 1:
            raise Exception("Multiple documents with title %s" % title)
        return rows and rows[0][0] or None

    class FilterResult:
        def __init__(self, doc, **opts):
            self.doc = doc
            self.error_log = opts.get("error_log")
            self.messages = opts.get("messages")

    class Parser(etree.XMLParser):
        def __init__(self):
            etree.XMLParser.__init__(self)
            self.resolvers.add(Doc.Resolver("cdrutil"))
            self.resolvers.add(Doc.Resolver("cdr"))
            self.resolvers.add(Doc.Resolver("cdrx"))


class Local(threading.local):
    def __init__(self, **kw):
        self.docs = []
        self.__dict__.update(kw)


class Resolver(etree.Resolver):
    UNSAFE = re.compile(r"insert\s|update\s|delete\s|create\s|alter\s"
                        r"exec[(\s]|execute[(\s]")
    ID_KEY_STRIP = re.compile("[^A-Z0-9]+")
    local = Local()

    def resolve(self, url, pubid, context):
        self.doc = self.local.docs[-1]
        self.session = self.doc.session
        self.cursor = self.session.cursor
        self.url = urllib.parse.unquote(url.replace("+", " "))
        self.url = self.url.replace("@@PLUS@@", "+")
        if url == "cdrx:/last":
            return self.resolve_string("<empty/>", context)
        scheme, parms = self.url.split(":", 1)
        parms = parms.strip("/")
        if scheme in ("cdr", "cdrx"):
            return self.get_doc(parms, context)
        elif scheme == "cdrutil":
            return self.run_function(parms, context)
        raise Exception("unsupported url {!r}".format(self.url))

    def run_function(self, parms, context):
        function, args = parms, None
        if "/" in parms:
            function, args = parms.split("/", 1)
        if function == "docid":
            return self.get_doc_id(context)
        elif function == "sql-query":
            return self.run_sql_query(args, context)
        elif function == "get-pv-num":
            return self.get_pv_num(args, context)
        elif function == "denormalizeTerm":
            return self.get_term(args, context)
        elif function == "dedup-ids":
            return self.dedup_ids(args, context)
        elif function == "valid-zip":
            return self.valid_zip(args, context)
        error = "unsupported function {!r} in {!r}".format.(function, self.url)
        raise Exception(error)

    @classmethod
    def make_id_key(cls, id):
        return cls.ID_KEY_STRIP.sub("", id.upper())

    def valid_zip(self, args, context):
        """
        Look up a string in the `zipcode` table

        Return the base (first 5 digits) for the ZIP code, or an empty
        element if the zip code is not found
        """

        result = etree.Element("ValidZip")
        query = db.Query("zipcode", "zip")
        query.where(query.Condition("zip", args))
        row = query.execute(self.cursor).fetchone()
        if row and row[0]:
            result.text = str(row[0])[:5]
        return self.package_result(result, context)

    def dedup_ids(self, args, context):
        ids = []
        skip = set()
        if "~~" in args:
            primary, secondary = [i.split("~") for i in args.split("~~", 1)]
            for p in primary:
                skip.add(self.make_id_key(p))
            for s in secondary:
                key = self.make_id_key(s)
                if key and key not in skip:
                    ids.append(s)
                    skip.add(key)
        result = etree.Element("result")
        for i in ids:
            etree.SubElement(result, "id").text = i
        return self.package_result(result, context)

    def get_term(self, args, context):
        if "/" in args:
            doc_id = Doc.extract_id(args.split("/")[0])
            upcode = False
        else:
            doc_id = Doc.extract_id(args)
            upcode = True
        term = Term.get_term(self.session, doc_id)
        if term is None:
            term_xml = "<empty/>"
        else:
            term_xml = term.get_xml(upcode)
        return self.resolve_string(term_xml, context)

    def get_pv_num(self, args, context):
        doc = Doc(self.session, id=args)
        answer = etree.Element("PubVerNumber")
        answer.text = str(doc.last_publishable_version or 0)
        return self.package_result(answer, context)

    def run_sql_query(self, args, context):
        if "~" in args:
            query, values = args.split("~", 1)
            values = values.split("~")
        else:
            query, values = args, []
        if self.UNSAFE.search(query):
            raise Exception("query contains disallowed sql keywords")
        if query.count("?") != len(values):
            raise Exception("wrong number of sql query placeholder values")
        if db.Query.PLACEHOLDER != "?":
            query = query.replace("?", db.Query.PLACEHOLDER)
        self.cursor.execute(query, tuple(values))
        names = [col[0] for col in cursor.description]
        result = etree.Element("SqlResult")
        r = 1
        for values in cursor.fetchall():
            row = etree.SubElement(result, "row", id=str(r))
            for c, v in enumerate(values):
                col = etree.SubElement(row, "col", id=str(c), name=names[c])
                if v is None:
                    col.set("null", "Y")
                else:
                    col.text = str(v)
            r += 1
        return self.package_result(result, context)

    def get_doc_id(self, context):
        element = etree.Element("DocId")
        element.text = self.doc.cdr_id
        return self.package_result(element, context)

    def get_doc(self, parms, context):
        if parms.startswith("*"):
            if "/CdrCtl" in parms:
                element = self.doc.legacy_doc_control(filtering=True)
                return self.package_result(element, context)
            elif "/DocTitle" in parms:
                element = etree.Element("CdrDocTitle")
                element.text = self.doc.title
                return self.package_result(element, context)
            else:
                raise Exception("unsupported url {!r}".format(self.url))
        if parms.startswith("name:"):
            parms = parms[5:]
            if "/" in parms:
                title, version = parms.split("/", 1)
            else:
                title, version = parms, None
            doc_id = Doc.id_from_title(title, self.cursor)
            if not doc_id:
                return None
            doc = Doc(self.session, id=doc_id, version=version)
            if doc.doctype == "Filter":
                doc_xml = Filter.get_filter(doc_id, self.cursor).xml
                return self.resolve_string(doc_xml, context)
            parms = str(doc.id)
            if version:
                parms = "%d/%s" % (doc_id, version)
        else:
            doc_id, version = parms, None
            if "/" in parms:
                doc_id, version = parms.split("/", 1)
            if not doc_id:
                raise Exception("no document specified")
            doc = Doc(self.session, id=doc_id, version=version)
        return self.resolve_string(doc.xml, context)

    def package_result(self, result, context):
        result = etree.tostring(result, encoding="utf-8")
        return self.resolve_string(result, context)

    @staticmethod
    def escape_uri(context, arg=""):
        if isinstance(arg, (list, tuple)):
            arg = "".join(arg)
        try:
            return urllib.parse.quote(arg.replace("+", "@@PLUS@@"))
        except:
            print("cdr:escape_uri(%r)" % arg)
            raise

etree.FunctionNamespace(Doc.NS).update({"escape-uri": Resolver.escape_uri})

class Term:
    MAX_DEPTH = 15
    MAX_CACHE_AGE = datetime.timedelta(1)
    use_cache = 0
    terms = {}
    lock = threading.Lock()
    cache_started = None
    def __init__(self, session, doc_id, depth=0):
        self.session = session
        self.doc_id = doc_id
        self.cdr_id = "CDR%010d" % doc_id
        self.include = True
        self.parents = {}
        self.name = self.pdq_key = self.xml = self.full_xml = None
        try:
            doc = Doc(session, id=doc_id, version="lastp")
            self.name = doc.get_text(doc.root.find("PreferredName"))
            self.pdq_key = doc.get_text(doc.root.find("PdqKey"))
            for node in doc.root.findall("TermType/TermTypeName"):
                if doc.get_text(node) in ("Header term", "Obsolete term"):
                    self.include = False
                    break
            for node in root.findall("TermRelationship/ParentTerm/TermId"):
                self.get_parent(node, depth)
            if self.name and not depth:
                self.serialize()
        except Exception as e:
            if Doc.NO_PUBLISHABLE_VERSIONS in str(e):
                return
            raise
    def get_xml(self, with_upcoding=True):
        with Term.lock:
            if self.xml and self.full_xml:
                return with_upcoding and self.full_xml or self.xml
        self.serialize(need_locking=True)
        return with_upcoding and self.full_xml or self.xml
    def serialize(self, need_locking=False):
        term = etree.Element("Term", nsmap=Doc.NSMAP)
        term.set(Doc.CDR_REF, self.cdr_id)
        if self.pdq_key:
            term.set("PdqKey", "Term:" + self.pdq_key)
        etree.SubElement(term, "PreferredName").text = self.name
        xml = etree.tostring(term, encoding="utf-8")
        for doc_id in sorted(self.parents):
            parent = self.parents[doc_id]
            if parent is not None and parent.include and parent.name:
                child = etree.SubElement(term, "Term")
                child.set(Doc.CDR_REF, parent.cdr_id)
                if parent.pdq_key:
                    child.set("PdqKey", "Term:" + parent.pdq_key)
                etree.SubElement(child, "PreferredName").text = parent.name
        full_xml = etree.tostring(term, encoding="utf-8")
        if need_locking:
            with Term.lock:
                if not(self.xml and self.full_xml):
                    self.xml, self.full_xml = xml, full_xml
        else:
            self.xml, self.full_xml = xml, full_xml
    def get_parent(self, node, depth):
        try:
            doc_id = Doc.extract_id(node.get(Doc.CDR_REF))
        except:
            error = "No cdr:ref for parent of Term {}".format(self.cdr_id)
            raise Exception(failure)
        if doc_id not in self.parents:
            parent = Term.get_term(self.session, doc_id, depth + 1)
            if parent:
                self.parents.update(parent.parents)
                self.parents[doc_id] = parent
    @classmethod
    def get_term(cls, session, doc_id, depth=0):
        if depth > cls.MAX_DEPTH:
            error = "term hierarchy depth exceeded at CDR()".format(doc_id)
            raise Exception(error)
        with cls.lock:
            if cls.use_cache:
                cache_age = datetime.datetime.now() - cls.cache_started
                if cache_age > cls.MAX_CACHE_AGE:
                    while cls.use_cache:
                        cls.set_cache(False)
            if doc_id in cls.terms:
                return cls.terms[doc_id]
        term = cls(session, doc_id, depth)
        if not term.name:
            term = None
        with cls.lock:
            if cls.use_cache and doc_id not in cls.terms:
                cls.terms[doc_id] = term
        return term
    @classmethod
    def set_cache(cls, on=True):
        with cls.lock:
            previous_state = cls.use_cache > 0
            if on:
                cls.use_cache += 1
                if not previous_state:
                    cls.cache_started = datetime.datetime.now()
            else:
                cls.use_cache -= 1
                if cls.use_cache < 0:
                    cls.use_cache = 0
                if not cls.use_cache:
                    cls.terms = {}
            return previous_state

class Filter:
    MAX_FILTER_SET_DEPTH = 20
    SHELF_LIFE = 60
    NS = "http://www.w3.org/1999/XSL/Transform"
    filter_set_lock = threading.Lock()
    filter_lock = threading.Lock()
    filters = {}
    filter_sets = {}
    def __init__(self, doc_id, xml):
        self.doc_id, self.xml = doc_id, xml
        self.now = time.time()
    def stale(self):
        now = time.time()
        answer = (now - self.now) > self.SHELF_LIFE
        self.now = now
        return answer

    @classmethod
    def get_filter(cls, doc_id, cursor):
        """
        Fetch a possibly cached filter document

        If a filter hasn't been used in over `SHELF_LIFE` seconds,
        we get a fresh copy for the cache.

        We have to encode spaces in the filter titles used in the
        `include` and `import` directives in order to make the URLs
        valid.

        While in development, we are using modified filters stored
        in the `good_filters` table. When we go into production we'll
        apply the same modifications to the actual filters and restore
        the use of the `doc_version` view for fetching the filters.

        Pass:
          doc_id - integer for the filter's document ID
          cursor - database cursor for the current tier

        Return:
          `Filter` object
        """

        with cls.filter_lock:
            f = cls.filters.get(doc_id)
            if f is not None:
                if f.stale():
                    del cls.filters[doc_id]
                else:
                    return f
        #query = db.Query("doc_version", "xml", "num")
        #query.order("num DESC").limit(1)
        query = db.Query("good_filters", "xml")
        query.where(query.Condition("id", doc_id))
        #xml, ver = query.execute(cursor).fetchone()
        xml = query.execute(cursor).fetchone()[0]
        root = etree.fromstring(bytes(xml, "utf-8"))
        for name in ("import", "include"):
            for node in root.findall(Doc.qname(cls.NS, name)):
                href = node.get("href")
                node.set("href", href.replace(" ", "%20"))
        xml = etree.tostring(root.getroottree(), encoding="utf-8")
        with cls.filter_lock:
            if doc_id not in cls.filters:
                cls.filters[doc_id] = cls.Filter(doc_id, xml)
            return cls.filters[doc_id]

    @staticmethod
    def assemble_filters(self, cursor, *filters, **opts):
        """
        """
        filter_sequence = []
        for f in filter:
            if f.startswith("name:"):
                doc_id = Doc.id_from_title(f.split(":", 1)[1], cursor)
