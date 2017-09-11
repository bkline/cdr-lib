#----------------------------------------------------------------------
# Rewrite of cdrdb.py to avoid dependencies and odd behavior of ADO/DB.
#----------------------------------------------------------------------
import pymssql
import time
import os

# Provides name resolution for different hosts
import cdrutil

# Provides lookup of database passwords from centralized file.
import cdrpw

# Setting up the propper database source
# --------------------------------------
# Default
CBIIT_HOSTING = True

DEFAULT_TIMEOUT = 120

# Accounting for alternate tiers later, see def connect()
h = cdrutil.AppHost(cdrutil.getEnvironment(), cdrutil.getTier())
if h.org == 'OCE':
    CDR_DB_SERVER = 'localhost'
    CBIIT_HOSTING = False
else:
    CDR_DB_SERVER = h.host['DBWIN'][0]

# Look in the environment for override of default location of CDR database.
_cdr_db_server = os.environ.get('CDR_DB_SERVER')
if _cdr_db_server:
    CDR_DB_SERVER = _cdr_db_server

# Logging support.  Set LOGFILE to log file pathname to enable logging.
LOGFILE = os.environ.get('CDR_DB_LOGFILE') or None
def debugLog(sql = None, params = None, what = "SQL Query"):
    if LOGFILE:
        import datetime
        now = datetime.datetime.now()
        now = "%d-%02d-%-2d %02d:%02d:%02d.%03d" % (now.year, now.month,
                                                    now.day, now.hour,
                                                    now.minute, now.second,
                                                    now.microsecond / 1000)
        try:
            fp = open(LOGFILE, 'a')
            fp.write("%s: %s\n" % (now, what))
            if sql:
                fp.write("%s\nParameters:\n%s\n" % (sql, params))
            fp.close()
        except:
            pass

#----------------------------------------------------------------------
# Connect to the CDR using known login account.
#----------------------------------------------------------------------
def connect(user='cdr', dataSource=CDR_DB_SERVER, db='cdr',
            timeout=None, as_dict=False):
    """
    Factory for creating a connection to the database.  Returns a
    Connection Object. It takes a number of parameters which are
    database dependent.  This implementation expects only the user
    name for the database login account.  The 'cdr' account is used
    for standard database activity for which the permission to alter
    data is required.  The 'CdrGuest' account has read-only access
    to the CDR data.
    """

    global CBIIT_HOSTING
    global h
    tier = h.tier
    if dataSource != CDR_DB_SERVER:
        # Default server name established above
        # If it's anything else, establish the network name here
        hostInfo = h.getTierHostNames(dataSource, 'DBWIN')
        if hostInfo:
            dataSource = hostInfo.qname
            tier = hostInfo.tier

    if CBIIT_HOSTING:
        ports = {
            "PROD": 55733,
            "STAGE": 55459,
            "QA": 53100,
            "DEV": 52400
        }
        port = ports.get(tier, 52400)
        if user.upper() == "CDR":
            user = "cdrsqlaccount"
    else:
        port = 32408
    password = cdrpw.password(h.org, tier, db, user)
    if timeout is None:
        timeout = DEFAULT_TIMEOUT
    return pymssql.connect(server=dataSource, port=port, user=user,
                           password=password, database=db, timeout=timeout,
                           as_dict=as_dict)

class Query:

    """
    Builder for SQL select queries.

    Example usage:

        query = cdrdb.Query('t1 a', 'a.title', 'b.name AS "Type"')
        query.join('t2 b', 'b.id = a.t2')
        query.where(query.Condition('b.name', ('Foo', 'Bar'), 'IN'))

        # To see the generated SQL
        print query

        # To execute and cleanup
        cursor = query.execute()
        rows = cursor.fetchall()
        cursor.close()

        # Or alternatively if closing the cursor doesn't matter
        rows = query.execute().fetchall()
    """

    def __init__(self, table, *columns):
        """
        Initializes a SQL query builder

        Passed:

            table           table name with possible alias
            columns         one or more column names to be selected,
                            qualified with alias if necessary; a column
                            can be an expression
        """
        self._table = table
        self._columns = columns
        self._joins = []
        self._where = []
        self._group = []
        self._having = []
        self._order = []
        self._parms = []
        self._unions = []
        self._timeout = DEFAULT_TIMEOUT
        self._alias = None
        self._into = None
        self._cursor = None
        self._limit = None
        self._unique = False
        self._str = None
        self._outer = False
        self._as_dict = False

    def timeout(self, value):
        """
        Override the default timeout of 120 seconds with a new value.
        """
        self._timeout = int(value)
        return self

    def join(self, table, *conditions):
        """
        Join to an additional table (or view)

        Each condition can be a simple string (e.g., 't.id = d.doc_type')
        or a more complicated Condition or Or object.

        If you don't supply at least one condition, you might be
        unpleasantly surprised by the results. :-)
        """
        self._joins.append(Query.Join(table, False, *conditions))
        self._str = None
        return self

    def outer(self, table, *conditions):
        """
        Create a left outer join

        Sets the self._outer flag so the formatter knows to add
        extra left padding to the query as needed.  Otherwise works
        the same as the join() method.
        """
        self._joins.append(Query.Join(table, True, *conditions))
        self._outer = True
        self._str = None
        return self

    def where(self, condition):
        """
        Adds a condition for the query's WHERE clause

        A condition can be a simple string (e.g., 't.id = d.doc_type')
        or a more complicated Condition or Or object.
        """
        self._where.append(condition)
        self._str = None
        return self

    def group(self, *columns):
        """
        Adds one or more columns to be used in the query's GROUP BY clause

        Example usage:
            query.group('d.id', 'd.title')
        """
        for column in columns:
            Query._add_sequence_or_value(column, self._group)
        self._str = None
        return self

    def having(self, condition):
        """
        Adds a condition to the query's HAVING clause

        A condition can be a simple string (e.g., 't.id = d.doc_type')
        or a more complicated Condition or Or object.
        """
        self._having.append(condition)
        self._str = None
        return self

    def union(self, query):
        """
        Add a query to be UNIONed with this one.

        Use this when you want to apply the ORDER BY clause to the UNIONed
        queries as a whole.  Make sure only this query has an ORDER set.
        If you need each component query to maintain its own internal order,
        construct and serialize each separately, and assemble them by hand.
        For example:

        q1 = cdrdb.Query(...).join.(...).where(...).order(...)
        q2 = cdrdb.Query(...).join.(...).where(...).order(...)
        union = cdrdb.Query(q1, "*").union(cdrdb.Query(q2, "*"))
        """
        self._unions.append(query)
        self._str = None
        return self

    def order(self, *columns):
        """
        Add the column(s) to be used to sort the results

        Example usage:
            query.order('doc_type.name', 'version.dt DESC')
        """
        temp = []
        for column in columns:
            Query._add_sequence_or_value(str(column), temp)
        for column in temp:
            column = column.strip()
            words = column.split()
            if len(words) > 2:
                raise Exception("invalid order column %s" % repr(column))
            if len(words) == 2 and words[1].upper() not in ("ASC", "DESC"):
                raise Exception("invalid order column %s" % repr(column))
            self._order.append(" ".join(words))
        self._str = None
        return self

    def limit(self, limit):
        """
        Sets maximum number of rows to return
        """
        if type(limit) is not int:
            raise Exception("limit must be integer")
        self._limit = limit
        self._str = None
        return self

    def unique(self):
        """
        Requests that duplicate rows be eliminated
        """
        self._unique = True
        self._str = None
        return self

    def cursor(self, cursor):
        """
        Pass in a cursor to be used for the query.
        """
        self._cursor = cursor
        return self

    def execute(self, cursor=None, timeout=None, as_dict=None):
        """
        Assemble and execute the SQL query, returning the cursor object

        As with the Miranda rule, if you do not supply a cursor,
        one will be provided for you.

        Note that the temporary 'sql' variable is assigned before
        invoking the cursor's execute() method, to make sure that
        the _parms sequence has been constructed.
        """
        if not cursor:
            if not timeout:
                timeout = self._timeout
            if as_dict is None:
                as_dict = self._as_dict
            conn = connect("CdrGuest", timeout=timeout, as_dict=as_dict)
            cursor = conn.cursor()
        sql = str(self)
        cursor.execute(sql, tuple(self._parms))
        return cursor

    def alias(self, alias):
        """
        Assigns an alias for a query so that it can be used as a virtual
        table as the target of a FROM clause:

            SELECT xxx.this, xxx.that, yyy.other
              FROM (
                  SELECT this, that
                    FROM whatever
              ) AS xxx

        Example usage:

            q1 = cdrdb.Query('whatever', 'this', 'that').alias('xxx')
            q2 = cdrdb.Query(q1, 'xxx.this', 'xxx.that', 'yyy.other')
            q2.join('other_table yyy', ...)
        """
        self._alias = alias
        self._str = None
        return self

    def parms(self):
        """
        Accessor method for query parameters

        Return the list of parameters to be passed to the database
        engine for the execution of the query.  Will be in the
        correct order, matching the position of the corresponding
        placeholders in the query string.
        """

        # Make sure the parameters have been assembled.
        if self._str is None:
            dummy = str(self)
        return self._parms

    def _align(self, keyword, rest=""):
        """
        Internal helper method to make the SQL query easier to read
        """
        keyword = " " * self._indent + keyword
        return "%s %s" % (keyword[-self._indent:], rest)

    def into(self, name):
        """
        Specify name of table to be created by this query

        Prefix the name with the octothorpe character ('#') to create
        a temporary table.
        """
        self._into = name
        self._str = None
        return self

    def log(self, **parms):
        import cdr
        logfile = parms.get("logfile", cdr.DEFAULT_LOGDIR + "/query.log")
        label = parms.get("label", "QUERY")
        output = u"%s:\n%s" % (label, self)
        if self._parms:
            parms = ["PARAMETERS:"] + [repr(p) for p in self._parms]
            output += "\n" + u"\n\t".join(parms)
        cdr.logwrite(output, logfile)

    def __str__(self):
        """
        Assemble the query for execution or logging.

        The format of the query string is arranged to make reading
        by a human easier.  The assembled query is cached.

        A side effect of a call to this method is that the sequence
        of all parameters to be passed to the database engine for
        execution of the query is constructed as the '_parms' member.
        """

        # If our cached string is not stale, use it.
        if self._str:
            return self._str

        # Start with a fresh paramater list.
        self._parms = []

        # Start the select statement, and calculate needed left padding.
        select = "SELECT"
        if self._unique:
            select += " DISTINCT"
        if self._limit is not None:
            select += " TOP %d" % self._limit
        self._indent = len(select)
        for attribute, keywords in (
            (self._order, "ORDER BY"),
            (self._outer, "LEFT OUTER JOIN"),
            (self._group, "GROUP BY")):
            if attribute:
                needed = len(keywords) - self._indent
                if needed > 0:
                    self._indent += needed
        query = [self._align(select, ", ".join(self._columns))]

        # Add clause to store results in a new table if requested.
        if self._into:
            query.append(self._align("INTO", self._into))

        # Is the base table itself a query?
        if isinstance(self._table, Query):

            # Make sure it has an alias.
            alias = self._table._alias
            if not alias:
                raise Exception("Virtual tables must have an alias")

            # SQL Server won't accept placeholders here.
            sql = str(self._table)
            if self._table._parms:
                raise Exception("Placeholders not allowed in virtual table")

            # Add the indented query in parentheses.
            query.append(self._align("FROM", "("))
            query.append(Query.indent("%s) %s" % (self._table, alias)))

        # No: just a plain vanilla FROM clause.
        else:
            query.append(self._align("FROM", self._table))

        # Add JOIN clauses for any additional tables used for the query.
        for join in self._joins:
            self._serialize_join(query, join)

        # Add the conditions used to restrict the set of results.
        keyword = "WHERE"
        for condition in self._where:
            self._serialize_condition(query, keyword, condition)
            keyword = "AND"

        # If the query uses aggregates, specify column for the grouping.
        if self._group:
            query.append(self._align("GROUP BY", ", ".join(self._group)))

        # Specify any restrictions on the results based on aggregations.
        if self._having:
            keyword = "HAVING"
            for condition in self._having:
                self._serialize_condition(query, keyword, condition)
                keyword = "AND"

        # Add any queries to be spliced to this one
        for union in self._unions:
            query.append(self._align("UNION"))
            query.append(str(union))

        # Specify the sorting of the result set if requested.
        if self._order:
            query.append(self._align("ORDER BY", ", ".join(self._order)))

        # Assemble everything and cache the results.
        self._str = "\n".join(query)

        # Give the caller the resulting SQL.
        return self._str

    def _serialize_or_set(self, query, keyword, or_set, prefix, suffix):
        """
        Internal helper method for building the query string

        This method has four responsibilities:
         1. Wrap the set of OR conditions in properly balanced parentheses
         2. Connect the conditions with the "OR" keyword
         3. Hand of serialization of each condition to _serialize_condition
         4. Connect nested sequences of conditions with the "AND" keyword
        """
        open_paren = "(" + prefix
        close_paren = ""
        for i, condition in enumerate(or_set.conditions):
            last_or = (i == len(or_set.conditions) - 1)
            if type(condition) in (tuple, list):
                for j, c in enumerate(condition):
                    if last_or and j == len(condition) - 1:
                        close_paren = suffix + ")"
                    self._serialize_condition(query, keyword, c,
                                              open_paren, close_paren)
                    keyword = "AND"
                    open_paren = ""
            else:
                if last_or:
                    close_paren = suffix + ")"
                self._serialize_condition(query, keyword, condition,
                                          open_paren, close_paren)
            keyword = "OR"
            open_paren = ""

    def _serialize_condition(self, query, keyword, condition, prefix="",
                             suffix=""):
        """
        Internal helper method for building the query string.
        """

        # Hand off the work for an Or set
        if isinstance(condition, Query.Or):
            self._serialize_or_set(query, keyword, condition, prefix, suffix)
            return

        # Handle the easy cases.
        if not isinstance(condition, Query.Condition):
            query.append(self._align(keyword, prefix + condition + suffix))
            return

        # Start the test string.
        test = "%s %s%s" % (condition.column, prefix, condition.test)

        # Handle a nested query.
        if isinstance(condition.value, Query):

            # Serialize the nested query.
            nested = condition.value
            alias = nested._alias and (" %s" % nested._alias) or ""
            serialized = "%s)%s%s" % (nested, alias, suffix)

            # Finish the condition.
            query.append(self._align(keyword, test + " ("))
            query.append(Query.indent(serialized))
            self._parms += nested._parms

        # Handle a sequence of values.
        elif condition.test.upper() in ("IN", "NOT IN"):

            # Make sure we have a list.
            values = condition.value
            if type(values) not in (list, tuple):
                values = [values]

            # Must have at least one value.
            if not values:
                raise Exception("%s test with no values" %
                                repr(condition.test.upper()))

            # Add the placeholders.
            test += " (%s)" % ", ".join(["%s"] * len(values))

            # Plug in the condition to the query string.
            query.append(self._align(keyword, test + suffix))

            # Add the parameters.
            self._parms += values

        # Last case: single value test.
        else:
            if type(condition.value) in (list, tuple):
                raise Exception("Unexpected sequence of values")
            query.append(self._align(keyword, "%s %%s%s" % (test, suffix)))
            self._parms.append(condition.value)

    def _serialize_join(self, query, join):
        """
        Helper function for building the query string.
        """
        keyword = join.outer and "LEFT OUTER JOIN" or "JOIN"

        # Is this 'table' being constructed on the fly?
        if isinstance(join.table, Query):

            # Make sure it has been provided with an alias.
            alias = join.table._alias
            if not alias:
                raise Exception("resultset expression without alias")

            # SQL Server won't accept placeholders here.
            if join.table.parms():
                raise Exception("Placeholders not allowed in joined "
                                "resultset expression")

            # Add the table expression indented and in parentheses.
            query.append(self._align(keyword, "("))
            query.append(Query.indent("%s) %s" % (join.table, alias)))

        # No, just a named table.
        else:
            query.append(self._align(keyword, join.table))

        # Add the conditions for the join.
        keyword = "ON"
        for condition in join.conditions:
            self._serialize_condition(query, keyword, condition)
            keyword = "AND"

    @staticmethod
    def indent(block, n=4):
        """
        Indent a block containing one or more lines by a number of spaces
        """
        if isinstance(block, Query):
            block = str(block)
        padding = " " * n
        end = block.endswith("\n") and "\n" or ""
        lines = block.splitlines()
        return "\n".join(["%s%s" % (padding, line) for line in lines]) + end

    @staticmethod
    def _add_sequence_or_value(to_be_added, collection):
        if type(to_be_added) is list:
            collection += to_be_added
        elif type(to_be_added) is tuple:
            collection += list(to_be_added)
        else:
            collection.append(to_be_added)

    class Condition:
        """
        Test of a value (typically, but not necessarily a column; could
        also be an expression, or even a constant value), against a
        second value (which can be a single value, or a query which
        returns a single value, or a sequence of values in the case
        of an "IN" or "NOT IN" test).
        """

        def __init__(self, col, val, test="="):
            self.column = col
            self.value = val
            self.test = test
    C = Condition

    class Or:
        """
        Represents a set of one or more conditions the satisfaction of
        any one of which will be considered as satisfying the entire
        set.

        Simple example:

            query = cdrdb.Query('t1', 'c1', 'c2')
            first_test = 'c1 < 42'
            second_test = query.Condition('c2', get_some_values(), 'IN')
            query.where(query.Or(first_test, second_test))
        """

        def __init__(self, *conditions):
            """
            Accepts one or more conditions, each of which can be either
            a string containing a SQL expression, or a Query.Condition
            object.  Any argument can also be a sequence of SQL expressions
            and/or Query.Condition or Query.Or objects, which will all be
            ANDed together as a single unit to be ORed against the tests
            represented by the other arguments to the constructor.  There
            is no limit (other than that imposed by the computing resources
            on the client and server machines) to the level of nesting
            supported for combinations of AND and OR condition sets.
            """
            self.conditions = conditions

    class Join:
        """
        Used internally to represent a SQL JOIN clause
        """

        def __init__(self, table, outer, *conditions):
            self.table = table
            self.outer = outer
            self.conditions = []
            for condition in conditions:
                Query._add_sequence_or_value(condition, self.conditions)

    @staticmethod
    def report(test_number, query, outcome):
        print "Test %2d...%s" % (test_number, outcome and "passed" or "failed")
        f = open("Query.tests", "a")
        banner = (" Test %d " % test_number).center(70, "=")
        f.write("%s\n" % banner)
        f.write("%s\n" % query)
        if query._parms:
            f.write("%s\n" % ("-" * 70))
            for p in query._parms:
                f.write("%s\n" % repr(p))
        f.close()

    @staticmethod
    def test():
        """
        Run tests to check the health of the Query class.
        """

        # Convenience aliases
        Q = Query
        C = Query.Condition
        R = Query.report

        # Create some test tables.
        c = connect("CdrGuest").cursor()
        c.execute("CREATE TABLE #t1 (i INT, n VARCHAR(32))")
        c.execute("CREATE TABLE #t2 (i INT, n VARCHAR(32))")
        c.execute("INSERT INTO #t1 VALUES(42, 'Alan')")
        c.execute("INSERT INTO #t1 VALUES(43, 'Bob')")
        c.execute("INSERT INTO #t1 VALUES(44, 'Volker')")
        c.execute("INSERT INTO #t1 VALUES(45, 'Elmer')")
        c.execute("INSERT INTO #t2 VALUES(42, 'biology')")
        c.execute("INSERT INTO #t2 VALUES(42, 'aviation')")
        c.execute("INSERT INTO #t2 VALUES(42, 'history')")
        c.execute("INSERT INTO #t2 VALUES(43, 'music')")
        c.execute("INSERT INTO #t2 VALUES(43, 'cycling')")
        c.execute("INSERT INTO #t2 VALUES(44, 'physics')")
        c.execute("INSERT INTO #t2 VALUES(44, 'volleyball')")
        c.execute("INSERT INTO #t2 VALUES(44, 'tennis')")

        # Test 1: ORDER BY with TOP.
        q = Q("#t1", "i").limit(1).order("1 DESC")
        r = q.execute(c, timeout=10).fetchall()
        R(1, q, r == [(45,)])

        # Test 2: JOIN with COUNT.
        q = Q("#t1", "COUNT(DISTINCT #t1.i)").join("#t2", "#t2.i = #t1.i")
        r = q.execute(c).fetchall()
        R(2, q, r == [(3,)])

        # Test 3: GROUP BY and HAVING.
        q = Q("#t2", "i", "COUNT(*)").group("i").having("COUNT(*) > 2")
        r = set([row[0] for row in q.execute(c).fetchall()])
        R(3, q, r == set([42, 44]))

        # Test 4: LEFT OUTER JOIN with IS NULL.
        q = Q("#t1 a", "a.i", "b.n").outer("#t2 b", "b.i = a.i")
        r = q.where("b.n IS NULL").execute(c).fetchall()
        R(4, q, r == [(45, None,)])

        # Test 5: NESTED ORs and ANDs.
        q = Q("#t1 a", "a.n").join("#t2 b", "b.i = a.i").unique()
        q.where(Q.Or("a.n LIKE 'E%'", ("a.i < 44", "b.n LIKE '%o%'")))
        q.where("a.n <> 'Volker'")
        r = q.execute(c).fetchall()
        R(5, q, r == [('Alan',)])

        # Test 6: Condition object with placeholders.
        v = ('biology', 'physics')
        q = Q("#t1 a", "a.n").join("#t2 b", "b.i = a.i").unique().order(1)
        q.where(C("b.n", v, "IN"))
        q.timeout(5)
        r = [row[0] for row in q.execute(c).fetchall()]
        R(6, q, r == ['Alan', 'Volker'])

        # Test 7: UNION.
        q = Q("#t1", "n").where("i > 44")
        q.union(Q("#t1", "n").where("i < 43"))
        r = [r[0] for r in q.order(1).execute(c).fetchall()]
        R(7, q, r == ["Alan", "Elmer"])

        # Test 8: INTO.
        Q("#t1", "*").into("#t3").execute(c)
        q = Q("#t3", "n").order(1)
        r = [r[0] for r in q.execute(c).fetchall()]
        R(8, q, r == ["Alan", "Bob", "Elmer", "Volker"])

        # Test 9: nested query.
        q = Q("#t1", "n")
        q.where(C("i", Q("#t2", "i").unique(), "NOT IN"))
        r = q.execute(c).fetchall()
        R(9, q, r == [("Elmer",)])

        # Test 10: dictionary results.
        c = connect("CdrGuest", as_dict=True).cursor()
        c.execute("CREATE TABLE #t1 (i INT, n VARCHAR(32))")
        c.execute("CREATE TABLE #t2 (i INT, n VARCHAR(32))")
        c.execute("INSERT INTO #t1 VALUES(42, 'Alan')")
        c.execute("INSERT INTO #t1 VALUES(43, 'Bob')")
        c.execute("INSERT INTO #t1 VALUES(44, 'Volker')")
        c.execute("INSERT INTO #t1 VALUES(45, 'Elmer')")
        c.execute("INSERT INTO #t2 VALUES(42, 'biology')")
        c.execute("INSERT INTO #t2 VALUES(42, 'aviation')")
        c.execute("INSERT INTO #t2 VALUES(42, 'history')")
        c.execute("INSERT INTO #t2 VALUES(43, 'music')")
        c.execute("INSERT INTO #t2 VALUES(43, 'cycling')")
        c.execute("INSERT INTO #t2 VALUES(44, 'physics')")
        c.execute("INSERT INTO #t2 VALUES(44, 'volleyball')")
        c.execute("INSERT INTO #t2 VALUES(44, 'tennis')")
        q = Q("#t1", "n")
        q.where(C("i", Q("#t2", "i").unique(), "NOT IN"))
        r = q.execute(c).fetchall()
        R(10, q, r == [{"n": "Elmer"}])