#----------------------------------------------------------------------
#
# $Id: cdrcgi.py,v 1.3 2001-04-08 22:52:42 bkline Exp $
#
# Common routines for creating CDR web forms.
#
# $Log: not supported by cvs2svn $
# Revision 1.2  2001/03/27 21:15:27  bkline
# Paramaterized body background for HTML; added RCS Log keyword.
#
#----------------------------------------------------------------------

#----------------------------------------------------------------------
# Import external modules needed.
#----------------------------------------------------------------------
import cgi, cdr, sys, codecs

#----------------------------------------------------------------------
# Create some useful constants.
#----------------------------------------------------------------------
USERNAME = "UserName"
PASSWORD = "Password"
SESSION  = "Session"
REQUEST  = "Request"
DOCID    = "DocId"
FILTER   = "Filter"
FORMBG   = '/images/back.jpg'
HEADER   = """<!DOCTYPE HTML PUBLIC '-//IETF//DTD HTML//EN'>
<HTML>
 <HEAD>
  <TITLE>%s</TITLE>
 </HEAD>
 <BASEFONT FACE='Arial, Helvetica, sans-serif'>
 <LINK REL='STYLESHEET' HREF='/stylesheets/dataform.css'>
 <BODY BACKGROUND='%s' BGCOLOR='lightgrey'>
  <FORM ACTION='/cgi-bin/cdr/%s' METHOD='POST'>
   <TABLE WIDTH='100%%' CELLSPACING='0' CELLPADDING='0' BORDER='0'>
    <TR>
     <TH NOWRAP BGCOLOR='silver' ALIGN='left' BACKGROUND='/images/nav1.jpg'>
      <FONT SIZE='6' COLOR='white'>&nbsp;%s</FONT>
     </TH>
"""
B_CELL = """\
     <TD BGCOLOR='silver'
         VALIGN='middle'
         ALIGN='right'
         WIDTH='100%'
         BACKGROUND='/images/nav1.jpg'>
"""
BUTTON = """\
      <INPUT TYPE='submit' NAME='%s' VALUE='%s'>&nbsp;
"""
SUBBANNER = """\
    </TR>
    <TR>
     <TD BGCOLOR='#FFFFCC' COLSPAN='3'>
      <FONT SIZE='-1' COLOR='navy'>&nbsp;%s<BR></FONT>
     </TD>
    </TR>
   </TABLE>
   <BR>
   <BR>
"""

#----------------------------------------------------------------------
# Display the header for a CDR web form.
#----------------------------------------------------------------------
def header(title, banner, subBanner, script = '', buttons = None, bkgd = ''):
    html = HEADER % (title, FORMBG, script, banner)
    if buttons:
        html = html + B_CELL
        for button in buttons:
            if button == "Load":
                html = html + "      <INPUT NAME='DocId' SIZE='14'>&nbsp;\n"
            html = html + BUTTON % (REQUEST, button)
        html = html + "     </TD>\n"
    html = html + SUBBANNER % subBanner
    return html

#----------------------------------------------------------------------
# Get a session ID based on current form field values.
#----------------------------------------------------------------------
def getSession(fields):

    # If we already have a Session field value, use it.
    if fields.has_key(SESSION):
        session = fields[SESSION].value
        if len(session) > 0:
            return session

    # Check for missing fields.
    if not fields.has_key(USERNAME) or not fields.has_key(PASSWORD):
        return None
    userId = fields[USERNAME].value
    password = fields[PASSWORD].value
    if len(userId) == 0 or len(password) == 0:
        return None

    # Log on to the CDR Server.
    session = cdr.login(userId, password)
    if session.find("<Err") >= 0: return None
    else:                         return session

#----------------------------------------------------------------------
# Get the name of the submitted request.
#----------------------------------------------------------------------
def getRequest(fields):

    # Make sure the request field exists.
    if not fields.has_key(REQUEST): return None
    else:                           return fields[REQUEST].value

#----------------------------------------------------------------------
# Send an HTML page back to the client.
#----------------------------------------------------------------------
def sendPage(page):
    print "Content-type: text/html\n\n" + page

#----------------------------------------------------------------------
# Emit an HTML page containing an error message and exit.
#----------------------------------------------------------------------
def bail(message, banner = "CDR Web Interface"):
    page = header("CDR Error", banner, "An error has occured", "", [])
    page = page + "<H2>%s</H2></FORM></BODY></HTML>" % message
    sendPage(page)
    sys.exit(0)

#----------------------------------------------------------------------
# Encode XML for transfer to the CDR Server using utf-8.
#----------------------------------------------------------------------
def encode(xml): return unicode(xml, 'latin-1').encode('utf-8')

#----------------------------------------------------------------------
# Convert CDR Server's XML from utf-8 to latin-1 encoding.
#----------------------------------------------------------------------
def decode(xml): return unicode(xml, 'utf-8').encode('latin-1')
