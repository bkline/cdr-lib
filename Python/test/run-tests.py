#!/usr/bin/env python3

import os
import unittest
import cdr
from cdrapi.users import Session
from cdrapi import db

class Tests(unittest.TestCase):
    USERNAME = "tester"
    TIER = os.environ.get("TEST_CDR_TIER")

    def setUp(self):
        opts = dict(comment="unit testing", tier=self.TIER)
        Tests.session = Session.create_session(self.USERNAME, **opts).name

    def tearDown(self):
        cdr.logout(self.session, tier=self.TIER)

""" """
class _01SessionTests(Tests):
    def test_01_login(self):
        opts = dict(comment="unit testing", tier=self.TIER)
        session = Session.create_session(self.USERNAME, **opts)
        _01SessionTests.session2 = session
        self.assertEqual(len(_01SessionTests.session2.name), 32)
        self.assertTrue(_01SessionTests.session2.active)
    def test_02_logout(self):
        self.assertTrue(_01SessionTests.session2.active)
        self.assertIsNone(cdr.logout(_01SessionTests.session2, tier=self.TIER))
        self.assertFalse(_01SessionTests.session2.active)
    def test_03_dup_session(self):
        session = cdr.dupSession(self.session, tier=self.TIER)
        if isinstance(session, Session):
            session = session.name
        self.assertEqual(len(session), 32)
        self.assertEqual(len(self.session), 32)
        self.assertNotEqual(session, self.session)
        self.assertIsNone(cdr.logout(session, tier=self.TIER))

class _02UserPermissionTests(Tests):
    def delete_action(self, name, **opts):
        disable = "ALTER TABLE {} NOCHECK CONSTRAINT ALL"
        enable = "ALTER TABLE {} WITH CHECK CHECK CONSTRAINT ALL"
        conn = db.connect(tier=opts.get("tier"))
        cursor = conn.cursor()
        fk_tables = (
            "audit_trail",
            "audit_trail_added_action",
            "external_map_usage",
            "grp_action"
        )
        try:
            for table in fk_tables:
                cursor.execute(disable.format(table))
            conn.commit()
            cdr.delAction(self.session, name, **opts)
        finally:
            for table in fk_tables:
                cursor.execute(enable.format(table))
            conn.commit()

    def test_01_can_do(self):
        opts = dict(tier=self.TIER)
        self.assertTrue(cdr.canDo("guest", "ADD DOCUMENT", "xxtest", **opts))
        self.assertFalse(cdr.canDo("guest", "ADD DOCUMENT", "Summary", **opts))
        self.assertTrue(cdr.canDo("guest", "LIST DOCTYPES", **opts))
        self.assertFalse(cdr.canDo("guest", "LIST USERS", **opts))
    def test_02_add_action(self):
        opts = dict(tier=self.TIER)
        actions = cdr.getActions(self.session, **opts)
        for name in "gimte", "dada":
            if name in actions:
                self.delete_action(name, **opts)
        action = cdr.Action("dada", "Y", "gimte")
        self.assertIsNone(cdr.putAction(self.session, None, action, **opts))
    def test_03_mod_action(self):
        opts = dict(tier=self.TIER)
        action = cdr.getAction(self.session, "dada", **opts)
        action.name = "gimte"
        action.comment = "dada"
        action.doctype_specific = "N"
        self.assertIsNone(cdr.putAction(self.session, "dada", action, **opts))
        action = cdr.getAction(self.session, "ADD DOCUMENT", **opts)
        action.doctype_specific = "N"
        with self.assertRaises(Exception):
            cdr.putAction(self.session, "ADD DOCUMENT", action, **opts)
    def test_04_get_action(self):
        opts = dict(tier=self.TIER)
        action = cdr.getAction(self.session, "gimte", **opts)
        self.assertEqual(action.comment, "dada")
        self.assertEqual(action.doctype_specific, "N")
    def test_05_del_action(self):
        opts = dict(tier=self.TIER)
        self.assertIsNone(self.delete_action("gimte", **opts))
    def test_06_get_actions(self):
        opts = dict(tier=self.TIER)
        actions = cdr.getActions(self.session, **opts)
        self.assertEqual(actions["ADD DOCUMENT"], "Y")
        self.assertEqual(actions["LIST USERS"], "N")

class _03GroupTests(Tests):
    NAME = "Test Group"
    NEWNAME = "Test Group (MOD)"
    USERS = ["tester"]
    NEWUSERS = ["tester", "CdrGuest"]
    def test_01_add_group(self):
        opts = dict(tier=self.TIER)
        groups = cdr.getGroups(self.session, **opts)
        for name in self.NAME, self.NEWNAME:
            if name in groups:
                cdr.delGroup(self.session, name, **opts)
        name = self.NAME
        users = self.USERS
        actions = {"LIST USERS": ""}
        args = dict(name=name, comment="dada", users=users, actions=actions)
        group = cdr.Group(**args)
        group.actions = {"LIST USERS": ""}
        self.assertIsNone(cdr.putGroup(self.session, None, group, **opts))
    def test_02_get_group(self):
        group = cdr.getGroup(self.session, self.NAME, tier=self.TIER)
        self.assertIsNotNone(group)
        self.assertEqual(set(group.users), set(self.USERS))
        self.assertEqual(group.comment, "dada")
    def test_03_mod_group(self):
        opts = dict(tier=self.TIER)
        group = cdr.getGroup(self.session, self.NAME, **opts)
        group.name = self.NEWNAME
        group.users = self.NEWUSERS
        self.assertIsNone(cdr.putGroup(self.session, self.NAME, group, **opts))
        group = cdr.getGroup(self.session, self.NEWNAME, **opts)
        self.assertEqual(set(group.users), set(self.NEWUSERS))
    def test_04_get_groups(self):
        opts = dict(tier=self.TIER)
        self.assertIn(self.NEWNAME, cdr.getGroups(self.session, **opts))
    def test_05_del_group(self):
        opts = dict(tier=self.TIER)
        self.assertIsNone(cdr.delGroup(self.session, self.NEWNAME, **opts))
""" """
class _05DocTests(Tests):
    def __make_doc(self, doc_filename, doc_id=None):
        directory = os.path.dirname(os.path.realpath(__file__))
        with open("{}/{}".format(directory, doc_filename), "rb") as fp:
            xml = fp.read()
        ctrl = {"DocTitle": "test doc"}
        return cdr.makeCdrDoc(xml, "xxtest", doc_id, ctrl)
    def __get_opts(self, doc):
        return {
            "doc": doc,
            "comment": "sauve qui peut",
            "reason": "pourquoi pas?",
            "val": "Y",
            "ver": "Y",
            "show_warnings": True,
            "tier": self.TIER
        }
    def test_01_add_doc(self):
        doc = self.__make_doc("001.xml")
        response = cdr.addDoc(self.session, **self.__get_opts(doc))
        #print(response)
        doc_id, errors = response
        self.assertTrue(b"not accepted by the pattern" in errors)
        self.assertTrue(doc_id.startswith("CDR"))
        CDRTestData.doc_id = doc_id
    def test_02_get_doc(self):
        opts = dict(tier=self.TIER, getObject=True)
        doc = cdr.getDoc(self.session, 5000, **opts)
        self.assertEqual(doc.type, "Person")
        doc = cdr.getDoc(self.session, CDRTestData.doc_id, **opts)
        CDRTestData.doc = doc
        self.assertEqual(doc.type, "xxtest")
    def test_03_rep_doc(self):
        doc = CDRTestData.doc
        directory = os.path.dirname(os.path.realpath(__file__))
        with open("{}/{}".format(directory, "002.xml"), "rb") as fp:
            doc.xml = fp.read()
        opts = self.__get_opts(str(doc))
        opts["publishable"] = "Y"
        response = cdr.repDoc(self.session, **opts)
        #print(response)
        doc_id, errors = response
        self.assertEqual(doc_id, CDRTestData.doc_id)
        self.assertTrue(not errors)
    def test_04_filter(self):
        filt = ["set:QC Summary Set"]
        result = cdr.filterDoc(self.session, filt, 62902, tier=self.TIER)
        self.assertTrue(b"small intestine cancer" in result[0])
    def test_05_val_doc(self):
        opts = dict(doc_id=5000, locators=True, tier=self.TIER)
        result = cdr.valDoc(self.session, "Person", **opts).decode("utf-8")
        expected = (
            "Element 'ProfessionalSuffix': This element is not expected.",
            "eref="
        )
        for e in expected:
            self.assertIn(e, result)
""" """

class _04DoctypeTests(Tests):
    def test_01_add_doctype(self):
        directory = os.path.dirname(os.path.realpath(__file__))
        with open("{}/{}".format(directory, "dada.xsd"), "rb") as fp:
            xsd = fp.read().decode("utf-8")
        ctrl = {"DocTitle": "dada.xsd"}
        doc = cdr.makeCdrDoc(xsd, "schema", None, ctrl)
        response = cdr.addDoc(self.session, doc=doc, tier=self.TIER)
        self.assertTrue(response.startswith("CDR"))
        comment = "test of CdrAddDocType"
        opts = {"type": "dada", "schema": "dada.xsd", "comment": comment}
        info = cdr.dtinfo(**opts)
        response = cdr.addDoctype(self.session, info, tier=self.TIER)
        self.assertEqual(response.active, "Y")
        self.assertEqual(response.format, "xml")
        self.assertEqual(response.comment, comment)
    def test_02_list_doctypes(self):
        types = cdr.getDoctypes(self.session, tier=self.TIER)
        self.assertIn("dada", types)
    def test_03_mod_doctype(self):
        info = cdr.getDoctype(self.session, "dada", tier=self.TIER)
        info.comment = None
        info.active = "N"
        info = cdr.modDoctype(self.session, info, tier=self.TIER)
        self.assertEqual(info.active, "N")
        self.assertIsNone(info.comment)
    def test_04_list_schema_docs(self):
        titles = cdr.getSchemaDocs(self.session, tier=self.TIER)
        self.assertIn("dada.xsd", titles)
    def test_05_get_doctype(self):
        doctype = cdr.getDoctype(self.session, "xxtest", tier=self.TIER)
        self.assertIn("Generated from xxtest", doctype.dtd)
        doctype = cdr.getDoctype(self.session, "Summary", tier=self.TIER)
        self.assertIn("AvailableAsModule", doctype.dtd)
        self.assertEqual(doctype.format, "xml")
        self.assertEqual(doctype.versioning, "Y")
        self.assertEqual(doctype.active, "Y")
        vv_list = cdr.getVVList(self.session, "dada", "gimte", tier=self.TIER)
        self.assertIn("Niedersachsen", vv_list)
        self.assertIn(u"K\xf6ln", vv_list)
    def test_06_del_doctype(self):
        try:
            cdr.delDoctype(self.session, "dada", tier=self.TIER)
            types = cdr.getDoctypes(self.session, tier=self.TIER)
            self.assertNotIn("dada", types)
        finally:
            query = db.Query("document d", "d.id")
            query.join("doc_type t", "t.id = d.doc_type")
            query.where(query.Condition("d.title", "dada.xsd"))
            query.where(query.Condition("t.name", "schema"))
            for row in query.execute().fetchall():
                cdr.delDoc(self.session, row.id, tier=self.TIER)
""" """
class CDRTestData:
    doc_id = None

if __name__ == "__main__":
    unittest.main()
