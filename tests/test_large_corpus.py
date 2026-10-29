import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from geological_agent.rag.corpus_text import project, load_record, projected_document, bindings
from geological_agent.rag.corpus import cursor_encode, cursor_decode
from geological_agent.rag.corpus_worker import validate_parts, segment_end
from geological_agent.rag.profile import CHUNK_POLICY


class ProjectionTests(unittest.TestCase):
    def test_text_table_pages_are_source_bound(self):
        value=project({'parsed_content':[{'type':'text','text':'矿床\x00年龄','page_idx':3},
                     {'type':'table','table_caption':['表一'],'table_body':'<table>10 Ma</table>','page_idx':4}]})
        self.assertEqual(value['body'],'矿床␀年龄\n\n表一\n\n<table>10 Ma</table>')
        self.assertEqual([p['page'] for p in value['spans']],[4,5,5])
        self.assertEqual(value['issues'][0]['code'],'nul_display_projection')
        self.assertEqual(bindings(value['spans'],0,3),value['spans'][:1])
        self.assertFalse(value['has_original_pdf'])

    def test_string_content_no_inferred_page(self):
        value=project({'parsed_content':['a\\nb','c']})
        self.assertEqual(value['body'],'a\\nb\n\nc')
        self.assertTrue(all(s['page'] is None for s in value['spans']))

    def test_markdown_long_text_not_truncated(self):
        text='α地学\n'*50000
        value=project({'content':{'content':text}})
        self.assertEqual(value['body'],text)
        self.assertEqual(value['sha256'],hashlib.sha256(text.encode()).hexdigest())

    def test_unknown_is_explicit(self):
        value=project({'parsed_content':[{'type':'alien','text':'原文'}]})
        self.assertEqual(value['body'],'原文')
        self.assertEqual(value['issues'][0]['code'],'unrecognized_block_type')

    def test_source_hash_includes_newline_and_path_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'record.jsonl';raw=b'{"content":"test"}\n';path.write_bytes(raw)
            digest=hashlib.sha256(raw).hexdigest()
            self.assertEqual(load_record(root,'record.jsonl',0,len(raw),digest)['content'],'test')
            with self.assertRaises(ValueError):load_record(root,'record.jsonl',0,len(raw)-1,digest)
            with self.assertRaises(ValueError):load_record(root,'../record.jsonl',0,len(raw),digest)
            row={'record_path':'record.jsonl','record_offset':0,'record_length':len(raw),'record_sha':digest,'body_sha':'wrong'}
            with self.assertRaises(ValueError):projected_document(root,row)

    def test_cursor_scope(self):
        value=cursor_encode('a'*32,'owner-and-filter')
        self.assertEqual(cursor_decode(value,'owner-and-filter'),'a'*32)
        with self.assertRaises(ValueError):cursor_decode(value,'other-owner')
        with self.assertRaises(ValueError):cursor_decode('broken','owner-and-filter')

    def test_chunk_gaps_and_truncation_rejected(self):
        part={'start_char':0,'end_char':3,'text':'abc','metadata':{'chunker':CHUNK_POLICY,'token_count':2}}
        payload={'chunks':[part],'vectors':[[1.0]+[0.0]*1023]}
        self.assertEqual(len(validate_parts('abc',payload)[0]),1)
        with self.assertRaises(ValueError):validate_parts('abcd',payload)
        part['start_char']=1;part['text']='bc'
        with self.assertRaises(ValueError):validate_parts('abc',payload)

    def test_segmentation_preserves_full_text(self):
        body=('paragraph\n\n'*5000)+'end';offset=0;parts=[]
        while offset<len(body):
            end=segment_end(body,offset);self.assertGreater(end,offset);parts.append(body[offset:end]);offset=end
        self.assertEqual(''.join(parts),body)

    def test_only_source_whitespace_may_be_unembedded(self):
        text='\n\nabc\n';part={'start_char':2,'end_char':5,'text':'abc','metadata':{'chunker':CHUNK_POLICY,'token_count':2}}
        payload={'chunks':[part],'vectors':[[1.0]+[0.0]*1023]}
        self.assertEqual(len(validate_parts(text,payload)[0]),1)
        with self.assertRaises(ValueError):validate_parts('X\nabc\n',payload)
        with self.assertRaises(ValueError):validate_parts('\n\nabcX',payload)
        self.assertEqual(validate_parts('\n \t',{'chunks':[],'vectors':[]}),([],[]))
        with self.assertRaises(ValueError):validate_parts('text',{'chunks':[],'vectors':[]})

if __name__=='__main__':unittest.main()
