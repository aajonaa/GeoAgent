import copy
import unittest

from geological_agent.rag.knowledge_graph import extract_document, digest, VERSION, ENTITIES


def source(text, metadata=None):
    doc = {"id":"doc-a","body":text,"sha256":digest(text)}
    chunk = {"id":"Kdoc-a_1","document_id":"doc-a","start_char":0,"end_char":len(text),"body":text,
             "metadata":metadata or {"sources":[{"page":2},{"page":3}],"quality_status":"manual_review_required","block_ids":["p2-b1"]}}
    return doc, [chunk]


class KnowledgeGraphTests(unittest.TestCase):
    def test_exact_negation_and_unicode_evidence(self):
        doc, chunks = source("🙂本研究未发现黄铁矿与自然金共生。\n不能据此推断成矿时代。")
        original = copy.deepcopy((doc,chunks))
        rows = extract_document(doc,chunks)["mentions"]
        self.assertEqual({r["label"] for r in rows}, {"黄铁矿","自然金"})
        for r in rows:
            self.assertEqual(doc["body"][r["start_char"]:r["end_char"]],r["text"])
            self.assertIn("未发现",r["text"])
            self.assertEqual(digest(r["text"]),r["quote_sha256"])
            self.assertEqual(r["relation"],"mentions")
            self.assertEqual(r["pages"],[2,3])
            self.assertEqual(r["quality_status"],"manual_review_required")
        self.assertEqual((doc,chunks),original)

    def test_longest_alias_does_not_invent_nested_entities(self):
        rows=extract_document(*source("黄铁矿化；花岗闪长岩；西秦岭。"))["mentions"]
        self.assertEqual([r["label"] for r in rows],["黄铁矿化","花岗闪长岩","西秦岭"])

    def test_english_boundaries_and_aliases(self):
        rows=extract_document(*source("PYRITE and pyrite; arsenopyrite, not pyr-itex or apyriteX."))["mentions"]
        self.assertEqual([r["label"] for r in rows],["黄铁矿","黄铁矿","毒砂"])

    def test_distinct_deposits_are_not_merged(self):
        rows=extract_document(*source("南金山金矿与北金山金矿、柏家庄矿床与闾井矿床。"))["mentions"]
        self.assertEqual(len({r["entity_id"] for r in rows}),4)

    def test_source_hash_mismatch_rejected(self):
        doc, chunks=source("黄铁矿");doc["body"]+="伪造"
        with self.assertRaisesRegex(ValueError,"SHA-256"):extract_document(doc,chunks)

    def test_invalid_chunk_never_fuzzy_repaired(self):
        doc,chunks=source("黄铁矿");chunks[0]["body"]="黄铁矿。"
        result=extract_document(doc,chunks)
        self.assertEqual(result["mentions"],[])
        self.assertEqual(result["diagnostics"]["invalid_chunks"],1)

    def test_document_with_no_chunks_is_retained(self):
        doc,_=source("黄铁矿")
        result=extract_document(doc,[])
        self.assertEqual(result["id"],doc["id"])
        self.assertEqual(result["diagnostics"]["chunks"],0)
        self.assertEqual(result["mentions"],[])

    def test_overlapping_chunks_do_not_duplicate_same_occurrence(self):
        doc,chunks=source("李坝金矿含黄铁矿")
        chunks.append(dict(chunks[0],id="Kdoc-a_2",start_char=5,body=doc["body"][5:]))
        result=extract_document(doc,chunks)
        self.assertEqual([r["label"] for r in result["mentions"]].count("黄铁矿"),1)

    def test_reference_sections_are_excluded(self):
        for meta in ({"kind":"ref_text"},{"section_path":["7. References"]},{"physical_section_path":["参考文献"]}):
            result=extract_document(*source("黄铁矿",meta))
            self.assertEqual(result["mentions"],[])
            self.assertEqual(result["diagnostics"]["reference_chunks"],1)

    def test_missing_pages_not_invented(self):
        result=extract_document(*source("黄铁矿",{"sources":[{"page":-1},{"page":"3"},{"page":True}]}))
        self.assertEqual(result["mentions"][0]["pages"],[])
        self.assertEqual(result["mentions"][0]["page_scope"],"unavailable")

    def test_repeated_build_is_deterministic(self):
        doc,chunks=source("石英、黄铁矿。")
        self.assertEqual(extract_document(doc,chunks),extract_document(doc,chunks))
        self.assertTrue(VERSION.startswith("literature-mentions-v1-"))

    def test_version_source_and_document_bind_identity(self):
        doc,chunks=source("黄铁矿")
        first=extract_document(doc,chunks)["mentions"][0]["id"]
        doc["id"]="doc-b"
        self.assertNotEqual(first,extract_document(doc,chunks)["mentions"][0]["id"])

    def test_vocabulary_identity_is_unique(self):
        self.assertEqual(len(ENTITIES),len({(r["kind"],r["label"]) for r in ENTITIES.values()}))

    def test_quote_bounded_and_source_unchanged(self):
        text="无"*1000+"黄铁矿"+"无"*1000
        row=extract_document(*source(text))["mentions"][0]
        self.assertLessEqual(len(row["text"]),273)
        self.assertEqual(row["mention_start"],1000)


if __name__=="__main__":unittest.main()
