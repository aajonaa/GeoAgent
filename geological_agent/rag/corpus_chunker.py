"""CPU use of the exact deployed Qwen tokenizer/chunker; no model loading."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from functools import lru_cache
from .profile import CHUNK_POLICY, EMBEDDING_REVISION


@lru_cache(maxsize=1)
def components():
    config=Path(os.environ['GEOTOOL_CORPUS_CHUNKER_CONFIG'])
    if config.stat().st_mode & 0o077:raise ValueError('Private chunker configuration required')
    spec=json.loads(config.read_text())
    if spec['embedding_revision']!=EMBEDDING_REVISION or spec['chunk_policy']!=CHUNK_POLICY:
        raise ValueError('Chunker identity changed')
    for key in ('chunker','tokenizer'):
        path=Path(spec[key]['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=spec[key]['sha256']:
            raise ValueError('Frozen '+key+' SHA-256 mismatch')
    loader=importlib.util.spec_from_file_location('_corpus_frozen_chunker',spec['chunker']['path'])
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
    if module.POLICY!=CHUNK_POLICY:raise ValueError('Chunker policy mismatch')
    from tokenizers import Tokenizer
    tokenizer=Tokenizer.from_file(spec['tokenizer']['path'])
    class Adapter:
        def encode(self,text,add_special_tokens=False):return tokenizer.encode(text,add_special_tokens=add_special_tokens).ids
        def __call__(self,text,**kwargs):
            value=tokenizer.encode(text,add_special_tokens=kwargs.get('add_special_tokens',False))
            return {'input_ids':value.ids,'offset_mapping':value.offsets}
    return module,Adapter()


def encode_segment(encoder,text):
    if not text.strip():return {'chunks':[],'vectors':[]}
    module,tokenizer=components()
    all_parts=module.split_document(text,tokenizer)
    # Source formatting remains in the original body. Whitespace is never sent
    # as a pretend passage; the worker records and verifies every such gap.
    parts=[part for part in all_parts if part['text'].strip()]
    return {'chunks':parts,'vectors':encoder.embed([part['text'] for part in parts]) if parts else []}
